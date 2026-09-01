from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import HTTPException
from llmai.shared import ClientConfig, OpenAIClientConfig

from utils.llm_config import get_llm_config
from utils.llm_provider import get_model


@dataclass(frozen=True)
class KindergartenPlannerRuntime:
    config: ClientConfig
    model: str
    source: str
    profile: str
    request_extra_body: dict | None
    max_tokens: int
    timeout_seconds: float
    total_timeout_seconds: float
    stream: bool


FAST_PROFILE = "fast"
PREMIUM_PROFILE = "premium"
DEFAULT_MODEL = "deepseek-v4-pro-0813"
FAST_MODEL = DEFAULT_MODEL
FAST_MAX_TOKENS = 16_000
# DeepSeek V4 Pro is now the default kindergarten outline planner. It may spend
# longer internally reasoning before a schema-rich ten-page lesson is complete,
# so keep a generous per-call budget while still bounding the browser wait. The
# total budget leaves one extra minute of headroom around the single quality-
# repair attempt used downstream instead of ending exactly at 2 x call timeout.
FAST_CALL_TIMEOUT_SECONDS = 180.0
FAST_TOTAL_TIMEOUT_SECONDS = 420.0


def _positive_number_env(name: str, default: str, cast):
    raw_value = (os.getenv(name) or default).strip()
    try:
        value = cast(raw_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{name} must be a positive number.",
        ) from exc
    if value <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"{name} must be a positive number.",
        )
    return value


def _is_kimi_model(model: str) -> bool:
    return "kimi" in model.strip().lower()


def _normalize_planner_model(model: str | None) -> str:
    candidate = (model or "").strip()
    # Old deployments may still carry KINDERGARTEN_PLANNER_MODEL=kimi-k3 or a
    # Kimi fast override in their environment. Treat those as stale settings so
    # a restart immediately moves this outline path to DeepSeek without requiring
    # the operator to find and remove every old environment variable first.
    if not candidate or _is_kimi_model(candidate):
        return DEFAULT_MODEL
    return candidate


def _planner_request_extra_body(model: str) -> dict | None:
    # Do not force Kimi-style reasoning/thinking flags onto DeepSeek or future
    # OpenAI-compatible planner models. Provider-specific options can be added
    # here later if a tested model actually requires them.
    _ = model
    return None


def _build_runtime(
    *,
    config: ClientConfig,
    model: str,
    source: str,
    profile: str,
) -> KindergartenPlannerRuntime:
    if profile == FAST_PROFILE:
        call_timeout_seconds = _positive_number_env(
            "KINDERGARTEN_PLANNER_FAST_TIMEOUT_SECONDS",
            str(FAST_CALL_TIMEOUT_SECONDS),
            float,
        )
        total_timeout_seconds = _positive_number_env(
            "KINDERGARTEN_PLANNER_FAST_TOTAL_TIMEOUT_SECONDS",
            str(FAST_TOTAL_TIMEOUT_SECONDS),
            float,
        )
        if total_timeout_seconds < call_timeout_seconds:
            raise HTTPException(
                status_code=400,
                detail=(
                    "KINDERGARTEN_PLANNER_FAST_TOTAL_TIMEOUT_SECONDS must be "
                    "greater than or equal to KINDERGARTEN_PLANNER_FAST_TIMEOUT_SECONDS."
                ),
            )
        return KindergartenPlannerRuntime(
            config=config,
            model=model,
            source=source,
            profile=profile,
            request_extra_body=_planner_request_extra_body(model),
            max_tokens=_positive_number_env(
                "KINDERGARTEN_PLANNER_FAST_MAX_TOKENS",
                str(FAST_MAX_TOKENS),
                int,
            ),
            timeout_seconds=call_timeout_seconds,
            total_timeout_seconds=total_timeout_seconds,
            stream=True,
        )

    timeout_seconds = _positive_number_env(
        "KINDERGARTEN_PLANNER_TIMEOUT_SECONDS",
        "240",
        float,
    )
    return KindergartenPlannerRuntime(
        config=config,
        model=model,
        source=source,
        profile=profile,
        request_extra_body=_planner_request_extra_body(model),
        max_tokens=_positive_number_env(
            "KINDERGARTEN_PLANNER_MAX_TOKENS",
            "32768",
            int,
        ),
        timeout_seconds=timeout_seconds,
        total_timeout_seconds=timeout_seconds * 2,
        stream=True,
    )


def _planner_profile() -> str:
    profile = (
        os.getenv("KINDERGARTEN_PLANNER_PROFILE") or FAST_PROFILE
    ).strip().lower()
    if profile not in {FAST_PROFILE, PREMIUM_PROFILE}:
        raise HTTPException(
            status_code=400,
            detail="KINDERGARTEN_PLANNER_PROFILE must be fast or premium.",
        )
    return profile


def _planner_model(profile: str, configured_model: str) -> str:
    if profile == FAST_PROFILE:
        candidate = (
            os.getenv("KINDERGARTEN_PLANNER_FAST_MODEL")
            or configured_model
            or DEFAULT_MODEL
        )
        return _normalize_planner_model(candidate)
    return _normalize_planner_model(configured_model or DEFAULT_MODEL)


def get_kindergarten_planner_runtime() -> KindergartenPlannerRuntime:
    """Resolve the model runtime used by kindergarten lesson planning.

    DeepSeek V4 Pro is the default for both planner profiles. Existing Kimi model
    environment values are treated as stale and replaced by the DeepSeek default.
    A different non-Kimi model can still be tested later through
    ``KINDERGARTEN_PLANNER_MODEL`` or ``KINDERGARTEN_PLANNER_FAST_MODEL`` without
    another code change.
    """
    planner_base_url = (
        os.getenv("KINDERGARTEN_PLANNER_BASE_URL") or ""
    ).strip().rstrip("/")
    planner_api_key = (os.getenv("KINDERGARTEN_PLANNER_API_KEY") or "").strip()
    configured_model = (os.getenv("KINDERGARTEN_PLANNER_MODEL") or "").strip()
    profile = _planner_profile()
    planner_model = _planner_model(profile, configured_model)

    dmx_base_url = (
        os.getenv("DMX_API_BASE_URL") or "https://www.dmxapi.cn/v1"
    ).strip().rstrip("/")
    dmx_api_key = (os.getenv("DMX_API_KEY") or "").strip()

    if planner_api_key:
        if not planner_base_url:
            raise HTTPException(
                status_code=400,
                detail=(
                    "KINDERGARTEN_PLANNER_API_KEY is set, so "
                    "KINDERGARTEN_PLANNER_BASE_URL must also be set."
                ),
            )
        return _build_runtime(
            config=OpenAIClientConfig(
                base_url=planner_base_url,
                api_key=planner_api_key,
            ),
            model=planner_model,
            source="dedicated-openai-compatible",
            profile=profile,
        )

    if dmx_api_key:
        return _build_runtime(
            config=OpenAIClientConfig(
                base_url=dmx_base_url,
                api_key=dmx_api_key,
            ),
            model=planner_model,
            source="shared-dmx-openai-compatible",
            profile=profile,
        )

    if not configured_model and not planner_base_url:
        return _build_runtime(
            config=get_llm_config(),
            model=get_model(),
            source="global",
            profile=PREMIUM_PROFILE,
        )

    raise HTTPException(
        status_code=400,
        detail=(
            "Kindergarten planner needs DMX_API_KEY, or a complete dedicated "
            "KINDERGARTEN_PLANNER_BASE_URL + KINDERGARTEN_PLANNER_API_KEY pair."
        ),
    )
