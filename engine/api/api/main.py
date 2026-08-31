import os
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import FileResponse

from api.lifespan import app_lifespan
from api.middlewares import SessionAuthMiddleware, UserConfigEnvUpdateMiddleware
from api.v1.async_tasks.router import API_V1_ASYNC_TASKS_ROUTER
from api.v1.auth.router import API_V1_AUTH_ROUTER
from api.v1.admin.router import API_V1_ADMIN_ROUTER
from api.v1.mock.router import API_V1_MOCK_ROUTER
from api.v1.ppt.router import API_V1_PPT_ROUTER
from api.v1.webhook.router import API_V1_WEBHOOK_ROUTER
from utils.dmx_compat import apply_dmx_compat_env
from utils.get_env import (
    get_app_data_directory_env,
    get_sentry_dsn_env,
    get_sentry_send_default_pii_env,
    get_sentry_traces_sample_rate_env,
    get_teachnova_cors_origins,
)
from utils.mime_types import init_sandbox_safe_mimetypes
from utils.path_helpers import get_resource_path


apply_dmx_compat_env()
init_sandbox_safe_mimetypes()


def _maybe_init_sentry() -> None:
    sentry_dsn = get_sentry_dsn_env()
    if not sentry_dsn:
        return

    try:
        import sentry_sdk
    except Exception:
        # Sentry SDK is optional in some runtime targets.
        return

    traces_sample_rate = get_sentry_traces_sample_rate_env()
    send_default_pii = get_sentry_send_default_pii_env()
    try:
        parsed_sample_rate = (
            float(traces_sample_rate) if traces_sample_rate is not None else 1.0
        )
    except ValueError:
        parsed_sample_rate = 1.0

    parsed_send_default_pii = (
        send_default_pii.lower() == "true" if send_default_pii is not None else True
    )

    sentry_sdk.init(
        dsn=sentry_dsn,
        send_default_pii=parsed_send_default_pii,
        traces_sample_rate=parsed_sample_rate,
    )


_maybe_init_sentry()

app = FastAPI(lifespan=app_lifespan)

# Routers
app.include_router(API_V1_PPT_ROUTER)
app.include_router(API_V1_WEBHOOK_ROUTER)
app.include_router(API_V1_MOCK_ROUTER)
app.include_router(API_V1_AUTH_ROUTER)
app.include_router(API_V1_ADMIN_ROUTER)
app.include_router(API_V1_ASYNC_TASKS_ROUTER)

# Mount app_data and static assets (direct FastAPI access; nginx also serves /static in Docker).
app_data_dir = get_app_data_directory_env()
if app_data_dir:
    os.makedirs(app_data_dir, exist_ok=True)
    app.mount("/app_data", StaticFiles(directory=app_data_dir), name="app_data")

static_dir = get_resource_path("static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


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


# Electron/local development serves Next.js (5001), the outline web app (5173),
# the TeachNova shell (3030) and FastAPI (8000) from separate loopback origins.
# Production is same-origin/reverse-proxied, but developers often keep
# NEXT_PUBLIC_URL set to the production editor URL while NEXT_PUBLIC_FAST_API is
# loopback. In that mixed setup the old CORS list excluded 127.0.0.1:5001 and
# EventSource failed before slide streaming could start.
def _cors_origins() -> list[str]:
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

        # Only expose development loopback origins when the configured public
        # FastAPI endpoint is itself loopback. This keeps production CORS tight.
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


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Content-Length", "Content-Type"],
)

app.add_middleware(UserConfigEnvUpdateMiddleware)
app.add_middleware(SessionAuthMiddleware)


@app.middleware("http")
async def static_icon_fallback_middleware(request: Request, call_next):
    """Serve placeholder when icon paths are missing (e.g. renamed Phosphor icons)."""
    response = await call_next(request)
    if response.status_code != 404:
        return response
    path = request.url.path
    if not path.startswith("/static/icons/"):
        return response
    placeholder = get_resource_path("static/icons/placeholder.svg")
    if not os.path.isfile(placeholder):
        return response
    return FileResponse(placeholder, media_type="image/svg+xml")


import logging as _logging
import traceback as _traceback

_err_logger = _logging.getLogger("api.error_catcher")

_inner_app = app


class _ErrorLoggingASGIMiddleware:
    """Pure ASGI middleware that logs exceptions before ServerErrorMiddleware swallows them."""
    def __init__(self, wrapped):
        self.app = wrapped

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except Exception:
            _err_logger.error(
                "Unhandled ASGI error for %s %s:\n%s",
                scope.get("method", "?"), scope.get("path", "?"),
                _traceback.format_exc(),
            )
            raise


app = _ErrorLoggingASGIMiddleware(_inner_app)
