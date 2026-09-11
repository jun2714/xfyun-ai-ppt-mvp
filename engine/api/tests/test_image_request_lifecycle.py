import asyncio

import pytest

from models.image_prompt import ImagePrompt
from services import image_generation_service as images
from utils.get_env import get_image_generation_timeout_seconds


def test_image_timeout_default_and_explicit_override(monkeypatch):
    monkeypatch.delenv("IMAGE_GENERATION_TIMEOUT_SECONDS", raising=False)
    assert get_image_generation_timeout_seconds() == 150
    monkeypatch.setenv("IMAGE_GENERATION_TIMEOUT_SECONDS", "75")
    assert get_image_generation_timeout_seconds() == 75
    monkeypatch.setenv("IMAGE_GENERATION_TIMEOUT_SECONDS", "invalid")
    assert get_image_generation_timeout_seconds() == 150


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


def test_serialized_image_wait_does_not_start_provider_timeout(monkeypatch):
    state = {"budgets": 0, "calls": 0}
    async def run():
        lock = asyncio.Lock()
        class Budget:
            async def __aenter__(self):
                state["budgets"] += 1
            async def __aexit__(self, *_args):
                pass
        monkeypatch.setattr(images, "_get_image_generation_lock", lambda: lock)
        monkeypatch.setattr(images, "is_parallel_image_generation_enabled", lambda: False)
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
