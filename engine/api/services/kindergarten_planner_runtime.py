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
    """Resolve an optional dedicated model for kindergarten lesson planning.

    The rest of the PPT pipeline can keep using the globally configured model while
    lesson planning uses a stronger OpenAI-compatible endpoint (for example Kimi K3).
    This keeps expensive reasoning focused on lesson logic instead of paying the same
    cost again for every small slide-copy operation.

    Environment variables:
      KINDERGARTEN_PLANNER_BASE_URL
      KINDERGARTEN_PLANNER_API_KEY
      KINDERGARTEN_PLANNER_MODEL

    When none of them are configured, the existing global LLM configuration remains
    the fallback so current deployments continue working unchanged.
    """
    base_url = (os.getenv("KINDERGARTEN_PLANNER_BASE_URL") or "").strip().rstrip("/")
    api_key = (os.getenv("KINDERGARTEN_PLANNER_API_KEY") or "").strip()
    model = (os.getenv("KINDERGARTEN_PLANNER_MODEL") or "").strip()

    configured = bool(base_url or api_key or model)
    if not configured:
        return KindergartenPlannerRuntime(
            config=get_llm_config(),
            model=get_model(),
            source="global",
        )

    missing: list[str] = []
    if not base_url:
        missing.append("KINDERGARTEN_PLANNER_BASE_URL")
    if not api_key:
        missing.append("KINDERGARTEN_PLANNER_API_KEY")
    if not model:
        missing.append("KINDERGARTEN_PLANNER_MODEL")
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                "Dedicated kindergarten planner configuration is incomplete: "
                + ", ".join(missing)
            ),
        )

    return KindergartenPlannerRuntime(
        config=OpenAIClientConfig(
            base_url=base_url,
            api_key=api_key,
        ),
        model=model,
        source="dedicated-openai-compatible",
    )
