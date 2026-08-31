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
    profile: str
    request_extra_body: dict | None
    max_tokens: int
    timeout_seconds: float
    total_timeout_seconds: float
    stream: bool


FAST_PROFILE = "fast"
PREMIUM_PROFILE = "premium"
FAST_MODEL = "kimi-k2.7-code-highspeed"
FAST_MAX_TOKENS = 16_000
FAST_CALL_TIMEOUT_SECONDS = 55.0
FAST_TOTAL_TIMEOUT_SECONDS = 60.0


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
    profile: str,
) -> KindergartenPlannerRuntime:
    if profile == FAST_PROFILE:
        if "kimi-k3" in model.strip().lower():
            raise HTTPException(
                status_code=400,
                detail=(
                    "KINDERGARTEN_PLANNER_FAST_MODEL cannot use kimi-k3. "
                    "Use kimi-k2.7-code-highspeed or switch the planner profile "
                    "to premium explicitly."
                ),
            )
        return KindergartenPlannerRuntime(
            config=config,
            model=model,
            source=source,
            profile=profile,
            request_extra_body=_planner_request_extra_body(model),
            max_tokens=FAST_MAX_TOKENS,
            timeout_seconds=FAST_CALL_TIMEOUT_SECONDS,
            total_timeout_seconds=FAST_TOTAL_TIMEOUT_SECONDS,
            stream=True,
        )

    timeout_seconds = _positive_number_env(
        "KINDERGARTEN_PLANNER_TIMEOUT_SECONDS",
        "240",
        float,
    )
    return KindergartenPlannerRuntime(
        config=config,
        model=model,
        source=source,
        profile=profile,
        request_extra_body=_planner_request_extra_body(model),
        max_tokens=_positive_number_env(
            "KINDERGARTEN_PLANNER_MAX_TOKENS",
            "32768",
            int,
        ),
        timeout_seconds=timeout_seconds,
        total_timeout_seconds=timeout_seconds * 2,
        stream=True,
    )


def _planner_profile() -> str:
    profile = (
        os.getenv("KINDERGARTEN_PLANNER_PROFILE") or FAST_PROFILE
    ).strip().lower()
    if profile not in {FAST_PROFILE, PREMIUM_PROFILE}:
        raise HTTPException(
            status_code=400,
            detail="KINDERGARTEN_PLANNER_PROFILE must be fast or premium.",
        )
    return profile


def _planner_model(profile: str, legacy_model: str) -> str:
    if profile == FAST_PROFILE:
        return (
            os.getenv("KINDERGARTEN_PLANNER_FAST_MODEL") or FAST_MODEL
        ).strip()
    return legacy_model or "kimi-k3"


def get_kindergarten_planner_runtime() -> KindergartenPlannerRuntime:
    """Resolve the model runtime used by kindergarten lesson planning.

    Standard generation always uses a bounded fast profile. The legacy
    ``KINDERGARTEN_PLANNER_MODEL`` value is read only when premium is selected
    explicitly, so a stale production ``kimi-k3`` setting cannot silently turn a
    normal outline request into a multi-minute reasoning call.
    """
    planner_base_url = (
        os.getenv("KINDERGARTEN_PLANNER_BASE_URL") or ""
    ).strip().rstrip("/")
    planner_api_key = (os.getenv("KINDERGARTEN_PLANNER_API_KEY") or "").strip()
    legacy_model = (os.getenv("KINDERGARTEN_PLANNER_MODEL") or "").strip()
    profile = _planner_profile()
    planner_model = _planner_model(profile, legacy_model)

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
            model=planner_model,
            source="dedicated-openai-compatible",
            profile=profile,
        )

    if dmx_api_key:
        return _build_runtime(
            config=OpenAIClientConfig(
                base_url=dmx_base_url,
                api_key=dmx_api_key,
            ),
            model=planner_model,
            source="shared-dmx-openai-compatible",
            profile=profile,
        )

    if not legacy_model and not planner_base_url:
        return _build_runtime(
            config=get_llm_config(),
            model=get_model(),
            source="global",
            profile=PREMIUM_PROFILE,
        )

    raise HTTPException(
        status_code=400,
        detail=(
            "Kindergarten planner needs DMX_API_KEY, or a complete dedicated "
            "KINDERGARTEN_PLANNER_BASE_URL + KINDERGARTEN_PLANNER_API_KEY pair."
        ),
    )
