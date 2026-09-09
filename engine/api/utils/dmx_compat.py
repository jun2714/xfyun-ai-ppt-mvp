from __future__ import annotations

import os


DEFAULT_DMX_GEMINI_IMAGE_MODEL = "gemini-3.1-flash-lite-image"
# Older local .env files still contain the previous default. Treat only that exact
# value as stale so the user's explicit custom model names continue to win.
_STALE_DMX_GEMINI_IMAGE_MODELS = {
    "gemini-3.1-flash-image",
}


def _resolved_dmx_gemini_model() -> str:
    configured = (os.getenv("DMX_IMAGE_MODEL") or "").strip()
    if not configured or configured in _STALE_DMX_GEMINI_IMAGE_MODELS:
        return DEFAULT_DMX_GEMINI_IMAGE_MODEL
    return configured


def apply_dmx_compat_env() -> None:
    """Bridge one DMXAPI credential into compatible provider-specific env names.

    The upstream engine still reads ``GOOGLE_API_KEY``, ``GEMINI_IMAGE_MODEL`` and
    ``IMAGE_PROVIDER`` in its Gemini image path. TeachNova intentionally keeps one
    DMXAPI key, so map the DMX image configuration once at API startup. Explicit
    provider-specific values always win.

    The previous TeachNova default was ``gemini-3.1-flash-image``. Local deployments
    commonly keep that value in an untracked .env file, so migrate that one known
    stale default to the current low-latency ``gemini-3.1-flash-lite-image`` model.
    Arbitrary custom model names are never rewritten.
    """
    dmx_key = (os.getenv("DMX_API_KEY") or "").strip()
    if not dmx_key:
        return

    image_style = (os.getenv("DMX_IMAGE_API_STYLE") or "").strip().casefold()
    gemini_base_url = (os.getenv("DMX_GEMINI_BASE_URL") or "").strip().rstrip("/")

    if image_style == "gemini":
        image_model = _resolved_dmx_gemini_model()
        os.environ.setdefault("IMAGE_PROVIDER", "gemini_flash")
        os.environ.setdefault("GOOGLE_API_KEY", dmx_key)

        # A provider-specific override is the escape hatch for deliberate model
        # experiments. Otherwise normalize the shared DMX setting too, so runtime
        # diagnostics and generation agree on the model actually being called.
        if not (os.getenv("GEMINI_IMAGE_MODEL") or "").strip():
            os.environ["DMX_IMAGE_MODEL"] = image_model
            os.environ["GEMINI_IMAGE_MODEL"] = image_model

        if gemini_base_url:
            os.environ.setdefault("GEMINI_IMAGE_BASE_URL", gemini_base_url)
