import pytest
from fastapi import HTTPException

import services.kindergarten_planner_runtime as runtime_module


_PLANNER_ENV = (
    "KINDERGARTEN_PLANNER_BASE_URL",
    "KINDERGARTEN_PLANNER_API_KEY",
    "KINDERGARTEN_PLANNER_MODEL",
    "DMX_API_BASE_URL",
    "DMX_API_KEY",
)


def _clear_planner_env(monkeypatch):
    for key in _PLANNER_ENV:
        monkeypatch.delenv(key, raising=False)


def test_planner_runtime_falls_back_to_global_config(monkeypatch):
    _clear_planner_env(monkeypatch)
    sentinel_config = object()
    monkeypatch.setattr(runtime_module, "get_llm_config", lambda: sentinel_config)
    monkeypatch.setattr(runtime_module, "get_model", lambda: "global-model")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.config is sentinel_config
    assert runtime.model == "global-model"
    assert runtime.source == "global"


def test_planner_runtime_reuses_shared_dmx_key(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_BASE_URL", "https://www.dmxapi.cn/v1")
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "kimi-k3")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.model == "kimi-k3"
    assert runtime.source == "shared-dmx-openai-compatible"
    assert runtime.config.__class__.__name__ == "OpenAIClientConfig"
    assert runtime.config.api_key == "shared-dmx-key"
    assert str(runtime.config.base_url).rstrip("/") == "https://www.dmxapi.cn/v1"


def test_planner_runtime_uses_dedicated_openai_compatible_config(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_API_KEY", "dedicated-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "kimi-k3")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.model == "kimi-k3"
    assert runtime.source == "dedicated-openai-compatible"
    assert runtime.config.__class__.__name__ == "OpenAIClientConfig"
    assert runtime.config.api_key == "dedicated-key"
    assert str(runtime.config.base_url).rstrip("/") == "https://example.test/v1"


def test_planner_runtime_rejects_model_without_any_key(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "kimi-k3")

    with pytest.raises(HTTPException) as exc_info:
        runtime_module.get_kindergarten_planner_runtime()

    assert exc_info.value.status_code == 400
    assert "DMX_API_KEY or KINDERGARTEN_PLANNER_API_KEY" in str(
        exc_info.value.detail
    )
