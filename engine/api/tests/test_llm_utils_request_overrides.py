from llmai.shared import SystemMessage

from utils import llm_utils


def test_explicit_request_body_can_bypass_global_provider_settings(monkeypatch):
    monkeypatch.setattr(
        llm_utils,
        "get_extra_body",
        lambda **kwargs: {"thinking": {"type": "enabled"}},
    )

    kwargs = llm_utils.get_generate_kwargs(
        model="kimi-k2.6",
        messages=[SystemMessage(content="test")],
        max_tokens=8192,
        extra_body={"thinking": {"type": "disabled"}},
        use_provider_extra_body=False,
    )

    assert kwargs["max_tokens"] == 8192
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_explicit_request_body_merges_when_provider_settings_are_enabled(monkeypatch):
    monkeypatch.setattr(
        llm_utils,
        "get_extra_body",
        lambda **kwargs: {"provider_option": True},
    )

    kwargs = llm_utils.get_generate_kwargs(
        model="another-model",
        messages=[SystemMessage(content="test")],
        extra_body={"request_option": "fast"},
    )

    assert kwargs["extra_body"] == {
        "provider_option": True,
        "request_option": "fast",
    }
