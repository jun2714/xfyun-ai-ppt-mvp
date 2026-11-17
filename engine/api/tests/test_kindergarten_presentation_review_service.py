"""Real SQLite claims/owner/version tests. Model replies are deterministic fixtures."""
import asyncio
import copy
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, select, update
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel

from api.v1.auth.context import reset_current_owner_id, set_current_owner_id
from models.kindergarten_content_review import REVIEW_CRITERIA, ModelReply
from models.kindergarten_lesson_plan import KindergartenLessonPlan
from models.kindergarten_presentation_review import ApplyPresentationReviewRequest, PresentationReviewRequest
from models.sql.presentation import PresentationModel, PresentationVersion
from models.sql.slide import SlideModel
from models.sql.user import User
from services import kindergarten_presentation_review_service as service
from services.kindergarten_visual_planning_service import apply_ai_background_visual_plan
from services.owner_scope import OWNER_SESSION_INFO_KEY


def _plan():
    return KindergartenLessonPlan.model_validate({
        "meta": {"topic": "认识海洋动物", "age_group": "4-5岁", "domain": "science", "duration_minutes": 20},
        "lesson_goals": ["观察海龟和海豚的外形差异"], "lesson_arc": ["观察", "比较", "回顾"],
        "slides": [
            {"slide_no": 1, "slide_type": "cover-scene", "teaching_goal": "认识本次观察对象",
             "screen_content": {"title": "认识海洋动物", "points": []},
             "teacher_note": "邀请幼儿观察海龟和海豚的外形。", "assets": []},
            {"slide_no": 2, "slide_type": "other", "teaching_goal": "比较海龟和海豚的外形",
             "screen_content": {"title": "五大领域总复习", "points": ["唱歌、跑步、画画都学一下"]},
             "teacher_note": "教师请幼儿观察并说出两个对象的不同。", "assets": []},
            {"slide_no": 3, "slide_type": "recap", "teaching_goal": "回顾观察到的外形差异",
             "screen_content": {"title": "回顾我们的发现", "points": ["海龟有龟壳"]},
             "teacher_note": "请幼儿说出海龟与海豚的一个外形差异。", "assets": []},
        ],
    })


def _review(*findings):
    return {"criteria_checked": list(REVIEW_CRITERIA), "findings": list(findings),
            "source_status": "not_required", "source_quotes": [], "needs_human": False,
            "human_questions": []}


def _revision_steps():
    finding = {"issue_id": "topic-1", "criterion": "topic_focus", "severity": "error",
               "slide_no": 2, "field_path": "screen_content.title", "evidence": "五大领域总复习",
               "requirement": "围绕海洋动物外形比较展开", "explanation": "目标扩展成无关领域",
               "suggestion": "改成观察和比较两种海洋动物", "requires_source": False}
    replacement = _plan().slides[1].model_dump(mode="json")
    replacement["screen_content"]["title"] = "观察海龟与海豚"
    return [_review(finding), {"replacements": [{"slide_no": 2, "issue_ids": ["topic-1"],
                                               "replacement": replacement}]}, _review()]


class Caller:
    def __init__(self, *steps, entered=None, release=None, on_call=None):
        self.steps = list(steps) or [_review()]
        self.calls = []
        self.entered = entered
        self.release = release
        self.on_call = on_call
        self.drained = False

    async def __call__(self, call):
        self.calls.append(call)
        if self.on_call:
            self.on_call()
        if self.entered:
            self.entered.set()
        try:
            if self.release:
                await self.release.wait()
            return ModelReply(payload=copy.deepcopy(self.steps.pop(0)))
        finally:
            self.drained = True


@asynccontextmanager
async def _database(tmp_path, *, mode="classroom", visual_mode="template", expire_on_commit=False,
                    opaque_outline=True):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'review.db'}", pool_size=4)

    @event.listens_for(engine.sync_engine, "connect")
    def sqlite_options(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=2000")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(lambda conn: SQLModel.metadata.create_all(
            conn, tables=[User.__table__, PresentationModel.__table__, SlideModel.__table__]))
    sessions = async_sessionmaker(engine, expire_on_commit=expire_on_commit)
    owner, other_owner, presentation_id = uuid4(), uuid4(), uuid4()
    plan = _plan()
    brief = {**plan.meta.model_dump(mode="json"), "content_mode": mode, "n_slides": 3}
    outline = plan.to_presentation_outline()
    for slide in outline.slides:
        slide.content_contract.visual_audience = "teacher" if mode == "training" else "child"
    if visual_mode == "ai-background" and mode != "training":
        outline = apply_ai_background_visual_plan(outline, topic=brief["topic"], domain=brief["domain"],
                                                  visual_style_hint="柔和水彩", content_mode=mode)
    raw_outline = outline.model_dump(mode="json")
    # An opaque saved field verifies unchanged pages survive byte-for-value, not
    # a parse/re-serialize round trip that drops extension fields.
    if opaque_outline:
        raw_outline["slides"][0]["saved_extension"] = {"keep": ["verbatim", 1]}
    source = service.make_review_source(brief, plan, raw_outline)
    theme = {"custom_color": "original", "kindergarten_generation": {
        "content_mode": mode, "visual_mode": visual_mode, "domain": "science", "visual_style": "柔和水彩",
        "selected_template": "existing-template",
    }, service.REVIEW_THEME_KEY: {"source": source}}
    async with sessions() as session:
        session.add_all([User(id=owner, username=str(owner), hashed_password="test-only"),
                         User(id=other_owner, username=str(other_owner), hashed_password="test-only")])
        await session.flush()
        session.add(PresentationModel(id=presentation_id, owner_id=owner, version=PresentationVersion.V2_STANDARD,
                                      content="认识海洋动物", n_slides=3, language="zh", theme=theme,
                                      outlines=raw_outline))
        await session.commit()

    class Database:
        def session(self, as_owner=owner):
            session = sessions()
            if as_owner is not None:
                session.info[OWNER_SESSION_INFO_KEY] = as_owner
            return session

        async def row(self):
            async with self.session() as session:
                return await session.get(PresentationModel, presentation_id)

        async def mutate(self, **fields):
            async with self.session() as session:
                await session.execute(update(PresentationModel).where(
                    PresentationModel.id == presentation_id).values(**fields))
                await session.commit()

    db = Database()
    db.engine, db.id, db.owner, db.other_owner, db.source = engine, presentation_id, owner, other_owner, source
    try:
        yield db
    finally:
        await engine.dispose()


def _request(db, **kwargs):
    return PresentationReviewRequest(source_version=db.source["source_version"], request_id=uuid4(), **kwargs)


async def _review_and_revision(db):
    async with db.session() as session:
        return await service.review_presentation(session, db.id, _request(db, max_revision_rounds=1),
                                                 caller=Caller(*_revision_steps()))


def test_source_hash_is_canonical_and_patch_cannot_forge_or_delete_namespace():
    plan = _plan()
    brief = {**plan.meta.model_dump(mode="json"), "n_slides": 3}
    source = service.make_review_source(brief, plan, plan.to_presentation_outline())
    assert source == service.make_review_source(dict(reversed(list(brief.items()))), plan, source["outline"])
    original = {service.REVIEW_THEME_KEY: {"source": source, "active": {"x": 1}}, "color": "a"}
    result = service.preserve_review_metadata(original, {service.REVIEW_THEME_KEY: {"source": "forged"}, "color": "b"})
    assert result[service.REVIEW_THEME_KEY] == original[service.REVIEW_THEME_KEY]
    result[service.REVIEW_THEME_KEY]["active"]["x"] = 2
    assert original[service.REVIEW_THEME_KEY]["active"]["x"] == 1
    assert service.preserve_review_metadata(original, None)[service.REVIEW_THEME_KEY] == original[service.REVIEW_THEME_KEY]
    assert service.REVIEW_THEME_KEY not in service.preserve_review_metadata({}, {service.REVIEW_THEME_KEY: {"source": "forged"}})


def test_saved_source_before_visual_fields_can_be_reviewed_and_applied(tmp_path):
    async def run():
        async with _database(tmp_path) as db:
            row = await db.row()
            raw = row.theme[service.REVIEW_THEME_KEY]["source"]
            for slide in raw["plan"]["slides"]:
                slide.pop("visual_representation")
            for slide in raw["outline"]["slides"]:
                slide["content_contract"].pop("visual_representation")
                slide["content_contract"].pop("teaching_domain")
            raw["source_version"] = service._digest({key: raw[key] for key in ("brief","plan","outline")})
            await db.mutate(theme=row.theme, outlines=raw["outline"])
            db.source = raw
            reviewed = await _review_and_revision(db)
            assert reviewed.can_apply
            async with db.session() as session:
                applied = await service.apply_review(session, db.id, {
                    "review_id": reviewed.review_id, "source_version": raw["source_version"],
                })
            assert applied.outlines.slides[1].content.startswith("观察海龟与海豚")
            # New defaults do not silently rewrite untouched old outline pages.
            assert (await db.row()).outlines["slides"][0] == raw["outline"]["slides"][0]
    asyncio.run(run())


@pytest.mark.parametrize("changes", [{"max_revision_rounds": 3}, {"max_model_calls": 6},
                                      {"timeout_seconds": 601}, {"plan": {}}])
def test_review_request_has_bounded_server_owned_inputs(changes):
    with pytest.raises(ValidationError):
        PresentationReviewRequest(source_version="a" * 64, request_id=uuid4(), **changes)


def test_owner_scope_rejects_missing_identity_foreign_owner_and_unowned_rows(tmp_path):
    async def run():
        token = set_current_owner_id(None)
        try:
            async with _database(tmp_path) as db:
                caller = Caller()
                for owner, code in [(None, 401), (db.other_owner, 404)]:
                    for operation in ("read", "review", "apply"):
                        async with db.session(owner) as session:
                            with pytest.raises(HTTPException) as error:
                                if operation == "read":
                                    await service.read_review_source(session, db.id)
                                elif operation == "review":
                                    await service.review_presentation(session, db.id, _request(db), caller=caller)
                                else:
                                    await service.apply_review(session, db.id, {"review_id": uuid4(), "source_version": db.source["source_version"]})
                            assert error.value.status_code == code
                await db.mutate(owner_id=None)
                async with db.session() as session:
                    with pytest.raises(HTTPException) as error:
                        await service.read_review_source(session, db.id)
                    assert error.value.status_code == 404
                assert not caller.calls
        finally:
            reset_current_owner_id(token)
    asyncio.run(run())


@pytest.mark.parametrize("problem,reason", [("missing", "review_source_missing"), ("invalid", "review_source_invalid"),
                                            ("manual_edit", "outline_changed"), ("large", "review_source_unavailable")])
def test_no_reconstruction_of_missing_invalid_or_manually_changed_source(tmp_path, problem, reason):
    async def run():
        async with _database(tmp_path) as db:
            row = await db.row()
            if problem == "missing":
                row.theme.pop(service.REVIEW_THEME_KEY)
            elif problem == "invalid":
                row.theme[service.REVIEW_THEME_KEY]["source"]["source_version"] = "b" * 64
            elif problem == "large":
                row.theme[service.REVIEW_THEME_KEY] = {"source": None, "unavailable_reason": "当前大纲超出文本审核范围"}
            else:
                row.outlines["slides"][0]["content"] = "教师已手动修改"
            await db.mutate(theme=row.theme, outlines=row.outlines)
            async with db.session() as session:
                state = await service.read_review_source(session, db.id)
                assert not state.available and state.reason == reason
            caller = Caller()
            async with db.session() as session:
                with pytest.raises(HTTPException) as error:
                    await service.review_presentation(session, db.id, _request(db), caller=caller)
                assert error.value.status_code == 409 and error.value.detail["code"] == reason
            assert not caller.calls
    asyncio.run(run())


def test_persisted_deduplication_releases_connection_during_model_wait(tmp_path):
    async def run():
        async with _database(tmp_path, expire_on_commit=True) as db:
            request = _request(db)
            async with db.session() as session:
                def check_released():
                    assert not session.in_transaction()
                    assert db.engine.pool.checkedout() == 0
                caller = Caller(on_call=check_released)
                first = await service.review_presentation(session, db.id, request, caller=caller)
            assert first.result.status == "passed" and not first.can_apply
            replay_caller = Caller()
            async with db.session() as session:
                replay = await service.review_presentation(session, db.id, request, caller=replay_caller)
            assert replay == first and len(caller.calls) == 1 and not replay_caller.calls
            async with db.session() as session:
                with pytest.raises(HTTPException) as error:
                    await service.review_presentation(session, db.id, request.model_copy(update={"max_revision_rounds": 1}), caller=replay_caller)
                assert error.value.detail["code"] == "review_request_conflict"
            saved = (await db.row()).theme[service.REVIEW_THEME_KEY]
            assert "active" not in saved and saved["latest_request_id"] == str(request.request_id)
    asyncio.run(run())


def test_simultaneous_two_session_claim_uses_sql_cas_not_process_lock(tmp_path, monkeypatch):
    async def run():
        async with _database(tmp_path) as db:
            both_read = asyncio.Event()
            arrived = 0
            original_cas = service._cas

            async def synchronize_claim(session, row, theme, **kwargs):
                nonlocal arrived
                if "active" in theme[service.REVIEW_THEME_KEY] and not kwargs.get("apply"):
                    arrived += 1
                    if arrived == 2:
                        both_read.set()
                    await asyncio.wait_for(both_read.wait(), 2)
                return await original_cas(session, row, theme, **kwargs)

            monkeypatch.setattr(service, "_cas", synchronize_claim)
            caller = Caller()
            request = _request(db)
            async def run_one():
                async with db.session() as session:
                    return await service.review_presentation(session, db.id, request, caller=caller)
            results = await asyncio.gather(run_one(), run_one(), return_exceptions=True)
            assert sum(not isinstance(result, Exception) for result in results) == 1
            conflict = next(result for result in results if isinstance(result, HTTPException))
            assert conflict.status_code == 409 and len(caller.calls) == 1
            assert "active" not in (await db.row()).theme[service.REVIEW_THEME_KEY]
    asyncio.run(run())


def test_edit_during_review_is_preserved_and_completed_report_is_stale(tmp_path):
    async def run():
        async with _database(tmp_path) as db:
            entered, release = asyncio.Event(), asyncio.Event()
            caller = Caller(*_revision_steps(), entered=entered, release=release)
            async with db.session() as session:
                task = asyncio.create_task(service.review_presentation(
                    session, db.id, _request(db, max_revision_rounds=1), caller=caller))
                await asyncio.wait_for(entered.wait(), 2)
                async with db.session() as reading:
                    state = await service.read_review_source(reading, db.id)
                    assert state.reason == "review_running" and not state.available
                row = await db.row()
                row.outlines["slides"][1]["content"] = "教师在审核期间编辑的标题"
                row.theme["custom_color"] = "new"
                await db.mutate(theme=row.theme, outlines=row.outlines)
                release.set()
                result = await task
            assert result.stale and not result.can_apply and result.changed_slide_numbers == [2]
            saved = await db.row()
            assert saved.outlines == row.outlines and saved.theme["custom_color"] == "new"
            assert "active" not in saved.theme[service.REVIEW_THEME_KEY]
            async with db.session() as session:
                with pytest.raises(HTTPException) as error:
                    await service.apply_review(session, db.id, {"review_id": result.review_id, "source_version": result.source_version})
                assert error.value.detail["code"] == "outline_changed"
    asyncio.run(run())


def test_cancel_drains_model_and_persists_cancelled_result_then_allows_new_request(tmp_path):
    async def run():
        async with _database(tmp_path) as db:
            entered = asyncio.Event()
            caller = Caller(entered=entered, release=asyncio.Event())
            request = _request(db)
            async with db.session() as session:
                task = asyncio.create_task(service.review_presentation(session, db.id, request, caller=caller))
                await asyncio.wait_for(entered.wait(), 2)
                task.cancel()
                result = await asyncio.wait_for(task, 2)
            assert result.result.status == "cancelled" and caller.drained and not result.can_apply
            assert "active" not in (await db.row()).theme[service.REVIEW_THEME_KEY]
            unused = Caller()
            async with db.session() as session:
                duplicate = await service.review_presentation(session, db.id, request, caller=unused)
                assert duplicate.result.status == "cancelled" and not unused.calls
            async with db.session() as session:
                new = await service.review_presentation(session, db.id, _request(db), caller=Caller())
                assert new.result.status == "passed"
    asyncio.run(run())


def test_expired_claim_is_never_automatically_restarted_or_reused(tmp_path):
    async def run():
        async with _database(tmp_path) as db:
            old_request = _request(db)
            row = await db.row()
            row.theme[service.REVIEW_THEME_KEY]["active"] = {
                "review_id": str(uuid4()), "request_id": str(old_request.request_id),
                "source_version": old_request.source_version,
                "deadline_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            }
            await db.mutate(theme=row.theme)
            async with db.session() as session:
                state = await service.read_review_source(session, db.id)
                assert state.available and state.reason == "review_expired" and state.active_review.expired
            caller = Caller()
            async with db.session() as session:
                with pytest.raises(HTTPException) as error:
                    await service.review_presentation(session, db.id, old_request, caller=caller)
                assert error.value.detail["code"] == "review_expired" and not caller.calls
            async with db.session() as session:
                await service.review_presentation(session, db.id, _request(db), caller=caller)
            async with db.session() as session:
                with pytest.raises(HTTPException) as error:
                    await service.review_presentation(session, db.id, old_request, caller=caller)
                assert error.value.detail["code"] == "review_result_archived" and len(caller.calls) == 1
    asyncio.run(run())


def test_full_results_are_bounded_without_forgetting_old_request_ids(tmp_path, monkeypatch):
    async def run():
        async with _database(tmp_path) as db:
            requests = [_request(db) for _ in range(4)]
            for request in requests:
                async with db.session() as session:
                    await service.review_presentation(session, db.id, request, caller=Caller())
            records = (await db.row()).theme[service.REVIEW_THEME_KEY]["completed"]
            assert len(records) == 4 and sum("response" in item for item in records.values()) == 3
            caller = Caller()
            async with db.session() as session:
                with pytest.raises(HTTPException) as error:
                    await service.review_presentation(session, db.id, requests[0], caller=caller)
                assert error.value.detail["code"] == "review_result_archived" and not caller.calls
            monkeypatch.setattr(service, "_MAX_TRACKED_REQUESTS", 4)
            async with db.session() as session:
                with pytest.raises(HTTPException) as error:
                    await service.review_presentation(session, db.id, _request(db), caller=caller)
                assert error.value.detail["code"] == "review_history_limit" and not caller.calls
    asyncio.run(run())


@pytest.mark.parametrize("mode,visual_mode", [("classroom", "template"), ("training", "template"),
                                             ("classroom", "ai-background"), ("training", "ai-background")])
def test_apply_verified_revision_updates_source_and_preserves_visual_contracts(tmp_path, mode, visual_mode):
    async def run():
        async with _database(tmp_path, mode=mode, visual_mode=visual_mode) as db:
            before = await db.row()
            reviewed = await _review_and_revision(db)
            assert reviewed.can_apply and reviewed.changed_slide_numbers == [2]
            payload = ApplyPresentationReviewRequest(review_id=reviewed.review_id, source_version=reviewed.source_version)
            async with db.session() as session:
                applied = await service.apply_review(session, db.id, payload)
            saved = await db.row()
            assert saved.outlines["slides"][0] == before.outlines["slides"][0]
            assert saved.outlines["slides"][2] == before.outlines["slides"][2]
            contract = saved.outlines["slides"][1]["content_contract"]
            assert contract["screen_title"] == "观察海龟与海豚"
            assert contract["visual_audience"] == ("teacher" if mode == "training" else "child")
            backgrounds = [item for item in contract["asset_contracts"] if item["planning_slot"] == "ai_background"]
            if visual_mode == "ai-background" and mode != "training":
                assert len(backgrounds) == 1 and "第2页" in backgrounds[0]["semantic_label"]
                assert "柔和水彩" in backgrounds[0]["description"] and "观察海龟与海豚" in backgrounds[0]["description"]
                assert contract["requires_images"] and contract["media_role"] in {"background", "mixed"}
            else:
                assert not backgrounds
            namespace = saved.theme[service.REVIEW_THEME_KEY]
            assert namespace["source"]["plan"] == reviewed.result.plan.model_dump(mode="json")
            assert namespace["source"]["outline"] == saved.outlines
            assert applied.source_version == namespace["source"]["source_version"] != reviewed.source_version
            assert saved.theme["kindergarten_generation"] == before.theme["kindergarten_generation"]
            async with db.session() as session:
                repeated = await service.apply_review(session, db.id, payload)
            assert repeated.source_version == applied.source_version and (await db.row()).outlines == saved.outlines
            edited = copy.deepcopy(saved.outlines)
            edited["slides"][1]["content"] = "应用后又手改"
            await db.mutate(outlines=edited)
            async with db.session() as session:
                with pytest.raises(HTTPException) as error:
                    await service.apply_review(session, db.id, payload)
                assert error.value.detail["code"] == "review_already_applied"
            assert (await db.row()).outlines == edited
    asyncio.run(run())


@pytest.mark.parametrize("generated", ["structure", "slide"])
def test_generated_deck_cannot_be_applied_even_if_review_preceded_generation(tmp_path, generated):
    async def run():
        async with _database(tmp_path) as db:
            reviewed = await _review_and_revision(db)
            if generated == "structure":
                await db.mutate(structure={"slides": []})
            else:
                async with db.session() as session:
                    session.add(SlideModel(owner_id=db.owner, presentation=db.id, layout_group="test", layout="test", index=0, content={}))
                    await session.commit()
            async with db.session() as session:
                state = await service.read_review_source(session, db.id)
                assert state.available and not state.latest_review.can_apply and not state.apply_available
                with pytest.raises(HTTPException) as error:
                    await service.apply_review(session, db.id, {"review_id": reviewed.review_id, "source_version": reviewed.source_version})
                assert error.value.detail["code"] == "review_generated_deck"
            assert (await db.row()).outlines == db.source["outline"]
    asyncio.run(run())


def test_apply_compare_and_swap_loses_to_manual_save_without_overwriting(tmp_path, monkeypatch):
    async def run():
        async with _database(tmp_path) as db:
            reviewed = await _review_and_revision(db)
            original_cas = service._cas
            edited = copy.deepcopy(db.source["outline"])
            edited["slides"][1]["content"] = "已保存的用户新内容"
            async def edit_before_apply(session, row, theme, **kwargs):
                if kwargs.get("apply"):
                    await db.mutate(outlines=edited)
                return await original_cas(session, row, theme, **kwargs)
            monkeypatch.setattr(service, "_cas", edit_before_apply)
            async with db.session() as session:
                with pytest.raises(HTTPException) as error:
                    await service.apply_review(session, db.id, {"review_id": reviewed.review_id, "source_version": reviewed.source_version})
                assert error.value.detail["code"] == "review_apply_conflict"
            assert (await db.row()).outlines == edited
    asyncio.run(run())


def test_two_simultaneous_apply_requests_commit_only_one_update(tmp_path, monkeypatch):
    async def run():
        async with _database(tmp_path) as db:
            reviewed = await _review_and_revision(db)
            original_cas = service._cas
            both_read, count = asyncio.Event(), 0
            async def barrier(session, row, theme, **kwargs):
                nonlocal count
                if kwargs.get("apply"):
                    count += 1
                    if count == 2:
                        both_read.set()
                    await asyncio.wait_for(both_read.wait(), 2)
                return await original_cas(session, row, theme, **kwargs)
            monkeypatch.setattr(service, "_cas", barrier)
            async def apply_one():
                async with db.session() as session:
                    return await service.apply_review(session, db.id, {"review_id": reviewed.review_id, "source_version": reviewed.source_version})
            results = await asyncio.gather(apply_one(), apply_one(), return_exceptions=True)
            assert sum(not isinstance(item, Exception) for item in results) == 1
            failure = next(item for item in results if isinstance(item, HTTPException))
            assert failure.detail["code"] == "review_apply_conflict"
            saved = await db.row()
            ns = saved.theme[service.REVIEW_THEME_KEY]
            assert ns["source"]["outline"] == saved.outlines
            assert ns["completed"][ns["latest_request_id"]]["response"]["applied"]
    asyncio.run(run())


def test_late_expired_worker_cannot_release_replacement_claim_or_become_latest(tmp_path):
    async def run():
        async with _database(tmp_path) as db:
            first_entered, first_release = asyncio.Event(), asyncio.Event()
            second_entered, second_release = asyncio.Event(), asyncio.Event()
            first_request, second_request = _request(db), _request(db)
            async with db.session() as first_session, db.session() as second_session:
                first_task = asyncio.create_task(service.review_presentation(
                    first_session, db.id, first_request,
                    caller=Caller(entered=first_entered, release=first_release)))
                await asyncio.wait_for(first_entered.wait(), 2)
                row = await db.row()
                row.theme[service.REVIEW_THEME_KEY]["active"]["deadline_at"] = (
                    datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                await db.mutate(theme=row.theme)
                second_task = asyncio.create_task(service.review_presentation(
                    second_session, db.id, second_request,
                    caller=Caller(entered=second_entered, release=second_release)))
                await asyncio.wait_for(second_entered.wait(), 2)
                first_release.set()
                first = await first_task
                saved = (await db.row()).theme[service.REVIEW_THEME_KEY]
                assert first.stale and not first.can_apply
                assert saved["active"]["request_id"] == str(second_request.request_id)
                assert saved.get("latest_request_id") != str(first_request.request_id)
                second_release.set()
                second = await second_task
            saved = (await db.row()).theme[service.REVIEW_THEME_KEY]
            assert not second.stale and "active" not in saved
            assert saved["latest_request_id"] == str(second_request.request_id)
            assert len(saved["completed"]) == 2
    asyncio.run(run())


def test_latest_verified_result_is_not_applicable_while_another_claim_exists(tmp_path):
    async def run():
        async with _database(tmp_path) as db:
            reviewed = await _review_and_revision(db)
            assert reviewed.can_apply
            row = await db.row()
            namespace = row.theme[service.REVIEW_THEME_KEY]
            latest_request = namespace["latest_request_id"]
            namespace["active"] = {"review_id": str(uuid4()), "request_id": str(uuid4()),
                                   "source_version": reviewed.source_version,
                                   "deadline_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
            await db.mutate(theme=row.theme)
            async with db.session() as session:
                state = await service.read_review_source(session, db.id)
                assert state.available and state.reason == "review_expired"
                assert not state.apply_available and not state.latest_review.can_apply
            async with db.session() as session:
                cached = await service.review_presentation(session, db.id, PresentationReviewRequest(
                    request_id=latest_request, source_version=reviewed.source_version, max_revision_rounds=1), caller=Caller())
                assert not cached.can_apply
            async with db.session() as session:
                with pytest.raises(HTTPException) as error:
                    await service.apply_review(session, db.id, {"review_id": reviewed.review_id, "source_version": reviewed.source_version})
                assert error.value.detail["code"] == "review_running"
    asyncio.run(run())


@pytest.mark.parametrize("tamper", ["history_missing", "hash_mismatch", "not_adopted", "original_mismatch"])
def test_apply_requires_server_saved_adopted_history_matching_this_source(tmp_path, tamper):
    async def run():
        async with _database(tmp_path) as db:
            reviewed = await _review_and_revision(db)
            row = await db.row()
            namespace = row.theme[service.REVIEW_THEME_KEY]
            result = namespace["completed"][namespace["latest_request_id"]]["response"]["result"]
            if tamper == "history_missing":
                result["review_history"] = []
            elif tamper == "hash_mismatch":
                result["review_history"][-1]["plan_sha256"] = "f" * 64
            elif tamper == "not_adopted":
                result["review_history"][-1]["adopted"] = False
            else:
                result["original_plan"]["slides"][0]["screen_content"]["title"] = "不属于送审原稿的页面"
            await db.mutate(theme=row.theme)
            async with db.session() as session:
                with pytest.raises(HTTPException) as error:
                    await service.apply_review(session, db.id, {"review_id": reviewed.review_id, "source_version": reviewed.source_version})
                assert error.value.detail["code"] == "review_not_applicable"
            assert (await db.row()).outlines == db.source["outline"]
    asyncio.run(run())


def test_apply_body_cannot_supply_arbitrary_plan():
    with pytest.raises(ValidationError):
        ApplyPresentationReviewRequest(review_id=uuid4(), source_version="a" * 64, plan=_plan().model_dump())


@pytest.mark.parametrize("value", [None, {"key": "值"}])
def test_json_cas_compiles_with_postgresql_jsonb_equality_and_other_dialects(value):
    # Compilation coverage only: the concurrency tests above run real SQLite.
    for dialect in (sqlite.dialect(), mysql.dialect(), postgresql.dialect()):
        expression = service._json_equal(PresentationModel.__table__.c.theme, value, dialect_name=dialect.name)
        compiled = str(expression.compile(dialect=dialect))
        if dialect.name == "postgresql":
            assert "CAST(presentations.theme AS JSONB)" in compiled
            assert "::JSONB" in compiled and "::JSON " not in compiled
        else:
            assert "CAST" not in compiled


def _generation_arguments(plan=None):
    from api.v1.ppt.endpoints.kindergarten import KindergartenPresentationCreateRequest
    from services.kindergarten_plan_quality_service import validate_kindergarten_lesson_plan
    from services.kindergarten_presentation_planning_service import ValidatedKindergartenPlanningResult
    from services.kindergarten_template_routing_service import KindergartenTemplateRoutingDecision

    plan = plan or _plan()
    return {
        "payload": KindergartenPresentationCreateRequest(**plan.meta.model_dump(), n_slides=3),
        "routing": KindergartenTemplateRoutingDecision(template="existing-template", reason="保持现有模板", scores={}),
        "visual_style_summary": "清新自然",
        "result": ValidatedKindergartenPlanningResult(plan=plan, outline=plan.to_presentation_outline(),
                                                      quality=validate_kindergarten_lesson_plan(plan), attempts=1),
    }


def test_real_patch_keeps_review_namespace_and_commits_theme_with_slides_once(tmp_path):
    from api.v1.ppt.endpoints.presentation import update_presentation

    async def run():
        async with _database(tmp_path) as db:
            await _review_and_revision(db)
            before = await db.row()
            protected = copy.deepcopy(before.theme[service.REVIEW_THEME_KEY])
            slide = SlideModel(owner_id=db.owner, presentation=db.id, layout_group="test", layout="test",
                               index=0, content={"title": "本次编辑的页面"})
            async with db.session() as session:
                commits = []
                event.listen(session.sync_session, "after_commit", lambda _: commits.append(True))
                await update_presentation(id=db.id, title="本次编辑", theme={
                    "custom_color": "edited", service.REVIEW_THEME_KEY: {"source": "forged", "completed": {}},
                }, slides=[slide], sql_session=session)
                assert len(commits) == 1
            saved = await db.row()
            assert saved.theme[service.REVIEW_THEME_KEY] == protected
            assert saved.theme["custom_color"] == "edited" and saved.title == "本次编辑"
            async with db.session() as session:
                slides = (await session.execute(select(SlideModel).where(SlideModel.presentation == db.id))).scalars().all()
                assert len(slides) == 1 and slides[0].content["title"] == "本次编辑的页面"
    asyncio.run(run())


def test_real_patch_racing_completed_review_preserves_report_and_previous_slides(tmp_path, monkeypatch):
    from api.v1.ppt.endpoints.presentation import update_presentation

    async def run():
        async with _database(tmp_path) as db:
            async with db.session() as session:
                session.add(SlideModel(owner_id=db.owner, presentation=db.id, layout_group="test", layout="test",
                                       index=0, content={"title": "已保存的旧页面"}))
                await session.commit()
            stage = service.stage_presentation_state_cas
            caller = Caller()
            async def finish_review_before_patch(session, row, **kwargs):
                if "quality_status" in kwargs["values"]:
                    async with db.session() as review_session:
                        await service.review_presentation(review_session, db.id, _request(db), caller=caller)
                return await stage(session, row, **kwargs)
            monkeypatch.setattr(service, "stage_presentation_state_cas", finish_review_before_patch)
            incoming = SlideModel(owner_id=db.owner, presentation=db.id, layout_group="test", layout="test",
                                  index=0, content={"title": "前端尚未保存的新页面"})
            async with db.session() as session:
                with pytest.raises(HTTPException) as error:
                    await update_presentation(id=db.id, title="并发编辑", theme={"custom_color": "new"},
                                              slides=[incoming], sql_session=session)
                assert error.value.status_code == 409
                assert error.value.detail["code"] == "presentation_save_conflict"
            saved = await db.row()
            ns = saved.theme[service.REVIEW_THEME_KEY]
            assert ns["latest_request_id"] in ns["completed"] and "active" not in ns and len(caller.calls) == 1
            assert saved.title != "并发编辑" and saved.theme["custom_color"] == "original"
            assert incoming.content["title"] == "前端尚未保存的新页面"
            async with db.session() as session:
                slides = (await session.execute(select(SlideModel).where(SlideModel.presentation == db.id))).scalars().all()
                assert len(slides) == 1 and slides[0].content["title"] == "已保存的旧页面"
    asyncio.run(run())


def test_real_patch_slide_insert_failure_rolls_back_theme_in_same_transaction(tmp_path):
    from api.v1.ppt.endpoints.presentation import update_presentation

    async def run():
        async with _database(tmp_path) as db:
            before = await db.row()
            # The intentionally nonexistent parent produces a real FK failure
            # during commit, after the theme CAS has already executed.
            invalid = SlideModel(owner_id=db.owner, presentation=uuid4(), layout_group="test", layout="test",
                                 index=0, content={"title": "事务失败样例"})
            async with db.session() as session:
                with pytest.raises(IntegrityError):
                    await update_presentation(id=db.id, title="不应保存", theme={"custom_color": "should-rollback"},
                                              slides=[invalid], sql_session=session)
                await session.rollback()
            saved = await db.row()
            assert saved.theme == before.theme and saved.title == before.title
    asyncio.run(run())


@pytest.mark.parametrize("old_theme", [None, {"legacy_color": "old"}])
def test_real_patch_legacy_presentation_without_review_state_still_saves(tmp_path, old_theme):
    from api.v1.ppt.endpoints.presentation import update_presentation

    async def run():
        async with _database(tmp_path) as db:
            await db.mutate(theme=old_theme)
            async with db.session() as session:
                await update_presentation(id=db.id, title="旧课件正常保存", theme={"legacy_color": "new"}, sql_session=session)
            saved = await db.row()
            assert saved.title == "旧课件正常保存" and saved.theme == {"legacy_color": "new"}
    asyncio.run(run())


@pytest.mark.parametrize("active", [False, True])
def test_source_capture_merges_fresh_review_state_instead_of_stale_orm_theme(tmp_path, active):
    from api.v1.ppt.endpoints.kindergarten import _persist_kindergarten_generation_metadata

    async def run():
        async with _database(tmp_path, opaque_outline=False) as db:
            entered, release = asyncio.Event(), asyncio.Event()
            async with db.session() as capture_session, db.session() as review_session:
                stale = await capture_session.get(PresentationModel, db.id)
                review_task = asyncio.create_task(service.review_presentation(
                    review_session, db.id, _request(db),
                    caller=Caller(entered=entered, release=release if active else None)))
                await asyncio.wait_for(entered.wait(), 2)
                if not active:
                    await review_task
                before = await db.row()
                assert stale.theme != before.theme
                await _persist_kindergarten_generation_metadata(stale, sql_session=capture_session, **_generation_arguments())
                saved = await db.row()
                ns, previous = saved.theme[service.REVIEW_THEME_KEY], before.theme[service.REVIEW_THEME_KEY]
                if active:
                    assert ns["active"] == previous["active"]
                else:
                    assert ns["completed"] == previous["completed"]
                    assert ns["latest_request_id"] == previous["latest_request_id"]
                release.set()
                await review_task
            assert (await db.row()).theme[service.REVIEW_THEME_KEY]["latest_request_id"]
    asyncio.run(run())


def test_source_capture_stages_dirty_outline_and_source_without_autoflush_or_state_loss(tmp_path):
    from api.v1.ppt.endpoints.kindergarten import _persist_kindergarten_generation_metadata

    async def run():
        async with _database(tmp_path, opaque_outline=False) as db:
            async with db.session() as capture_session:
                pending = await capture_session.get(PresentationModel, db.id)
                plan = _plan()
                plan.slides[1].screen_content.title = "新生成的观察页面"
                arguments = _generation_arguments(plan)
                pending.outlines = arguments["result"].outline.model_dump(mode="json")
                pending.title = "新生成的大纲"
                # This second session must still observe the old persisted
                # outline; the pending replacement belongs to capture_session.
                async with db.session() as review_session:
                    reviewed = await service.review_presentation(review_session, db.id, _request(db), caller=Caller())
                commits = []
                event.listen(capture_session.sync_session, "after_commit", lambda _: commits.append(True))
                await _persist_kindergarten_generation_metadata(pending, sql_session=capture_session, **arguments)
                assert len(commits) == 1
            saved = await db.row()
            ns = saved.theme[service.REVIEW_THEME_KEY]
            assert saved.outlines == arguments["result"].outline.model_dump(mode="json")
            assert saved.title == "新生成的大纲"
            assert ns["source"]["outline"] == saved.outlines and ns["source"]["plan"] == plan.model_dump(mode="json")
            assert ns["completed"][ns["latest_request_id"]]["response"]["review_id"] == str(reviewed.review_id)
            async with db.session() as session:
                state = await service.read_review_source(session, db.id)
                assert state.available and state.latest_review.stale and not state.latest_review.can_apply
    asyncio.run(run())


def test_source_capture_cas_conflict_preserves_new_report_and_rolls_back_pending_outline(tmp_path, monkeypatch):
    from api.v1.ppt.endpoints.kindergarten import _persist_kindergarten_generation_metadata

    async def run():
        async with _database(tmp_path, opaque_outline=False) as db:
            stage = service.stage_presentation_state_cas
            async with db.session() as capture_session:
                pending = await capture_session.get(PresentationModel, db.id)
                plan = _plan()
                plan.slides[1].screen_content.title = "尚未保存的新大纲"
                arguments = _generation_arguments(plan)
                pending.outlines = arguments["result"].outline.model_dump(mode="json")
                pending.title = "不能覆盖的待保存值"
                async def review_after_snapshot(session, row, **kwargs):
                    if session is capture_session:
                        async with db.session() as review_session:
                            await service.review_presentation(review_session, db.id, _request(db), caller=Caller())
                    return await stage(session, row, **kwargs)
                monkeypatch.setattr(service, "stage_presentation_state_cas", review_after_snapshot)
                with pytest.raises(HTTPException) as error:
                    await _persist_kindergarten_generation_metadata(pending, sql_session=capture_session, **arguments)
                assert error.value.status_code == 409 and error.value.detail["code"] == "presentation_save_conflict"
            saved = await db.row()
            assert saved.outlines == db.source["outline"] and saved.title != "不能覆盖的待保存值"
            ns = saved.theme[service.REVIEW_THEME_KEY]
            assert ns["latest_request_id"] in ns["completed"] and "active" not in ns
    asyncio.run(run())


def test_source_capture_rejects_dirty_outline_when_another_session_has_saved_manual_edit(tmp_path):
    from api.v1.ppt.endpoints.kindergarten import _persist_kindergarten_generation_metadata

    async def run():
        async with _database(tmp_path, opaque_outline=False) as db:
            async with db.session() as capture_session:
                pending = await capture_session.get(PresentationModel, db.id)
                plan = _plan()
                plan.slides[1].screen_content.title = "待保存的模型内容"
                arguments = _generation_arguments(plan)
                pending.outlines = arguments["result"].outline.model_dump(mode="json")
                manual = copy.deepcopy(db.source["outline"])
                manual["slides"][1]["content"] = "教师已经保存的手动修改"
                await db.mutate(outlines=manual)
                with pytest.raises(HTTPException) as error:
                    await _persist_kindergarten_generation_metadata(pending, sql_session=capture_session, **arguments)
                assert error.value.detail["code"] == "presentation_save_conflict"
            assert (await db.row()).outlines == manual
    asyncio.run(run())


def test_successful_apply_clears_previous_generation_quality_warning_only_after_adoption(tmp_path):
    async def run():
        async with _database(tmp_path) as db:
            row = await db.row()
            row.theme["kindergarten_generation"]["quality_warning"] = "原稿尚有机器检查问题"
            await db.mutate(theme=row.theme)
            reviewed = await _review_and_revision(db)
            assert reviewed.can_apply
            assert (await db.row()).theme["kindergarten_generation"]["quality_warning"] == "原稿尚有机器检查问题"
            async with db.session() as session:
                await service.apply_review(session, db.id, {"review_id": reviewed.review_id, "source_version": reviewed.source_version})
            assert "quality_warning" not in (await db.row()).theme["kindergarten_generation"]
    asyncio.run(run())


async def _stream_fixture(db, monkeypatch, *, planning_error=None):
    from api.v1.ppt.endpoints import kindergarten as endpoint

    arguments = _generation_arguments()
    payload = arguments["payload"].model_copy(update={"template": "existing-template"})
    await db.mutate(outlines=None, theme={"custom_color": "original", "kindergarten_generation": {
        "outline_status": "pending", "request": payload.model_dump(mode="json"),
    }})
    planning_calls, memory_calls, failure_calls = [], [], []

    async def planning(payload, request, *, text_chunk_callback, stop_on_disconnect):
        planning_calls.append(payload)
        await text_chunk_callback("固定测试文稿片段，无模型调用。")
        if planning_error is not None:
            raise planning_error
        return arguments["result"]

    async def remember(*args):
        memory_calls.append(args)

    original_failure = endpoint._persist_outline_failure
    async def failure(*args):
        failure_calls.append(args[1])
        await original_failure(*args)

    async def connected():
        return False

    monkeypatch.setattr(endpoint, "_generate_reviewable_plan", planning)
    monkeypatch.setattr(endpoint.MEM0_PRESENTATION_MEMORY_SERVICE, "store_generated_outlines", remember)
    monkeypatch.setattr(endpoint, "_persist_outline_failure", failure)
    return endpoint, SimpleNamespace(is_disconnected=connected), arguments["result"], planning_calls, memory_calls, failure_calls


async def _read_sse(response):
    events = []
    async for chunk in response.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        for line in text.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def test_real_stream_commits_outline_and_source_once_then_reloads_without_regeneration(tmp_path, monkeypatch):
    async def run():
        async with _database(tmp_path) as db:
            endpoint, request, result, planning_calls, memory_calls, failure_calls = await _stream_fixture(db, monkeypatch)
            stage = service.stage_presentation_state_cas
            before_commit = []
            async def observe_before_cas(session, row, **kwargs):
                persisted = await db.row()
                before_commit.append((persisted.outlines, service.REVIEW_THEME_KEY in persisted.theme))
                return await stage(session, row, **kwargs)
            monkeypatch.setattr(service, "stage_presentation_state_cas", observe_before_cas)
            async with db.session() as session:
                commits = []
                event.listen(session.sync_session, "after_commit", lambda _: commits.append(True))
                stream = await endpoint.stream_kindergarten_presentation_outline(db.id, request, sql_session=session)
                events = await _read_sse(stream)
                assert len(commits) == 1
            assert before_commit == [(None, False)]
            assert [event["type"] for event in events][-2:] == ["outline", "complete"]
            assert not any(event["type"] == "error" for event in events)
            saved = await db.row()
            assert saved.outlines == result.outline.model_dump(mode="json")
            assert saved.theme[service.REVIEW_THEME_KEY]["source"]["outline"] == saved.outlines
            assert saved.theme["kindergarten_generation"]["outline_status"] == "ready"
            assert len(planning_calls) == len(memory_calls) == 1 and not failure_calls
            async with db.session() as session:
                repeated = await _read_sse(await endpoint.stream_kindergarten_presentation_outline(db.id, request, sql_session=session))
            assert repeated[-1]["type"] == "complete" and len(planning_calls) == 1
    asyncio.run(run())


def test_real_stream_save_conflict_emits_error_without_overwriting_winner_or_failure_metadata(tmp_path, monkeypatch):
    async def run():
        async with _database(tmp_path) as db:
            endpoint, request, result, planning_calls, memory_calls, failure_calls = await _stream_fixture(db, monkeypatch)
            stage = service.stage_presentation_state_cas
            winner = {}
            async def race_before_cas(session, row, **kwargs):
                current = await db.row()
                current.theme["kindergarten_generation"]["outline_status"] = "ready"
                current.theme["server_marker"] = "newer-writer"
                current.theme[service.REVIEW_THEME_KEY] = {"source": None, "completed": {
                    str(uuid4()): {"state": "archived", "review_id": str(uuid4()), "source_version": "a" * 64},
                }}
                manual = result.outline.model_dump(mode="json")
                manual["slides"][1]["content"] = "教师刚保存的内容"
                winner.update(theme=copy.deepcopy(current.theme), outlines=copy.deepcopy(manual))
                await db.mutate(theme=current.theme, outlines=manual)
                return await stage(session, row, **kwargs)
            monkeypatch.setattr(service, "stage_presentation_state_cas", race_before_cas)
            async with db.session() as session:
                commits = []
                event.listen(session.sync_session, "after_commit", lambda _: commits.append(True))
                events = await _read_sse(await endpoint.stream_kindergarten_presentation_outline(db.id, request, sql_session=session))
                assert not commits
            assert events[-1]["type"] == "error" and "本次没有覆盖" in events[-1]["detail"]
            assert not any(event["type"] in {"outline", "complete"} for event in events)
            saved = await db.row()
            assert saved.theme == winner["theme"] and saved.outlines == winner["outlines"]
            assert not failure_calls and not memory_calls and len(planning_calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize("error", [HTTPException(status_code=503, detail="测试供应方未完成请求"),
                                   HTTPException(status_code=409, detail={"code": "different_conflict", "message": "其他生成错误"})])
def test_real_stream_other_http_errors_still_persist_failure_and_emit_sse_error(tmp_path, monkeypatch, error):
    async def run():
        async with _database(tmp_path) as db:
            endpoint, request, _, planning_calls, memory_calls, failure_calls = await _stream_fixture(
                db, monkeypatch, planning_error=error)
            async with db.session() as session:
                events = await _read_sse(await endpoint.stream_kindergarten_presentation_outline(db.id, request, sql_session=session))
            assert events[-1]["type"] == "error" and not any(event["type"] == "complete" for event in events)
            assert len(failure_calls) == len(planning_calls) == 1 and not memory_calls
            saved = await db.row()
            assert saved.outlines is None
            assert saved.theme["kindergarten_generation"]["outline_status"] == "failed"
            assert saved.theme["kindergarten_generation"]["outline_error"] == events[-1]["detail"]
            assert service.REVIEW_THEME_KEY not in saved.theme
    asyncio.run(run())
