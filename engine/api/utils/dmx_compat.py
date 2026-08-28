from __future__ import annotations

import os


def apply_dmx_compat_env() -> None:
    """Bridge one DMXAPI credential into compatible provider-specific env names.

    The upstream engine still reads ``GOOGLE_API_KEY``, ``GEMINI_IMAGE_MODEL`` and
    ``IMAGE_PROVIDER`` in its Gemini image path.  TeachNova intentionally keeps one
    DMXAPI key, so map the DMX image configuration once at API startup.  Explicit
    provider-specific values always win.
    """
    dmx_key = (os.getenv("DMX_API_KEY") or "").strip()
    if not dmx_key:
        return

    image_style = (os.getenv("DMX_IMAGE_API_STYLE") or "").strip().casefold()
    image_model = (os.getenv("DMX_IMAGE_MODEL") or "").strip()
    gemini_base_url = (os.getenv("DMX_GEMINI_BASE_URL") or "").strip().rstrip("/")

    if image_style == "gemini" and image_model:
        os.environ.setdefault("IMAGE_PROVIDER", "gemini_flash")
        os.environ.setdefault("GOOGLE_API_KEY", dmx_key)
        os.environ.setdefault("GEMINI_IMAGE_MODEL", image_model)
        if gemini_base_url:
            os.environ.setdefault("GEMINI_IMAGE_BASE_URL", gemini_base_url)
