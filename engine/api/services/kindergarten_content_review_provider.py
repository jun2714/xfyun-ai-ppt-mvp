"""One cancellable HTTP request per explicit content-review stage.

This deliberately avoids the planner's schema/transport retry helpers: a review
must not silently multiply its model calls. Credentials remain in the API process.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from models.kindergarten_content_review import ModelCall, ModelReply, ProviderUsage


class ReviewProviderError(RuntimeError):
    """Only a safe diagnostic code may leave this adapter."""

    def __init__(self, code: str, *, submitted=None, model=None, usage=None):
        super().__init__(code)
        self.submitted = submitted
        self.model = model
        self.usage = usage


@dataclass(frozen=True)
class ReviewRuntime:
    base_url: str
    api_key: str = field(repr=False)
    model: str = ""
    max_tokens: int = 8192
    timeout_seconds: float = 90.0
    extra_body: dict = field(default_factory=dict)


def _positive_env(name: str, default: float, maximum: float) -> float:
    import math

    try:
        value = float(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ReviewProviderError("review_configuration_invalid") from exc
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ReviewProviderError("review_configuration_invalid")
    return value


def get_review_runtime() -> ReviewRuntime:
    """Resolve only server-owned configuration, never URLs from lesson data."""
    key = (os.getenv("KINDERGARTEN_REVIEW_API_KEY") or "").strip()
    base = (os.getenv("KINDERGARTEN_REVIEW_BASE_URL") or "").strip().rstrip("/")
    model = (os.getenv("KINDERGARTEN_REVIEW_MODEL") or "").strip()
    extra: dict = {}
    if key or base:
        if not (key and base and model):
            raise ReviewProviderError("review_configuration_incomplete")
        # Use the same provider-specific DeepSeek switches as the planner.
        from llmai.shared import OpenAIClientConfig
        from services.kindergarten_planner_runtime import _planner_request_extra_body

        config = OpenAIClientConfig(api_key=key, base_url=base)
        extra = _planner_request_extra_body(model, config) or {}
    else:
        from llmai.shared import OpenAIClientConfig
        from services.kindergarten_planner_runtime import (
            _planner_request_extra_body,
            get_kindergarten_planner_runtime,
        )

        runtime = get_kindergarten_planner_runtime()
        if not isinstance(runtime.config, OpenAIClientConfig):
            raise ReviewProviderError("review_requires_openai_compatible_configuration")
        key = str(runtime.config.api_key or "")
        base = str(runtime.config.base_url or "https://api.openai.com/v1").rstrip("/")
        model = model or runtime.model
        extra = _planner_request_extra_body(model, runtime.config) or {}
    parsed = urlsplit(base)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ReviewProviderError("review_configuration_invalid")
    if not key or not model:
        raise ReviewProviderError("review_configuration_incomplete")
    token_limit = _positive_env("KINDERGARTEN_REVIEW_MAX_TOKENS", 8192, 32768)
    if not token_limit.is_integer():
        raise ReviewProviderError("review_configuration_invalid", submitted=False)
    return ReviewRuntime(
        base_url=base,
        api_key=key,
        model=model,
        max_tokens=int(token_limit),
        timeout_seconds=_positive_env("KINDERGARTEN_REVIEW_CALL_TIMEOUT_SECONDS", 90, 300),
        extra_body=extra,
    )


def _usage_value(usage: dict, key: str) -> int | None:
    value = usage.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _read_usage(data: dict) -> ProviderUsage | None:
    raw = data.get("usage")
    if not isinstance(raw, dict):
        return None
    details = raw.get("prompt_tokens_details")
    return ProviderUsage(
        input_tokens=_usage_value(raw, "prompt_tokens"),
        output_tokens=_usage_value(raw, "completion_tokens"),
        total_tokens=_usage_value(raw, "total_tokens"),
        cached_input_tokens=_usage_value(details, "cached_tokens") if isinstance(details, dict) else None,
    )


class OpenAICompatibleReviewCaller:
    def __init__(self, runtime: ReviewRuntime | None = None, *, transport=None):
        self.runtime = runtime
        self.transport = transport

    async def __call__(self, call: ModelCall) -> ModelReply:
        from services.model_request_queue import model_request_slot

        try:
            runtime = self.runtime or get_review_runtime()
        except ReviewProviderError as exc:
            exc.submitted = False
            raise
        except Exception as exc:
            raise ReviewProviderError("review_configuration_unavailable", submitted=False) from exc
        payload = json.dumps(call.payload, ensure_ascii=False)
        if len(payload) > 160_000:
            raise ReviewProviderError("review_input_too_large", submitted=False)
        system = call.system_prompt + "\nReturn one JSON object matching this schema:\n" + json.dumps(
            call.response_schema, ensure_ascii=False,
        )
        body = {
            "model": runtime.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": payload}],
            "response_format": {"type": "json_object"},
            "max_tokens": runtime.max_tokens,
            "stream": False,
            **runtime.extra_body,
        }
        # httpx has no application-level retry by default. Redirects are disabled
        # so a provider cannot forward this authenticated POST to another origin.
        model, usage = runtime.model, None
        async with model_request_slot("outline"):
            try:
                async with httpx.AsyncClient(
                    timeout=runtime.timeout_seconds,
                    follow_redirects=False,
                    transport=self.transport,
                ) as client:
                    response = await client.post(
                        runtime.base_url + "/chat/completions",
                        headers={"Authorization": "Bearer " + runtime.api_key},
                        json=body,
                    )
                if response.status_code != 200:
                    raise ReviewProviderError(f"review_provider_http_{response.status_code}",
                                              submitted=True, model=model)
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("Provider response must be an object")
                model = str(data.get("model") or runtime.model)
                usage = _read_usage(data)
                choice = data["choices"][0]
                if choice.get("finish_reason") not in {None, "stop"}:
                    raise ReviewProviderError("review_provider_incomplete_output",
                                              submitted=True, model=model, usage=usage)
                text = choice["message"]["content"]
                result = json.loads(text)
                if not isinstance(result, dict):
                    raise ValueError("Model result must be an object")
            except httpx.TimeoutException as exc:
                raise ReviewProviderError("review_provider_timeout") from exc
            except httpx.HTTPError as exc:
                raise ReviewProviderError("review_provider_connection_failed") from exc
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                raise ReviewProviderError("review_provider_invalid_json", submitted=True,
                                          model=model, usage=usage) from exc
        return ModelReply(payload=result, model=model,
                          usage=usage, submitted=True)
