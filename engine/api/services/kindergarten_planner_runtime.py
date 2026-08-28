from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import HTTPException
from llmai.shared import ClientConfig, OpenAIClientConfig

from utils.llm_config import get_llm_config
from utils.llm_provider import get_model


@dataclass(frozen=True)
class KindergartenPlannerRuntime:
    config: ClientConfig
    model: str
    source: str


def get_kindergarten_planner_runtime() -> KindergartenPlannerRuntime:
    """Resolve the model runtime used by kindergarten lesson planning.

    Production normally routes Kimi K3 through DMXAPI, so the planner can reuse the
    same ``DMX_API_KEY`` and ``DMX_API_BASE_URL`` as the rest of the PPT pipeline.
    A dedicated OpenAI-compatible endpoint/key can still be supplied for deployments
    that want to call Moonshot (or another gateway) directly.

    Environment variables:
      KINDERGARTEN_PLANNER_MODEL
      KINDERGARTEN_PLANNER_BASE_URL   (optional override)
      KINDERGARTEN_PLANNER_API_KEY    (optional override)
      DMX_API_BASE_URL                (shared fallback)
      DMX_API_KEY                     (shared fallback)

    If no planner-specific settings are configured, the existing global LLM runtime
    remains the fallback so older deployments keep working unchanged.
    """
    planner_base_url = (
        os.getenv("KINDERGARTEN_PLANNER_BASE_URL") or ""
    ).strip().rstrip("/")
    planner_api_key = (os.getenv("KINDERGARTEN_PLANNER_API_KEY") or "").strip()
    planner_model = (os.getenv("KINDERGARTEN_PLANNER_MODEL") or "").strip()

    configured = bool(planner_base_url or planner_api_key or planner_model)
    if not configured:
        return KindergartenPlannerRuntime(
            config=get_llm_config(),
            model=get_model(),
            source="global",
        )

    dmx_base_url = (
        os.getenv("DMX_API_BASE_URL") or "https://www.dmxapi.cn/v1"
    ).strip().rstrip("/")
    dmx_api_key = (os.getenv("DMX_API_KEY") or "").strip()

    base_url = planner_base_url or dmx_base_url
    api_key = planner_api_key or dmx_api_key

    missing: list[str] = []
    if not planner_model:
        missing.append("KINDERGARTEN_PLANNER_MODEL")
    if not api_key:
        missing.append(
            "DMX_API_KEY or KINDERGARTEN_PLANNER_API_KEY"
        )
    if not base_url:
        missing.append(
            "DMX_API_BASE_URL or KINDERGARTEN_PLANNER_BASE_URL"
        )
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                "Kindergarten planner configuration is incomplete: "
                + ", ".join(missing)
            ),
        )

    uses_dedicated_endpoint = bool(planner_base_url or planner_api_key)
    return KindergartenPlannerRuntime(
        config=OpenAIClientConfig(
            base_url=base_url,
            api_key=api_key,
        ),
        model=planner_model,
        source=(
            "dedicated-openai-compatible"
            if uses_dedicated_endpoint
            else "shared-dmx-openai-compatible"
        ),
    )
