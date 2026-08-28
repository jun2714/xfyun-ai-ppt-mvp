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

    TeachNova routes Kimi K3 through DMXAPI by default, reusing ``DMX_API_KEY``.
    A direct OpenAI-compatible planner endpoint is only selected when a dedicated
    ``KINDERGARTEN_PLANNER_API_KEY`` is supplied.  This prevents a stale Moonshot
    URL from being accidentally combined with the shared DMX key.
    """
    planner_base_url = (
        os.getenv("KINDERGARTEN_PLANNER_BASE_URL") or ""
    ).strip().rstrip("/")
    planner_api_key = (os.getenv("KINDERGARTEN_PLANNER_API_KEY") or "").strip()
    planner_model = (os.getenv("KINDERGARTEN_PLANNER_MODEL") or "").strip()

    dmx_base_url = (
        os.getenv("DMX_API_BASE_URL") or "https://www.dmxapi.cn/v1"
    ).strip().rstrip("/")
    dmx_api_key = (os.getenv("DMX_API_KEY") or "").strip()

    if planner_api_key:
        if not planner_base_url:
            raise HTTPException(
                status_code=400,
                detail=(
                    "KINDERGARTEN_PLANNER_API_KEY is set, so "
                    "KINDERGARTEN_PLANNER_BASE_URL must also be set."
                ),
            )
        return KindergartenPlannerRuntime(
            config=OpenAIClientConfig(
                base_url=planner_base_url,
                api_key=planner_api_key,
            ),
            model=planner_model or "kimi-k3",
            source="dedicated-openai-compatible",
        )

    if dmx_api_key:
        return KindergartenPlannerRuntime(
            config=OpenAIClientConfig(
                base_url=dmx_base_url,
                api_key=dmx_api_key,
            ),
            model=planner_model or "kimi-k3",
            source="shared-dmx-openai-compatible",
        )

    if not planner_model and not planner_base_url:
        return KindergartenPlannerRuntime(
            config=get_llm_config(),
            model=get_model(),
            source="global",
        )

    raise HTTPException(
        status_code=400,
        detail=(
            "Kindergarten planner needs DMX_API_KEY, or a complete dedicated "
            "KINDERGARTEN_PLANNER_BASE_URL + KINDERGARTEN_PLANNER_API_KEY pair."
        ),
    )
