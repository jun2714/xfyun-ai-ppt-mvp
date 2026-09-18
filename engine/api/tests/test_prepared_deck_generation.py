import asyncio
import uuid

from services.prepared_deck_generation import (
    ASYNC_TASK_TYPE_DECK_GENERATE,
    DeckBroadcast,
    _GENERATING_DECK_ID,
    deck_task_data,
    generating_this_deck,
    iter_sse_json_events,
)


def test_task_type_is_dedicated_from_research_complete():
    assert ASYNC_TASK_TYPE_DECK_GENERATE == "ppt.generate_slides"


def test_generating_this_deck_uses_contextvar():
    presentation_id = uuid.uuid4()
    assert generating_this_deck(presentation_id) is False
    token = _GENERATING_DECK_ID.set(str(presentation_id))
    try:
        assert generating_this_deck(presentation_id) is True
        assert generating_this_deck(uuid.uuid4()) is False
    finally:
        _GENERATING_DECK_ID.reset(token)


def test_broadcast_replays_history_to_late_subscribers():
    broadcast = DeckBroadcast()
    broadcast.publish('event: response\ndata: {"type": "status", "status": "正在生成"}\n\n')
    queue = broadcast.subscribe()
    first = queue.get_nowait()
    assert "正在生成" in first
    broadcast.unsubscribe(queue)


def test_iter_sse_and_task_data_track_live_progress():
    raw = (
        'event: response\ndata: {"type": "chunk", "chunk": "{\\"index\\": 0}"}\n\n'
        'event: response\ndata: {"type": "slide_assets", "slide_index": 2}\n\n'
        'event: response\ndata: {"type": "complete"}\n\n'
    )
    events = iter_sse_json_events(raw)
    assert [event["type"] for event in events] == ["chunk", "slide_assets", "complete"]
    data = deck_task_data(
        topic="认识春天",
        stage="slides",
        progress=40,
        presentation_id="abc",
        created_slides=3,
        n_slides=10,
    )
    assert data["presentation_id"] == "abc"
    assert data["remaining_slides"] == 7
    assert data["progress"] == 40


def test_observer_stream_follows_instead_of_starting_a_second_worker(monkeypatch):
    from api.v1.ppt.endpoints import presentation as presentation_endpoint
    from models.sql.presentation import PresentationModel, PresentationVersion
    from datetime import datetime, timezone

    presentation_id = uuid.uuid4()
    presentation = PresentationModel(
        id=presentation_id,
        owner_id=None,
        version=PresentationVersion.V2_STANDARD,
        content="认识春天",
        n_slides=8,
        language="Chinese",
        title="认识春天",
        outlines={"slides": [{"content": "封面"}]},
        structure={"slides": [0]},
        layout={"slides": [{"id": "cover"}]},
        generation_mode="standard",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    class _Session:
        async def get(self, _model, _id):
            return presentation

        async def scalars(self, _query):
            return []

    started = {}

    class _Task:
        id = "task-follow-1"

    async def fake_ensure(pid, **kwargs):
        started["id"] = str(pid)
        started["topic"] = kwargs.get("topic")
        return _Task()

    async def fake_follow(pid, task_id):
        yield 'event: response\ndata: {"type": "status", "status": "正在后台生成课件"}\n\n'
        yield 'event: response\ndata: {"type": "complete"}\n\n'

    monkeypatch.setattr(presentation_endpoint, "ensure_prepared_deck_job", fake_ensure)
    monkeypatch.setattr(presentation_endpoint, "follow_prepared_deck_job", fake_follow)
    monkeypatch.setattr(presentation_endpoint, "generating_this_deck", lambda _id: False)

    async def consume():
        response = await presentation_endpoint.stream_presentation(
            presentation_id,
            _Session(),
        )
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    body = asyncio.run(consume())
    assert started["id"] == str(presentation_id)
    assert "正在后台生成课件" in body
    assert '"type": "complete"' in body
