import pytest

from services.asset_semantic_quality_service import (
    VisionAssetSemanticQualityService,
    build_default_asset_semantic_quality_service,
)


_ENV = (
    "ASSET_SEMANTIC_QA_PROVIDER",
    "ASSET_SEMANTIC_QA_MODEL",
    "ASSET_SEMANTIC_QA_CONFIDENCE",
    "DMX_API_KEY",
    "DMX_API_BASE_URL",
    "KINDERGARTEN_PLANNER_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "GOOGLE_API_KEY",
    "GOOGLE_MODEL",
    "LLM",
)


def _clear(monkeypatch):
    for key in _ENV:
        monkeypatch.delenv(key, raising=False)


def test_auto_semantic_qa_uses_shared_dmx_key(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "kimi-k3")

    service = build_default_asset_semantic_quality_service()

    assert isinstance(service, VisionAssetSemanticQualityService)
    assert service.provider == "dmx"
    assert service.model == "kimi-k3"
    assert service.confidence_threshold == 0.70


def test_explicit_direct_provider_still_wins(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ASSET_SEMANTIC_QA_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "direct-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "vision-model")
    monkeypatch.setenv("DMX_API_KEY", "shared-key")

    service = build_default_asset_semantic_quality_service()

    assert isinstance(service, VisionAssetSemanticQualityService)
    assert service.provider == "openai"
    assert service.model == "vision-model"


def test_explicit_dmx_requires_shared_key(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ASSET_SEMANTIC_QA_PROVIDER", "dmx")

    with pytest.raises(ValueError, match="DMX_API_KEY"):
        build_default_asset_semantic_quality_service()


def test_semantic_qa_can_be_disabled(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ASSET_SEMANTIC_QA_PROVIDER", "off")
    monkeypatch.setenv("DMX_API_KEY", "shared-key")

    assert build_default_asset_semantic_quality_service() is None
