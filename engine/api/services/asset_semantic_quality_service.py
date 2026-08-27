from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from typing import Literal, Protocol

import aiohttp
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from constants.llm import DEFAULT_GOOGLE_MODEL, DEFAULT_OPENAI_MODEL
from models.sql.image_asset import ImageAsset
from services.asset_planning_service import AssetSemanticExpectation


class AssetSemanticCheck(BaseModel):
    planning_slot: str
    semantic_label: str
    present: bool
    detected_count: int | None = Field(default=None, ge=0, le=50)
    features_match: bool = True
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=500)


class AssetSemanticQualityResult(BaseModel):
    passed: bool = False
    checks: list[AssetSemanticCheck] = Field(default_factory=list, max_length=24)
    overall_reason: str = Field(default="", max_length=1000)
    provider: str | None = None
    model: str | None = None


class AssetSemanticQualityError(ValueError):
    def __init__(self, result: AssetSemanticQualityResult):
        self.result = result
        failed = [
            check.semantic_label
            for check in result.checks
            if not check.present or not check.features_match
        ]
        detail = ", ".join(failed) or result.overall_reason or "语义不匹配"
        super().__init__(f"图片语义质检未通过：{detail}")


class AssetSemanticQualityService(Protocol):
    async def validate(
        self,
        image: str | ImageAsset,
        expectations: tuple[AssetSemanticExpectation, ...],
    ) -> AssetSemanticQualityResult: ...


class VisionAssetSemanticQualityService:
    """Provider-backed visual QA for generated teaching assets.

    The service is intentionally independent from image generation. It only receives
    the finished image and structured expectations, so callers can retry one failed
    asset request without regenerating the rest of the presentation.
    """

    def __init__(
        self,
        provider: Literal["openai", "google"],
        model: str,
        *,
        confidence_threshold: float = 0.70,
    ):
        self.provider = provider
        self.model = model
        self.confidence_threshold = max(0.0, min(confidence_threshold, 1.0))

    async def validate(
        self,
        image: str | ImageAsset,
        expectations: tuple[AssetSemanticExpectation, ...],
    ) -> AssetSemanticQualityResult:
        required = tuple(expectation for expectation in expectations if expectation.qa_required)
        if not required:
            return AssetSemanticQualityResult(
                passed=True,
                provider=self.provider,
                model=self.model,
                overall_reason="没有需要执行视觉语义质检的资产契约。",
            )

        prompt = _build_quality_prompt(required)
        if self.provider == "openai":
            result = await self._validate_openai(image, prompt)
        else:
            result = await self._validate_google(image, prompt)
        result.provider = self.provider
        result.model = self.model
        return _enforce_expectations(result, required, self.confidence_threshold)

    async def _validate_openai(
        self,
        image: str | ImageAsset,
        prompt: str,
    ) -> AssetSemanticQualityResult:
        image_url = await _openai_image_url(image)
        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url, "detail": "low"},
                        },
                    ],
                }
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        return AssetSemanticQualityResult.model_validate(json.loads(content))

    async def _validate_google(
        self,
        image: str | ImageAsset,
        prompt: str,
    ) -> AssetSemanticQualityResult:
        data, mime_type = await _image_bytes_and_mime(image)
        client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
        response = await client.aio.models.generate_content(
            model=self.model,
            contents=[
                prompt,
                types.Part.from_bytes(data=data, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )
        return AssetSemanticQualityResult.model_validate(json.loads(response.text or "{}"))


def build_default_asset_semantic_quality_service(
) -> AssetSemanticQualityService | None:
    """Create visual QA only when a supported vision provider is configured.

    `ASSET_SEMANTIC_QA_PROVIDER` accepts auto/openai/google/off. Auto prefers the
    currently selected LLM provider when it is OpenAI/Google, then falls back to any
    configured supported key. Generic decks continue to work when no vision key is
    configured; prompt-level semantic preflight remains active independently.
    """
    requested = (os.getenv("ASSET_SEMANTIC_QA_PROVIDER") or "auto").strip().casefold()
    if requested in {"off", "disabled", "none", "0", "false"}:
        return None
    if requested not in {"auto", "openai", "google"}:
        raise ValueError(
            "ASSET_SEMANTIC_QA_PROVIDER must be auto, openai, google, or off"
        )

    selected_llm = (os.getenv("LLM") or "").strip().casefold()
    openai_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    google_key = (os.getenv("GOOGLE_API_KEY") or "").strip()

    provider: Literal["openai", "google"] | None = None
    if requested == "openai":
        if not openai_key:
            raise ValueError("ASSET_SEMANTIC_QA_PROVIDER=openai requires OPENAI_API_KEY")
        provider = "openai"
    elif requested == "google":
        if not google_key:
            raise ValueError("ASSET_SEMANTIC_QA_PROVIDER=google requires GOOGLE_API_KEY")
        provider = "google"
    elif selected_llm == "openai" and openai_key:
        provider = "openai"
    elif selected_llm == "google" and google_key:
        provider = "google"
    elif openai_key:
        provider = "openai"
    elif google_key:
        provider = "google"

    if provider is None:
        return None

    if provider == "openai":
        model = (
            os.getenv("ASSET_SEMANTIC_QA_MODEL")
            or os.getenv("OPENAI_MODEL")
            or DEFAULT_OPENAI_MODEL
        )
    else:
        model = (
            os.getenv("ASSET_SEMANTIC_QA_MODEL")
            or os.getenv("GOOGLE_MODEL")
            or DEFAULT_GOOGLE_MODEL
        )

    try:
        threshold = float(os.getenv("ASSET_SEMANTIC_QA_CONFIDENCE", "0.70"))
    except ValueError:
        threshold = 0.70
    return VisionAssetSemanticQualityService(
        provider,
        model,
        confidence_threshold=threshold,
    )


def _build_quality_prompt(
    expectations: tuple[AssetSemanticExpectation, ...],
) -> str:
    contracts = [
        {
            "planning_slot": expectation.planning_slot,
            "semantic_label": expectation.semantic_label,
            "expected_count": expectation.expected_count,
            "role": expectation.role,
            "description": expectation.description,
        }
        for expectation in expectations
    ]
    return (
        "你是幼儿教学图片的视觉语义质检器。只判断图片是否满足给定结构化契约，"
        "不要评价审美，不要猜测页面文字，也不要因为画风不同而判错。\n"
        "逐项检查：1) 指定主体/局部特征是否真的可见；2) 非背景主体数量是否符合"
        "expected_count；3) description 中可直接从图片验证的关键特征是否满足。"
        "如果主体被遮挡到无法教学辨认，应判 features_match=false。"
        "背景类契约不要求 detected_count 精确。\n"
        "返回纯 JSON：{\"passed\":false,\"checks\":[{\"planning_slot\":\"...\","
        "\"semantic_label\":\"...\",\"present\":true,\"detected_count\":1,"
        "\"features_match\":true,\"confidence\":0.95,\"reason\":\"...\"}],"
        "\"overall_reason\":\"...\"}。checks 必须与契约逐项一一对应。\n"
        f"资产契约：{json.dumps(contracts, ensure_ascii=False)}"
    )


def _enforce_expectations(
    result: AssetSemanticQualityResult,
    expectations: tuple[AssetSemanticExpectation, ...],
    confidence_threshold: float,
) -> AssetSemanticQualityResult:
    by_key = {
        (
            check.planning_slot.strip().casefold(),
            check.semantic_label.strip().casefold(),
        ): check
        for check in result.checks
    }
    normalized_checks: list[AssetSemanticCheck] = []
    failures: list[str] = []

    for expectation in expectations:
        key = (
            expectation.planning_slot.strip().casefold(),
            expectation.semantic_label.strip().casefold(),
        )
        check = by_key.get(key)
        if check is None:
            check = AssetSemanticCheck(
                planning_slot=expectation.planning_slot,
                semantic_label=expectation.semantic_label,
                present=False,
                detected_count=None,
                features_match=False,
                confidence=0.0,
                reason="视觉模型没有返回该资产契约的检查结果。",
            )
        count_matches = True
        if expectation.role != "background":
            count_matches = check.detected_count == expectation.expected_count
        check_passed = (
            check.present
            and check.features_match
            and count_matches
            and check.confidence >= confidence_threshold
        )
        if not check_passed:
            parts: list[str] = []
            if not check.present:
                parts.append("主体缺失")
            if not check.features_match:
                parts.append("关键特征不符")
            if not count_matches:
                parts.append(
                    f"数量应为 {expectation.expected_count}，检测为 {check.detected_count}"
                )
            if check.confidence < confidence_threshold:
                parts.append(
                    f"置信度 {check.confidence:.2f} 低于 {confidence_threshold:.2f}"
                )
            failures.append(
                f"{expectation.semantic_label}：{'；'.join(parts) or check.reason}"
            )
        normalized_checks.append(check)

    result.checks = normalized_checks
    result.passed = not failures
    if failures:
        result.overall_reason = " | ".join(failures)[:1000]
    elif not result.overall_reason:
        result.overall_reason = "图片满足全部教学语义契约。"
    return result


async def _openai_image_url(image: str | ImageAsset) -> str:
    value = image.path if isinstance(image, ImageAsset) else image
    if value.startswith(("http://", "https://", "data:")):
        return value
    data, mime_type = await _image_bytes_and_mime(image)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


async def _image_bytes_and_mime(image: str | ImageAsset) -> tuple[bytes, str]:
    value = image.path if isinstance(image, ImageAsset) else image
    if value.startswith("data:"):
        header, encoded = value.split(",", 1)
        mime_type = header[5:].split(";", 1)[0] or "image/png"
        return base64.b64decode(encoded), mime_type

    if value.startswith(("http://", "https://")):
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(value) as response:
                response.raise_for_status()
                if response.content_length and response.content_length > 12 * 1024 * 1024:
                    raise ValueError("Semantic QA image exceeds 12 MB")
                data = await response.read()
                if len(data) > 12 * 1024 * 1024:
                    raise ValueError("Semantic QA image exceeds 12 MB")
                content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0]
                return data, content_type or _mime_type_for_path(value)

    path = Path(value)
    if not path.is_file():
        raise FileNotFoundError(f"Semantic QA image not found: {value}")
    if path.stat().st_size > 12 * 1024 * 1024:
        raise ValueError("Semantic QA image exceeds 12 MB")
    return path.read_bytes(), _mime_type_for_path(value)


def _mime_type_for_path(value: str) -> str:
    guessed, _ = mimetypes.guess_type(value.split("?", 1)[0])
    return guessed if guessed and guessed.startswith("image/") else "image/png"
