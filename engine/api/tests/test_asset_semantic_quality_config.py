import pytest

from services.asset_semantic_quality_service import (
    VisionAssetSemanticQualityService,
    build_default_asset_semantic_quality_service,
)


_ENV_KEYS = (
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


def _clear_env(monkeypatch):
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_auto_semantic_qa_reuses_dmx_key(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")
    monkeypatch.setenv("KINDERGARTEN_PLANNER_MODEL", "kimi-k3")

    service = build_default_asset_semantic_quality_service()

    assert isinstance(service, VisionAssetSemanticQualityService)
    assert service.provider == "dmx"
    assert service.model == "kimi-k3"
    assert service.confidence_threshold == 0.70


def test_explicit_dmx_semantic_qa_uses_requested_model(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ASSET_SEMANTIC_QA_PROVIDER", "dmx")
    monkeypatch.setenv("ASSET_SEMANTIC_QA_MODEL", "vision-model")
    monkeypatch.setenv("ASSET_SEMANTIC_QA_CONFIDENCE", "0.82")
    monkeypatch.setenv("DMX_API_KEY", "shared-dmx-key")

    service = build_default_asset_semantic_quality_service()

    assert isinstance(service, VisionAssetSemanticQualityService)
    assert service.provider == "dmx"
    assert service.model == "vision-model"
    assert service.confidence_threshold == 0.82


def test_explicit_dmx_semantic_qa_requires_shared_key(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ASSET_SEMANTIC_QA_PROVIDER", "dmx")

    with pytest.raises(ValueError, match="DMX_API_KEY"):
        build_default_asset_semantic_quality_service()
