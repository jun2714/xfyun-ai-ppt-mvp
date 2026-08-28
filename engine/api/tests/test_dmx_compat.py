import os

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
)


def _clear(monkeypatch):
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)


def test_dmx_gemini_config_reuses_shared_key(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-key")
    monkeypatch.setenv("DMX_IMAGE_API_STYLE", "gemini")
    monkeypatch.setenv("DMX_IMAGE_MODEL", "gemini-3.1-flash-image")
    monkeypatch.setenv("DMX_GEMINI_BASE_URL", "https://www.dmxapi.cn")

    apply_dmx_compat_env()

    assert os.environ["IMAGE_PROVIDER"] == "gemini_flash"
    assert os.environ["GOOGLE_API_KEY"] == "shared-key"
    assert os.environ["GEMINI_IMAGE_MODEL"] == "gemini-3.1-flash-image"
    assert os.environ["GEMINI_IMAGE_BASE_URL"] == "https://www.dmxapi.cn"


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


def test_no_dmx_key_is_noop(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DMX_IMAGE_API_STYLE", "gemini")
    monkeypatch.setenv("DMX_IMAGE_MODEL", "gemini-3.1-flash-image")

    apply_dmx_compat_env()

    assert "GOOGLE_API_KEY" not in os.environ
    assert "IMAGE_PROVIDER" not in os.environ
