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
    request_extra_body: dict | None
    max_tokens: int
    timeout_seconds: float


def _positive_number_env(name: str, default: str, cast):
    raw_value = (os.getenv(name) or default).strip()
    try:
        value = cast(raw_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"{name} must be a positive number.",
        ) from exc
    if value <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"{name} must be a positive number.",
        )
    return value


def _planner_request_extra_body(model: str) -> dict | None:
    normalized_model = model.strip().lower()
    if "kimi-k3" in normalized_model:
        effort = (
            os.getenv("KINDERGARTEN_PLANNER_REASONING_EFFORT") or "low"
        ).strip().lower()
        if effort not in {"low", "high", "max"}:
            raise HTTPException(
                status_code=400,
                detail=(
                    "KINDERGARTEN_PLANNER_REASONING_EFFORT must be one of: "
                    "low, high, max."
                ),
            )
        return {"reasoning_effort": effort}
    if "kimi-k2.6" in normalized_model or "kimi-k2.5" in normalized_model:
        return {"thinking": {"type": "disabled"}}
    return None


def _build_runtime(
    *,
    config: ClientConfig,
    model: str,
    source: str,
) -> KindergartenPlannerRuntime:
    return KindergartenPlannerRuntime(
        config=config,
        model=model,
        source=source,
        request_extra_body=_planner_request_extra_body(model),
        max_tokens=_positive_number_env(
            "KINDERGARTEN_PLANNER_MAX_TOKENS",
            "8192",
            int,
        ),
        timeout_seconds=_positive_number_env(
            "KINDERGARTEN_PLANNER_TIMEOUT_SECONDS",
            "55",
            float,
        ),
    )


def get_kindergarten_planner_runtime() -> KindergartenPlannerRuntime:
    """Resolve the model runtime used by kindergarten lesson planning.

    TeachNova routes the fast Kimi K2.6 planner through DMXAPI by default, reusing
    ``DMX_API_KEY``. A direct OpenAI-compatible planner endpoint is only selected
    when a dedicated ``KINDERGARTEN_PLANNER_API_KEY`` is supplied. This prevents a
    stale Moonshot URL from being accidentally combined with the shared DMX key.
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
        return _build_runtime(
            config=OpenAIClientConfig(
                base_url=planner_base_url,
                api_key=planner_api_key,
            ),
            model=planner_model or "kimi-k2.6",
            source="dedicated-openai-compatible",
        )

    if dmx_api_key:
        return _build_runtime(
            config=OpenAIClientConfig(
                base_url=dmx_base_url,
                api_key=dmx_api_key,
            ),
            model=planner_model or "kimi-k2.6",
            source="shared-dmx-openai-compatible",
        )

    if not planner_model and not planner_base_url:
        return _build_runtime(
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
