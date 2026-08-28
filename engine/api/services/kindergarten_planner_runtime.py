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

    The default production path routes Kimi K3 through DMXAPI.  K3 therefore reuses
    the same ``DMX_API_KEY`` and ``DMX_API_BASE_URL`` as the other DMX-routed models.

    A *dedicated* OpenAI-compatible endpoint is only selected when a dedicated
    ``KINDERGARTEN_PLANNER_API_KEY`` is present.  This detail is important: a stale
    or copied ``KINDERGARTEN_PLANNER_BASE_URL=https://api.moonshot.cn/v1`` must never
    be combined with a DMX key, because that produces an upstream authentication
    failure.  When the planner key is absent, the DMX key is always paired with the
    DMX endpoint.
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

    # Direct provider override: base URL and key are a pair.  Never mix the direct
    # Moonshot URL with the shared DMX key.
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

    # Preferred production path: one DMX account/key for K3 and the rest of the
    # configured DMX models.  Deliberately ignore planner_base_url here; it may be a
    # legacy Moonshot value from an older .env example.
    if dmx_api_key:
        return KindergartenPlannerRuntime(
            config=OpenAIClientConfig(
                base_url=dmx_base_url,
                api_key=dmx_api_key,
            ),
            model=planner_model or "kimi-k3",
            source="shared-dmx-openai-compatible",
        )

    # If there is no dedicated planner configuration at all, preserve legacy
    # deployments by using the existing global LLM runtime.
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
