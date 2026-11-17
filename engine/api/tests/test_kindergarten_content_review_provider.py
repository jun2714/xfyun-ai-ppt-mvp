import asyncio
import json

import httpx
import pytest

from models.kindergarten_content_review import ModelCall
from services.kindergarten_content_review_provider import (
    OpenAICompatibleReviewCaller,
    ReviewProviderError,
    ReviewRuntime,
    get_review_runtime,
)


def _call():
    return ModelCall(stage="review", system_prompt="Review the supplied data.",
                     payload={"plan": {"text": "海洋动物"}}, response_schema={"type": "object"}, round_no=0)


def _runtime():
    return ReviewRuntime(base_url="https://provider.invalid/v1", api_key="test-secret",
                         model="test-model", extra_body={"thinking": {"type": "disabled"}})


def test_provider_submits_once_and_preserves_unknown_usage():
    requests = []

    def handler(request):
        requests.append(request)
        data = json.loads(request.content)
        assert data["messages"][0]["role"] == "system"
        assert data["messages"][1]["role"] == "user"
        assert data["stream"] is False
        assert data["thinking"] == {"type": "disabled"}
        return httpx.Response(200, json={"model": "actual-model", "choices": [{
            "finish_reason": "stop", "message": {"content": '{"findings": []}'},
        }]})

    caller = OpenAICompatibleReviewCaller(_runtime(), transport=httpx.MockTransport(handler))
    reply = asyncio.run(caller(_call()))
    assert len(requests) == 1
    assert reply.submitted is True
    assert reply.model == "actual-model"
    assert reply.usage is None
    assert "test-secret" not in repr(_runtime())


@pytest.mark.parametrize("status", [302, 401, 429, 500, 503])
def test_provider_does_not_retry_or_follow_redirects_or_expose_error_bodies(status):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="private-provider-message test-secret",
                              headers={"Location": "https://another.invalid"})

    caller = OpenAICompatibleReviewCaller(_runtime(), transport=httpx.MockTransport(handler))
    with pytest.raises(ReviewProviderError) as error:
        asyncio.run(caller(_call()))
    assert len(requests) == 1
    assert str(error.value) == f"review_provider_http_{status}"


@pytest.mark.parametrize("payload", [
    {"choices": [{"finish_reason": "length", "message": {"content": '{}'}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": '[]'}}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": 'not-json'}}]},
    {"choices": []},
])
def test_provider_rejects_incomplete_or_invalid_output(payload):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    caller = OpenAICompatibleReviewCaller(_runtime(), transport=httpx.MockTransport(handler))
    with pytest.raises(ReviewProviderError):
        asyncio.run(caller(_call()))
    assert len(requests) == 1


def test_provider_retains_reported_token_counts_without_filling_missing_values():
    payload = {"choices": [{"message": {"content": '{}'}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 125, "completion_tokens": 30}}
    caller = OpenAICompatibleReviewCaller(_runtime(), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)))
    reply = asyncio.run(caller(_call()))
    assert reply.usage.input_tokens == 125
    assert reply.usage.output_tokens == 30
    assert reply.usage.total_tokens is None


def test_cancelling_request_closes_call_and_releases_queue_slot():
    async def run():
        from services.model_request_queue import get_request_queue

        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def handler(request):
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        caller = OpenAICompatibleReviewCaller(_runtime(), transport=httpx.MockTransport(handler))
        task = asyncio.create_task(caller(_call()))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
        assert get_request_queue("outline").active == 0

    asyncio.run(run())


def test_partial_dedicated_configuration_fails_before_any_provider_call(monkeypatch):
    monkeypatch.setenv("KINDERGARTEN_REVIEW_API_KEY", "test-secret")
    monkeypatch.delenv("KINDERGARTEN_REVIEW_BASE_URL", raising=False)
    monkeypatch.delenv("KINDERGARTEN_REVIEW_MODEL", raising=False)
    with pytest.raises(ReviewProviderError, match="review_configuration_incomplete"):
        get_review_runtime()


def test_invalid_model_json_retains_known_provider_usage():
    payload = {"choices": [{"message": {"content": 'not-json'}, "finish_reason": "stop"}],
               "model": "actual-model", "usage": {"prompt_tokens": 100, "completion_tokens": 20}}
    caller = OpenAICompatibleReviewCaller(_runtime(), transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload)))
    with pytest.raises(ReviewProviderError) as caught:
        asyncio.run(caller(_call()))
    assert caught.value.submitted is True
    assert caught.value.model == "actual-model"
    assert caught.value.usage.input_tokens == 100
    assert caught.value.usage.output_tokens == 20


def test_fractional_token_budget_is_rejected(monkeypatch):
    monkeypatch.setenv("KINDERGARTEN_REVIEW_API_KEY", "test-secret")
    monkeypatch.setenv("KINDERGARTEN_REVIEW_BASE_URL", "https://provider.invalid/v1")
    monkeypatch.setenv("KINDERGARTEN_REVIEW_MODEL", "test-model")
    monkeypatch.setenv("KINDERGARTEN_REVIEW_MAX_TOKENS", "0.5")
    with pytest.raises(ReviewProviderError, match="review_configuration_invalid"):
        get_review_runtime()


@pytest.mark.parametrize("queue_full", [False, True])
def test_queue_rejection_reports_no_submission_and_releases_waiter(monkeypatch, queue_full):
    from services import model_request_queue as queues

    async def run():
        queue = queues.FairRequestQueue(
            "outline", queues.QueueLimits(1, 1, 1, 60 if queue_full else 0.02),
        )
        monkeypatch.setattr(queues, "model_request_slot", lambda lane: queue.slot("review-owner"))
        requests = []

        def handler(request):
            requests.append(request)
            pytest.fail("A rejected waiter must not submit an HTTP request")

        async def pending_work():
            async with queue.slot("pending-owner"):
                pytest.fail("The existing owner should retain its slot")

        caller = OpenAICompatibleReviewCaller(_runtime(), transport=httpx.MockTransport(handler))
        pending = None
        async with queue.slot("existing-owner"):
            try:
                if queue_full:
                    pending = asyncio.create_task(pending_work())
                    await asyncio.sleep(0)
                expected = "review_queue_full" if queue_full else "review_queue_timeout"
                with pytest.raises(ReviewProviderError, match=expected) as caught:
                    await caller(_call())
                assert caught.value.submitted is False
                assert caught.value.model == "test-model"
                assert requests == []
                assert queue.active == 1
            finally:
                if pending is not None:
                    pending.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await pending
            assert not queue.pending
        assert queue.active == 0 and not queue.owners

    asyncio.run(run())


@pytest.mark.parametrize("end_with", ["timeout", "cancel"])
def test_real_http_timeout_or_cancellation_closes_connection_and_releases_slot(end_with):
    """Use a local TCP peer: MockTransport does not enforce httpx timeouts."""
    from services.model_request_queue import get_request_queue

    async def run():
        received = asyncio.Event()
        closed = asyncio.Event()
        request_count = 0

        async def handle(reader, writer):
            nonlocal request_count
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                length = next(int(line.split(b":", 1)[1].strip())
                              for line in headers.split(b"\r\n")
                              if line.lower().startswith(b"content-length:"))
                await reader.readexactly(length)
                request_count += 1
                received.set()
                # Never send a response; a timeout/cancel must close the client.
                await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()
                closed.set()

        server = await asyncio.start_server(handle, "127.0.0.1", 0)
        async with server:
            port = server.sockets[0].getsockname()[1]
            runtime = ReviewRuntime(
                base_url=f"http://127.0.0.1:{port}/v1", api_key="local-test-only",
                model="local-test-model", timeout_seconds=0.05 if end_with == "timeout" else 5,
            )
            caller = OpenAICompatibleReviewCaller(runtime, transport=httpx.AsyncHTTPTransport(retries=0))
            task = asyncio.create_task(caller(_call()))
            try:
                await asyncio.wait_for(received.wait(), timeout=2)
                if end_with == "cancel":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError) as caught:
                        await task
                else:
                    with pytest.raises(ReviewProviderError, match="review_provider_timeout") as caught:
                        await task
                assert caught.value.submitted is None
                assert caught.value.model == "local-test-model"
                await asyncio.wait_for(closed.wait(), timeout=2)
                assert request_count == 1
                queue = get_request_queue("outline")
                assert queue.active == 0 and not queue.pending and not queue.owners
            finally:
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

    asyncio.run(run())
