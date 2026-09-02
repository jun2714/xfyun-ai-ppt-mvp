import os

from api.v1.ppt.endpoints.diagnostics import resolve_image_runtime
from utils.dmx_compat import apply_dmx_compat_env


_KEYS = (
    "DMX_API_KEY",
    "DMX_IMAGE_API_STYLE",
    "DMX_IMAGE_MODEL",
    "DMX_GEMINI_BASE_URL",
    "IMAGE_PROVIDER",
    "GOOGLE_API_KEY",
    "GEMINI_IMAGE_MODEL",
    "GEMINI_IMAGE_BASE_URL",
    "IMAGE_GENERATION_TIMEOUT_SECONDS",
    "ASSET_GENERATION_CONCURRENCY",
    "DISABLE_IMAGE_GENERATION",
)


def _clear(monkeypatch):
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)


def test_image_runtime_reports_migrated_flash_lite_model(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-key")
    monkeypatch.setenv("DMX_IMAGE_API_STYLE", "gemini")
    monkeypatch.setenv("DMX_IMAGE_MODEL", "gemini-3.1-flash-image")
    monkeypatch.setenv("DMX_GEMINI_BASE_URL", "https://www.dmxapi.cn")
    monkeypatch.setenv("IMAGE_GENERATION_TIMEOUT_SECONDS", "75")
    monkeypatch.setenv("ASSET_GENERATION_CONCURRENCY", "4")

    apply_dmx_compat_env()
    runtime = resolve_image_runtime()

    assert runtime.provider == "gemini_flash"
    assert runtime.model == "gemini-3.1-flash-lite-image"
    assert runtime.base_url == "https://www.dmxapi.cn"
    assert runtime.timeout_seconds == 75
    assert runtime.concurrency == 4
    assert runtime.disabled is False
    assert runtime.google_genai_version is not None
    assert runtime.google_genai_minimum == "2.21.0"
    assert runtime.google_genai_compatible is True


def test_image_runtime_bounds_invalid_operational_values(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-key")
    monkeypatch.setenv("DMX_IMAGE_API_STYLE", "gemini")
    monkeypatch.setenv("IMAGE_GENERATION_TIMEOUT_SECONDS", "bad")
    monkeypatch.setenv("ASSET_GENERATION_CONCURRENCY", "99")

    apply_dmx_compat_env()
    runtime = resolve_image_runtime()

    assert runtime.model == "gemini-3.1-flash-lite-image"
    assert runtime.timeout_seconds == 75
    assert runtime.concurrency == 6


def test_provider_specific_model_remains_visible_in_diagnostics(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-key")
    monkeypatch.setenv("DMX_IMAGE_API_STYLE", "gemini")
    monkeypatch.setenv("DMX_IMAGE_MODEL", "gemini-3.1-flash-image")
    monkeypatch.setenv("GEMINI_IMAGE_MODEL", "manual-test-model")
    monkeypatch.setenv("GEMINI_IMAGE_BASE_URL", "https://google.example")

    apply_dmx_compat_env()
    runtime = resolve_image_runtime()

    assert runtime.model == "manual-test-model"
    assert runtime.base_url == "https://google.example"
    assert os.environ["DMX_IMAGE_MODEL"] == "gemini-3.1-flash-image"
