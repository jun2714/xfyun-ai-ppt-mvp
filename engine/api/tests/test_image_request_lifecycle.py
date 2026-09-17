import asyncio

import pytest

from models.image_prompt import ImagePrompt
from services import image_generation_service as images
from utils.get_env import get_image_generation_timeout_seconds
from utils.image_generation_error import normalize_image_generation_error


def test_image_timeout_default_and_explicit_override(monkeypatch):
    monkeypatch.delenv("IMAGE_GENERATION_TIMEOUT_SECONDS", raising=False)
    assert get_image_generation_timeout_seconds() == 150
    monkeypatch.setenv("IMAGE_GENERATION_TIMEOUT_SECONDS", "75")
    assert get_image_generation_timeout_seconds() == 75
    monkeypatch.setenv("IMAGE_GENERATION_TIMEOUT_SECONDS", "invalid")
    assert get_image_generation_timeout_seconds() == 150


def test_dmx_gemini_rate_limit_and_transport_timeout_have_distinct_codes():
    from google.genai.errors import ClientError
    import httpx
    limited = normalize_image_generation_error(ClientError(429, {'error': {'message': 'private upstream details'}}))
    timed_out = normalize_image_generation_error(httpx.ReadTimeout('private upstream URL'))
    assert limited.status_code == 429 and limited.provider_code == 'image_provider_rate_limited'
    assert timed_out.status_code == 504 and timed_out.provider_code == 'image_request_timeout'
    assert 'private' not in limited.detail + timed_out.detail


def test_provider_deadline_cancels_call_and_next_teacher_can_proceed(monkeypatch):
    monkeypatch.setattr(images, 'get_image_generation_timeout_seconds', lambda: .02)
    state = {'calls': 0, 'cancelled': False}
    async def run():
        async def provider(*args):
            state['calls'] += 1
            if state['calls'] > 1:
                return 'https://example.com/ready.png'
            try:
                await asyncio.Event().wait()
            finally:
                state['cancelled'] = True
        service = images.ImageGenerationService.__new__(images.ImageGenerationService)
        service.is_image_generation_disabled = False
        service.is_stock_provider_selected = lambda: False
        service.image_gen_func = provider
        service.output_directory = '.'
        with pytest.raises(images.HTTPException) as failure:
            await service.generate_image(ImagePrompt(prompt='课堂观察'))
        assert failure.value.provider_code == 'image_request_timeout'
        assert state == {'calls': 1, 'cancelled': True}
        assert await service.generate_image(ImagePrompt(prompt='另一张图')) == 'https://example.com/ready.png'
    asyncio.run(run())


def test_gemini_cancellation_closes_async_transport_without_background_thread(monkeypatch, tmp_path):
    state = {}
    async def run():
        started = asyncio.Event()
        class Client:
            def __init__(self, **kwargs):
                state["options"] = kwargs["http_options"]
                self.aio = self
                self.models = self
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_args):
                state["async_closed"] = True
            def close(self):
                state["sync_closed"] = True
            async def generate_content(self, **_kwargs):
                state["calls"] = state.get("calls", 0) + 1
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    state["cancelled"] = True
        monkeypatch.setattr(images.genai, "Client", Client)
        service = images.ImageGenerationService.__new__(images.ImageGenerationService)
        task = asyncio.create_task(service._generate_image_google("课堂观察", str(tmp_path), "test-model"))
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert state["calls"] == 1
    assert state["cancelled"] and state["async_closed"] and state["sync_closed"]
    assert state["options"]["retry_options"] == {"attempts": 1}


def test_gemini_image_config_receives_requested_aspect_ratio(monkeypatch, tmp_path):
    state = {}

    class Client:
        def __init__(self, **kwargs):
            self.aio = self
            self.models = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def close(self):
            return None

        async def generate_content(self, **kwargs):
            state["config"] = kwargs["config"]
            part = type("Part", (), {"inline_data": None})()
            return type("Response", (), {"parts": [part], "candidates": []})()

    monkeypatch.setattr(images.genai, "Client", Client)
    service = images.ImageGenerationService.__new__(images.ImageGenerationService)

    with pytest.raises(images.HTTPException):
        asyncio.run(
            service._generate_image_google(
                "课堂观察",
                str(tmp_path),
                "test-model",
                aspect_ratio="21:9",
            )
        )

    assert state["config"].image_config.aspect_ratio == "21:9"


def test_serialized_image_wait_does_not_start_provider_timeout(monkeypatch):
    state = {"budgets": 0, "calls": 0}
    async def run():
        lock = asyncio.Lock()
        class Budget:
            async def __aenter__(self):
                state["budgets"] += 1
            async def __aexit__(self, *_args):
                pass
        monkeypatch.setattr(images, "model_request_slot", lambda _lane: lock)
        monkeypatch.setattr(images.asyncio, "timeout", lambda _seconds: Budget())
        async def provider(*_args):
            state["calls"] += 1
            return "https://example.com/image.png"
        service = images.ImageGenerationService.__new__(images.ImageGenerationService)
        service.is_image_generation_disabled = False
        service.is_stock_provider_selected = lambda: False
        service.image_gen_func = provider
        service.output_directory = "."
        await lock.acquire()
        task = asyncio.create_task(service.generate_image(ImagePrompt(prompt="种子")))
        await asyncio.sleep(0)
        assert state == {"budgets": 0, "calls": 0}
        lock.release()
        assert await task == "https://example.com/image.png"
        assert state == {"budgets": 1, "calls": 1}
    asyncio.run(run())
