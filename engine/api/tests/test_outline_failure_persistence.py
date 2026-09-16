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


def _three_page_plan():
    from models.kindergarten_lesson_plan import KindergartenLessonPlan

    def slide(no, title):
        return {
            "slide_no": no,
            "slide_type": "other",
            "teaching_goal": title,
            "screen_content": {"title": title, "points": [f"{title}要点"]},
            "teacher_note": f"讲解{title}",
            "assets": [],
        }

    return KindergartenLessonPlan.model_validate(
        {
            "meta": {
                "topic": "认识小兔子",
                "age_group": "4-5岁",
                "domain": "science",
                "duration_minutes": 20,
            },
            "lesson_goals": ["观察小兔子的外形"],
            "lesson_arc": ["导入", "观察", "回顾"],
            "slides": [
                slide(1, "封面"),
                slide(2, "观察长耳朵"),
                slide(3, "课堂回顾"),
            ],
        }
    )


def _failed_quality_report():
    from services.kindergarten_plan_quality_service import (
        KindergartenPlanIssue,
        KindergartenPlanQualityReport,
    )

    return KindergartenPlanQualityReport(
        passed=False,
        errors=[
            KindergartenPlanIssue(
                severity="error",
                code="game-contract-missing",
                message="缺游戏契约",
            )
        ],
    )


def test_reviewable_quality_error_keeps_outline_instead_of_http_422(monkeypatch):
    from services.kindergarten_presentation_planning_service import (
        KindergartenPlanningQualityError,
    )

    plan = _three_page_plan()
    report = _failed_quality_report()

    async def boom(*_args, **_kwargs):
        raise KindergartenPlanningQualityError(report, 1, plan)

    monkeypatch.setattr(kindergarten, "_generate_validated_plan", boom)
    payload = SimpleNamespace(content_mode="classroom")
    result = asyncio.run(
        kindergarten._generate_reviewable_plan(payload, SimpleNamespace())
    )
    assert result.plan is plan
    assert result.quality.passed is False
    assert len(result.outline.slides) == 3


def test_empty_quality_error_still_becomes_http_422(monkeypatch):
    from services.kindergarten_presentation_planning_service import (
        KindergartenPlanningQualityError,
    )

    report = _failed_quality_report()

    async def boom(*_args, **_kwargs):
        raise KindergartenPlanningQualityError(report, 1, None)

    monkeypatch.setattr(kindergarten, "_generate_validated_plan", boom)
    payload = SimpleNamespace(content_mode="classroom")
    with pytest.raises(HTTPException) as error:
        asyncio.run(kindergarten._generate_reviewable_plan(payload, SimpleNamespace()))
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "KINDERGARTEN_PLAN_QUALITY_FAILED"


def test_quality_gate_keeps_streamed_outline_for_review(monkeypatch):
    from services.kindergarten_presentation_planning_service import (
        KindergartenPlanningQualityError,
    )

    plan = _three_page_plan()
    report = _failed_quality_report()

    async def boom(*_args, **_kwargs):
        raise KindergartenPlanningQualityError(report, 1, plan)

    monkeypatch.setattr(kindergarten, "_generate_validated_plan", boom)
    routing = SimpleNamespace(template="auto", reason="test", scores={"auto": 1})
    monkeypatch.setattr(
        kindergarten,
        "_apply_visual_mode",
        lambda payload, result, available_templates=None: (result, routing, None),
    )
    monkeypatch.setattr(
        kindergarten, "_available_auto_templates", AsyncMock(return_value={})
    )
    monkeypatch.setattr(
        kindergarten,
        "MEM0_PRESENTATION_MEMORY_SERVICE",
        SimpleNamespace(store_generated_outlines=AsyncMock()),
    )
    presentation = SimpleNamespace(
        id=uuid.uuid4(),
        outlines=None,
        n_slides=8,
        title="",
        theme={
            "kindergarten_generation": {
                "outline_status": "pending",
                "request": {
                    "topic": "认识小兔子",
                    "age_group": "4-5岁",
                    "domain": "science",
                    "content_mode": "classroom",
                    "n_slides": 8,
                },
            }
        },
        model_dump=lambda **_kw: {"id": "p1", "title": "认识小兔子", "n_slides": 3},
    )
    monkeypatch.setattr(
        kindergarten, "get_by_id_unscoped", AsyncMock(return_value=presentation)
    )
    session = SimpleNamespace(
        add=lambda _item: None,
        commit=AsyncMock(),
        rollback=AsyncMock(),
        refresh=AsyncMock(),
    )
    request = SimpleNamespace(is_disconnected=AsyncMock(return_value=False))

    async def run():
        response = await kindergarten.stream_kindergarten_presentation_outline(
            presentation.id, request, sql_session=session
        )
        return [chunk async for chunk in response.body_iterator]

    events = [
        json.loads(chunk.split("data: ", 1)[1]) for chunk in asyncio.run(run())
    ]
    assert all(event.get("type") != "error" for event in events)
    outline_event = next(event for event in events if event.get("type") == "outline")
    assert len(outline_event["outline"]["slides"]) == 3
    assert presentation.outlines["slides"]
    generation = presentation.theme["kindergarten_generation"]
    assert generation["outline_status"] == "ready"
    assert generation["quality_warning"]
