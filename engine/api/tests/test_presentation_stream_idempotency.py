import asyncio
from datetime import datetime, timezone
import json
import uuid

from api.v1.ppt.endpoints import presentation as presentation_endpoint
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel


class _ExistingDeckSession:
    def __init__(self, presentation, slides):
        self.presentation = presentation
        self.slides = slides

    async def get(self, _model, _id):
        return self.presentation

    async def scalars(self, _query):
        return self.slides


def test_refreshing_completed_standard_stream_replays_saved_slides(monkeypatch):
    presentation_id = uuid.uuid4()
    presentation = PresentationModel(
        id=presentation_id,
        owner_id=None,
        version=PresentationVersion.V2_STANDARD,
        content="认识春天的花朵",
        n_slides=1,
        language="Chinese",
        title="认识春天的花朵",
        generation_mode="standard",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    slide = SlideModel(
        owner_id=None,
        presentation=presentation_id,
        layout_group="general",
        layout="title",
        index=0,
        content={"title": "已保存页面"},
    )
    session = _ExistingDeckSession(presentation, [slide])

    async def fail_if_model_is_called(*_args, **_kwargs):
        raise AssertionError("refresh must not call the slide-content model")

    monkeypatch.setattr(
        presentation_endpoint,
        "get_slide_content_from_type_and_outline",
        fail_if_model_is_called,
    )

    async def consume_response():
        response = await presentation_endpoint.stream_presentation(
            presentation_id,
            session,
        )
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return "".join(chunks)

    body = asyncio.run(consume_response())

    events = [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]
    replayed_json = "".join(
        event["chunk"] for event in events if event.get("type") == "chunk"
    )

    assert "已保存页面" in replayed_json
    assert '"type": "complete"' in body
    assert '"type": "error"' not in body
