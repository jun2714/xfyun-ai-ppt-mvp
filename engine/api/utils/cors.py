from __future__ import annotations

import os
from urllib.parse import urlparse

from utils.get_env import get_teachnova_cors_origins


def _is_loopback_url(value: str | None) -> bool:
    if not value:
        return False
    try:
        return urlparse(value).hostname in {"127.0.0.1", "localhost"}
    except Exception:
        return False


def _append_origin(origins: list[str], value: str | None) -> None:
    origin = (value or "").strip().rstrip("/")
    if origin and origin not in origins:
        origins.append(origin)


def build_cors_origins() -> list[str]:
    """Build credential-safe CORS origins for production and local split-port UI.

    Production normally uses a reverse proxy/same origin. Local development may
    combine the editor on 5001, outline web on 5173, TeachNova shell on 3030 and
    FastAPI on 8000. We only add those loopback UI origins when the configured
    public FastAPI URL is itself loopback, so production CORS stays narrow.
    """
    next_public_origin = (os.getenv("NEXT_PUBLIC_URL") or "").strip().rstrip("/")
    origins: list[str] = []
    if not next_public_origin:
        origins = ["*"]
    else:
        _append_origin(origins, next_public_origin)
        if _is_loopback_url(next_public_origin):
            parsed = urlparse(next_public_origin)
            alt_host = "localhost" if parsed.hostname == "127.0.0.1" else "127.0.0.1"
            alt = f"{parsed.scheme}://{alt_host}"
            if parsed.port:
                alt = f"{alt}:{parsed.port}"
            _append_origin(origins, alt)

    if origins != ["*"]:
        for origin in get_teachnova_cors_origins():
            _append_origin(origins, origin)

        if _is_loopback_url(os.getenv("NEXT_PUBLIC_FAST_API")):
            for origin in (
                "http://127.0.0.1:5001",
                "http://localhost:5001",
                "http://127.0.0.1:5173",
                "http://localhost:5173",
                "http://127.0.0.1:3030",
                "http://localhost:3030",
            ):
                _append_origin(origins, origin)

    return origins
