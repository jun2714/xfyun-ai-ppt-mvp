from __future__ import annotations

import os


def apply_dmx_compat_env() -> None:
    """Expose the shared DMX credential to compatible provider runtimes.

    TeachNova uses one DMXAPI key for Kimi K3 and Gemini image generation.  The
    upstream presentation engine still reads provider-specific environment names in
    a few places (for example GOOGLE_API_KEY/GEMINI_IMAGE_MODEL).  Keep those code
    paths intact and bridge the DMX configuration once at API startup instead of
    asking operators to duplicate the same key into multiple variables.

    Explicit provider-specific values always win via ``setdefault`` semantics.
    """
    dmx_key = (os.getenv("DMX_API_KEY") or "").strip()
    if not dmx_key:
        return

    dmx_image_style = (os.getenv("DMX_IMAGE_API_STYLE") or "").strip().casefold()
    dmx_image_model = (os.getenv("DMX_IMAGE_MODEL") or "").strip()
    dmx_gemini_base_url = (os.getenv("DMX_GEMINI_BASE_URL") or "").strip().rstrip("/")

    if dmx_image_style == "gemini" and dmx_image_model:
        os.environ.setdefault("IMAGE_PROVIDER", "gemini_flash")
        os.environ.setdefault("GOOGLE_API_KEY", dmx_key)
        os.environ.setdefault("GEMINI_IMAGE_MODEL", dmx_image_model)
        if dmx_gemini_base_url:
            os.environ.setdefault("GEMINI_IMAGE_BASE_URL", dmx_gemini_base_url)
