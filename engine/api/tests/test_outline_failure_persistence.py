import asyncio
import copy
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from sqlalchemy import JSON, Integer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from api.v1.ppt.endpoints.kindergarten import _persist_outline_failure
from api.v1.ppt.endpoints import kindergarten, outlines
from utils.outline_utils import get_saved_outline_failure


def test_outline_timeout_survives_real_async_rollback_and_preserves_saved_request():
    class Base(DeclarativeBase):
        pass

    class Presentation(Base):
        __tablename__ = "failure_checkpoint"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        theme: Mapped[dict] = mapped_column(JSON)

    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as session:
                saved = {"palette": "mint", "kindergarten_generation": {
                    "outline_status": "pending", "request": {"topic": "小种子", "n_slides": 8},
                }}
                presentation = Presentation(id=1, theme=saved)
                session.add(presentation)
                await session.commit()
                # Rollback must discard unfinished changes and restore saved metadata.
                presentation.theme = {"unfinished": True}
                await _persist_outline_failure(presentation, "Text model timed out after 180 seconds", session)
            async with sessions() as session:
                stored = await session.get(Presentation, 1)
                assert stored.theme["palette"] == "mint"
                generation = stored.theme["kindergarten_generation"]
                assert generation["outline_status"] == "failed"
                assert generation["outline_error"] == "Text model timed out after 180 seconds"
                assert generation["request"] == {"topic": "小种子", "n_slides": 8}
                assert "unfinished" not in stored.theme
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("endpoint", ["kindergarten", "generic"])
def test_reopening_failed_project_cannot_start_either_paid_outline_route(monkeypatch, endpoint):
    reason = "Text model timed out after 180 seconds"
    presentation = SimpleNamespace(id=uuid.uuid4(), outlines=None, theme={
        "kindergarten_generation": {"outline_status": "failed", "outline_error": reason,
                                    "request": {"topic": "测试教研", "content_mode": "training"}},
    })
    saved = copy.deepcopy(presentation.theme)
    module = kindergarten if endpoint == "kindergarten" else outlines
    monkeypatch.setattr(module, "get_by_id_unscoped", AsyncMock(return_value=presentation))
    planner = AsyncMock(side_effect=AssertionError("A failed project must not regenerate"))
    monkeypatch.setattr(module, "_generate_validated_plan" if endpoint == "kindergarten"
                        else "generate_ppt_outline", planner)
    session = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())
    route = kindergarten.stream_kindergarten_presentation_outline if endpoint == "kindergarten" else outlines.stream_outlines
    with pytest.raises(HTTPException) as error:
        asyncio.run(route(presentation.id, SimpleNamespace(), sql_session=session))
    assert error.value.status_code == 409
    assert error.value.detail == reason
    planner.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    assert presentation.theme == saved


def test_saved_outline_remains_readable_despite_a_stale_failure_marker(monkeypatch):
    saved_outline = {"slides": [{"content": "已确认的大纲"}]}
    presentation = SimpleNamespace(id=uuid.uuid4(), outlines=saved_outline, theme={
        "kindergarten_generation": {"outline_status": "failed", "outline_error": "旧错误"},
    })
    monkeypatch.setattr(kindergarten, "get_by_id_unscoped", AsyncMock(return_value=presentation))
    monkeypatch.setattr(kindergarten, "_stream_presentation_payload", lambda _p: {"slides": []})
    planner = AsyncMock(side_effect=AssertionError("Saved outlines must be replayed"))
    monkeypatch.setattr(kindergarten, "_generate_validated_plan", planner)
    async def run():
        response = await kindergarten.stream_kindergarten_presentation_outline(
            presentation.id, SimpleNamespace(), sql_session=SimpleNamespace(rollback=AsyncMock()),
        )
        return [chunk async for chunk in response.body_iterator]
    events = [json.loads(chunk.split("data: ", 1)[1]) for chunk in asyncio.run(run())]
    assert next(event for event in events if event["type"] == "outline")["outline"] == saved_outline
    planner.assert_not_called()


@pytest.mark.parametrize("theme", [None, {}, {"kindergarten_generation": {"outline_status": "pending"}},
                                  {"kindergarten_generation": {"outline_status": "ready", "outline_error": "旧错误"}}])
def test_only_terminal_outline_failures_block_generation(theme):
    assert get_saved_outline_failure(theme) is None
