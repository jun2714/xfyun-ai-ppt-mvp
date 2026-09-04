import os

from utils.dmx_compat import (
    DEFAULT_DMX_GEMINI_IMAGE_MODEL,
    apply_dmx_compat_env,
)


_KEYS = (
    "DMX_API_KEY",
    "DMX_IMAGE_API_STYLE",
    "DMX_IMAGE_MODEL",
    "DMX_GEMINI_BASE_URL",
    "IMAGE_PROVIDER",
    "GOOGLE_API_KEY",
    "GEMINI_IMAGE_MODEL",
    "GEMINI_IMAGE_BASE_URL",
)


def _clear(monkeypatch):
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)


def test_dmx_gemini_config_reuses_shared_key_and_current_lite_model(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-key")
    monkeypatch.setenv("DMX_IMAGE_API_STYLE", "gemini")
    monkeypatch.setenv("DMX_IMAGE_MODEL", "gemini-3.1-flash-lite-image")
    monkeypatch.setenv("DMX_GEMINI_BASE_URL", "https://www.dmxapi.cn")

    apply_dmx_compat_env()

    assert os.environ["IMAGE_PROVIDER"] == "gemini_flash"
    assert os.environ["GOOGLE_API_KEY"] == "shared-key"
    assert os.environ["GEMINI_IMAGE_MODEL"] == DEFAULT_DMX_GEMINI_IMAGE_MODEL
    assert os.environ["GEMINI_IMAGE_BASE_URL"] == "https://www.dmxapi.cn"


def test_missing_dmx_image_model_defaults_to_flash_lite(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-key")
    monkeypatch.setenv("DMX_IMAGE_API_STYLE", "gemini")

    apply_dmx_compat_env()

    assert os.environ["DMX_IMAGE_MODEL"] == DEFAULT_DMX_GEMINI_IMAGE_MODEL
    assert os.environ["GEMINI_IMAGE_MODEL"] == DEFAULT_DMX_GEMINI_IMAGE_MODEL


def test_previous_teachnova_default_is_migrated_to_flash_lite(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-key")
    monkeypatch.setenv("DMX_IMAGE_API_STYLE", "gemini")
    monkeypatch.setenv("DMX_IMAGE_MODEL", "gemini-3.1-flash-image")

    apply_dmx_compat_env()

    assert os.environ["DMX_IMAGE_MODEL"] == DEFAULT_DMX_GEMINI_IMAGE_MODEL
    assert os.environ["GEMINI_IMAGE_MODEL"] == DEFAULT_DMX_GEMINI_IMAGE_MODEL


def test_custom_dmx_image_model_is_not_rewritten(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-key")
    monkeypatch.setenv("DMX_IMAGE_API_STYLE", "gemini")
    monkeypatch.setenv("DMX_IMAGE_MODEL", "custom-gemini-image-model")

    apply_dmx_compat_env()

    assert os.environ["DMX_IMAGE_MODEL"] == "custom-gemini-image-model"
    assert os.environ["GEMINI_IMAGE_MODEL"] == "custom-gemini-image-model"


def test_explicit_provider_specific_config_wins(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-key")
    monkeypatch.setenv("DMX_IMAGE_API_STYLE", "gemini")
    monkeypatch.setenv("DMX_IMAGE_MODEL", "gemini-3.1-flash-image")
    monkeypatch.setenv("DMX_GEMINI_BASE_URL", "https://www.dmxapi.cn")
    monkeypatch.setenv("IMAGE_PROVIDER", "pexels")
    monkeypatch.setenv("GOOGLE_API_KEY", "direct-google-key")
    monkeypatch.setenv("GEMINI_IMAGE_MODEL", "direct-model")
    monkeypatch.setenv("GEMINI_IMAGE_BASE_URL", "https://google.example")

    apply_dmx_compat_env()

    assert os.environ["IMAGE_PROVIDER"] == "pexels"
    assert os.environ["GOOGLE_API_KEY"] == "direct-google-key"
    assert os.environ["GEMINI_IMAGE_MODEL"] == "direct-model"
    assert os.environ["GEMINI_IMAGE_BASE_URL"] == "https://google.example"
    # Because a provider-specific model was explicitly supplied, even the stale
    # shared DMX value is left untouched for transparent diagnostics.
    assert os.environ["DMX_IMAGE_MODEL"] == "gemini-3.1-flash-image"


def test_no_dmx_key_is_noop(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DMX_IMAGE_API_STYLE", "gemini")
    monkeypatch.setenv("DMX_IMAGE_MODEL", "gemini-3.1-flash-lite-image")

    apply_dmx_compat_env()

    assert "GOOGLE_API_KEY" not in os.environ
    assert "IMAGE_PROVIDER" not in os.environ
