import pytest
from fastapi import HTTPException

import services.kindergarten_planner_runtime as runtime_module


_PLANNER_ENV = (
    "KINDERGARTEN_PLANNER_BASE_URL",
    "KINDERGARTEN_PLANNER_API_KEY",
    "KINDERGARTEN_PLANNER_MODEL",
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


def test_planner_runtime_uses_dedicated_openai_compatible_config(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("KINDERGARTEN_PLANNER_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_API_KEY", "test-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "kimi-k3")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.model == "kimi-k3"
    assert runtime.source == "dedicated-openai-compatible"
    assert runtime.config.__class__.__name__ == "OpenAIClientConfig"


def test_planner_runtime_rejects_partial_dedicated_config(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "kimi-k3")

    with pytest.raises(HTTPException) as exc_info:
        runtime_module.get_kindergarten_planner_runtime()

    assert exc_info.value.status_code == 400
    assert "KINDERGARTEN_PLANNER_BASE_URL" in str(exc_info.value.detail)
    assert "KINDERGARTEN_PLANNER_API_KEY" in str(exc_info.value.detail)
