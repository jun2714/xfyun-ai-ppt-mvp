from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version

from fastapi import APIRouter
from pydantic import BaseModel

from utils.image_provider import (
    get_selected_image_provider,
    is_image_generation_disabled,
)
from utils.oss_storage import is_oss_enabled


DIAGNOSTICS_ROUTER = APIRouter(prefix="/diagnostics", tags=["Diagnostics"])
MIN_GOOGLE_GENAI_VERSION = "2.21.0"
GENERATION_STABILITY_REVISION = "asset-v2-text-fit-v1"


class ImageRuntimeResponse(BaseModel):
    generation_stability_revision: str
    provider: str | None
    model: str | None
    base_url: str | None
    timeout_seconds: float
    concurrency: int
    disabled: bool
    oss_enabled: bool
    google_genai_version: str | None
    google_genai_minimum: str
    google_genai_compatible: bool


def _version_tuple(raw_version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in raw_version.split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _google_genai_runtime() -> tuple[str | None, bool]:
    try:
        installed = version("google-genai")
    except PackageNotFoundError:
        return None, False
    return installed, _version_tuple(installed) >= _version_tuple(MIN_GOOGLE_GENAI_VERSION)


def _bounded_timeout() -> float:
    try:
        return max(10.0, float(os.getenv("IMAGE_GENERATION_TIMEOUT_SECONDS", "75")))
    except ValueError:
        return 75.0


def _bounded_concurrency() -> int:
    try:
        return max(1, min(6, int(os.getenv("ASSET_GENERATION_CONCURRENCY", "4"))))
    except ValueError:
        return 4


def resolve_image_runtime() -> ImageRuntimeResponse:
    """Return non-secret image generation routing for local/production diagnostics."""
    provider = get_selected_image_provider()
    provider_name = provider.value if provider is not None else None

    model: str | None = None
    base_url: str | None = None
    if provider_name == "gemini_flash":
        model = (
            os.getenv("GEMINI_IMAGE_MODEL")
            or os.getenv("DMX_IMAGE_MODEL")
            or "gemini-2.5-flash-image"
        ).strip()
        base_url = (
            os.getenv("GEMINI_IMAGE_BASE_URL")
            or os.getenv("DMX_GEMINI_BASE_URL")
            or "https://generativelanguage.googleapis.com"
        ).strip().rstrip("/")
    elif provider_name == "nanobanana_pro":
        model = "gemini-3-pro-image-preview"
    elif provider_name == "dall-e-3":
        model = "dall-e-3"
    elif provider_name == "gpt-image-1.5":
        model = "gpt-image-1.5"
    elif provider_name == "openai_compatible":
        model = (os.getenv("OPENAI_COMPAT_IMAGE_MODEL") or "openai-compatible").strip()
        base_url = (os.getenv("OPENAI_COMPAT_IMAGE_BASE_URL") or "").strip().rstrip("/") or None
    elif provider_name:
        model = provider_name

    google_genai_version, google_genai_compatible = _google_genai_runtime()
    return ImageRuntimeResponse(
        generation_stability_revision=GENERATION_STABILITY_REVISION,
        provider=provider_name,
        model=model,
        base_url=base_url,
        timeout_seconds=_bounded_timeout(),
        concurrency=_bounded_concurrency(),
        disabled=is_image_generation_disabled(),
        oss_enabled=is_oss_enabled(),
        google_genai_version=google_genai_version,
        google_genai_minimum=MIN_GOOGLE_GENAI_VERSION,
        google_genai_compatible=google_genai_compatible,
    )


@DIAGNOSTICS_ROUTER.get("/image-runtime", response_model=ImageRuntimeResponse)
async def image_runtime():
    """Expose model/provider routing without keys so deployments can verify restarts."""
    return resolve_image_runtime()
