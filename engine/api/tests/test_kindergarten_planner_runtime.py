import pytest
from fastapi import HTTPException

import services.kindergarten_planner_runtime as runtime_module


_PLANNER_ENV = (
    "KINDERGARTEN_PLANNER_BASE_URL",
    "KINDERGARTEN_PLANNER_API_KEY",
    "KINDERGARTEN_PLANNER_MODEL",
    "KINDERGARTEN_PLANNER_PROFILE",
    "KINDERGARTEN_PLANNER_FAST_MODEL",
    "KINDERGARTEN_PLANNER_FAST_MAX_TOKENS",
    "KINDERGARTEN_PLANNER_FAST_TIMEOUT_SECONDS",
    "KINDERGARTEN_PLANNER_FAST_TOTAL_TIMEOUT_SECONDS",
    "KINDERGARTEN_PLANNER_DEEPSEEK_THINKING",
    "KINDERGARTEN_PLANNER_DEEPSEEK_REASONING_EFFORT",
    "DMX_API_BASE_URL",
    "DMX_API_KEY",
    "KINDERGARTEN_PLANNER_MAX_TOKENS",
    "KINDERGARTEN_PLANNER_TIMEOUT_SECONDS",
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
    assert runtime.profile == "premium"
    assert runtime.request_extra_body is None
    assert runtime.max_tokens == 32768
    assert runtime.timeout_seconds == 240
    assert runtime.total_timeout_seconds == 480
    assert runtime.stream is True


def test_fast_profile_ignores_stale_kimi_model(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_BASE_URL", "https://www.dmxapi.cn/v1")
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "kimi-k3")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.model == "deepseek-v4-pro-0813"
    assert runtime.source == "shared-dmx-openai-compatible"
    assert runtime.profile == "fast"
    assert runtime.request_extra_body == {"thinking": {"type": "disabled"}}
    assert runtime.max_tokens == 16000
    assert runtime.timeout_seconds == 180
    assert runtime.total_timeout_seconds == 420
    assert runtime.stream is True
    assert runtime.config.__class__.__name__ == "OpenAIClientConfig"
    assert runtime.config.api_key == "shared-dmx-key"
    assert str(runtime.config.base_url).rstrip("/") == "https://www.dmxapi.cn/v1"


def test_planner_runtime_defaults_to_deepseek_with_only_dmx_key(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.model == "deepseek-v4-pro-0813"
    assert runtime.source == "shared-dmx-openai-compatible"
    assert runtime.profile == "fast"
    assert runtime.request_extra_body == {"thinking": {"type": "disabled"}}
    assert runtime.config.api_key == "shared-dmx-key"
    assert str(runtime.config.base_url).rstrip("/") == "https://www.dmxapi.cn/v1"


def test_deepseek_thinking_can_be_explicitly_enabled(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_DEEPSEEK_THINKING", "enabled")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_DEEPSEEK_REASONING_EFFORT", "max")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.request_extra_body == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "max",
    }


def test_invalid_deepseek_thinking_mode_is_rejected(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_DEEPSEEK_THINKING", "auto")

    with pytest.raises(HTTPException) as exc_info:
        runtime_module.get_kindergarten_planner_runtime()

    assert exc_info.value.status_code == 400
    assert "DEEPSEEK_THINKING" in str(exc_info.value.detail)


def test_stale_moonshot_url_and_kimi_model_are_ignored_with_shared_dmx(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_BASE_URL", "https://www.dmxapi.cn/v1")
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_BASE_URL", "https://api.moonshot.cn/v1")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "kimi-k3")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.source == "shared-dmx-openai-compatible"
    assert runtime.model == "deepseek-v4-pro-0813"
    assert runtime.request_extra_body == {"thinking": {"type": "disabled"}}
    assert runtime.config.api_key == "shared-dmx-key"
    assert str(runtime.config.base_url).rstrip("/") == "https://www.dmxapi.cn/v1"


def test_premium_profile_replaces_stale_kimi_with_deepseek(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_PROFILE", "premium")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "kimi-k3")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.model == "deepseek-v4-pro-0813"
    assert runtime.profile == "premium"
    assert runtime.request_extra_body == {"thinking": {"type": "disabled"}}


def test_planner_runtime_uses_dedicated_openai_compatible_config(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_API_KEY", "dedicated-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_PROFILE", "premium")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "deepseek-v4-pro-0813")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.model == "deepseek-v4-pro-0813"
    assert runtime.source == "dedicated-openai-compatible"
    assert runtime.profile == "premium"
    assert runtime.request_extra_body == {"thinking": {"type": "disabled"}}
    assert runtime.config.__class__.__name__ == "OpenAIClientConfig"
    assert runtime.config.api_key == "dedicated-key"
    assert str(runtime.config.base_url).rstrip("/") == "https://example.test/v1"


def test_dedicated_key_requires_dedicated_base_url(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("KINDERGARTEN_PLANNER_API_KEY", "dedicated-key")

    with pytest.raises(HTTPException) as exc_info:
        runtime_module.get_kindergarten_planner_runtime()

    assert exc_info.value.status_code == 400
    assert "KINDERGARTEN_PLANNER_BASE_URL" in str(exc_info.value.detail)


def test_planner_runtime_rejects_model_without_any_key(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "deepseek-v4-pro-0813")

    with pytest.raises(HTTPException) as exc_info:
        runtime_module.get_kindergarten_planner_runtime()

    assert exc_info.value.status_code == 400
    assert "DMX_API_KEY" in str(exc_info.value.detail)


def test_planner_model_can_be_switched_later_without_code_change(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "future-outline-model")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.model == "future-outline-model"
    assert runtime.profile == "fast"
    assert runtime.request_extra_body is None


def test_fast_specific_model_override_wins(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "future-outline-model")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_FAST_MODEL", "fast-outline-model")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.model == "fast-outline-model"
    assert runtime.request_extra_body is None


def test_stale_kimi_fast_override_is_replaced_by_deepseek(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_FAST_MODEL", "kimi-k2.7-code-highspeed")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.model == "deepseek-v4-pro-0813"
    assert runtime.request_extra_body == {"thinking": {"type": "disabled"}}


def test_planner_runtime_reads_its_own_limits(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_PROFILE", "premium")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MAX_TOKENS", "4096")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_TIMEOUT_SECONDS", "45.5")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.max_tokens == 4096
    assert runtime.timeout_seconds == 45.5


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("KINDERGARTEN_PLANNER_MAX_TOKENS", "0"),
        ("KINDERGARTEN_PLANNER_TIMEOUT_SECONDS", "not-a-number"),
    ],
)
def test_planner_runtime_rejects_invalid_premium_settings(
    monkeypatch,
    name,
    value,
):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_PROFILE", "premium")
    monkeypatch.setenv(name, value)

    with pytest.raises(HTTPException) as exc_info:
        runtime_module.get_kindergarten_planner_runtime()

    assert exc_info.value.status_code == 400
    assert name in str(exc_info.value.detail)


def test_fast_profile_uses_deepseek_bounded_limits(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_TIMEOUT_SECONDS", "999")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MAX_TOKENS", "999999")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.model == "deepseek-v4-pro-0813"
    assert runtime.max_tokens == 16000
    assert runtime.timeout_seconds == 180
    assert runtime.total_timeout_seconds == 420


def test_fast_profile_limits_can_be_overridden(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_FAST_MAX_TOKENS", "12000")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_FAST_TIMEOUT_SECONDS", "210")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_FAST_TOTAL_TIMEOUT_SECONDS", "450")

    runtime = runtime_module.get_kindergarten_planner_runtime()

    assert runtime.max_tokens == 12000
    assert runtime.timeout_seconds == 210
    assert runtime.total_timeout_seconds == 450


def test_fast_profile_rejects_total_timeout_shorter_than_call(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_FAST_TIMEOUT_SECONDS", "180")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_FAST_TOTAL_TIMEOUT_SECONDS", "120")

    with pytest.raises(HTTPException) as exc_info:
        runtime_module.get_kindergarten_planner_runtime()

    assert exc_info.value.status_code == 400
    assert "FAST_TOTAL_TIMEOUT_SECONDS" in str(exc_info.value.detail)


def test_planner_runtime_rejects_unknown_profile(monkeypatch):
    _clear_planner_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_PROFILE", "balanced")

    with pytest.raises(HTTPException) as exc_info:
        runtime_module.get_kindergarten_planner_runtime()

    assert exc_info.value.status_code == 400
    assert "must be fast or premium" in str(exc_info.value.detail)
