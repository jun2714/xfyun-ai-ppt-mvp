"""Persist review claims/results without holding a DB connection during model IO.

The theme namespace is server-owned. Compare-and-swap updates protect independent
workers as well as browser edits; the in-memory content reviewer owns no database.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import JSON, cast, exists, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm.attributes import set_committed_value

from models.kindergarten_content_review import (
    KindergartenContentReviewRequest, KindergartenContentReviewResponse, ReviewBrief,
)
from models.kindergarten_lesson_plan import KindergartenLessonPlan
from models.kindergarten_presentation_review import (
    ActivePresentationReview, ApplyPresentationReviewRequest, ApplyPresentationReviewResponse,
    PresentationReviewRequest, PresentationReviewResponse, PresentationReviewSourceResponse,
)
from models.presentation_outline_model import PresentationOutlineModel
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from services.kindergarten_content_review_service import _plan_hash, review_kindergarten_content
from services.kindergarten_plan_quality_service import validate_kindergarten_lesson_plan
from services.owner_scope import is_row_owned_by, owner_id_from_session


REVIEW_THEME_KEY = "kindergarten_content_review"
_LEASE_GRACE_SECONDS = 30
_MAX_SAVED_REVIEWS = 3
# Refuse another review after this limit rather than forget an idempotency key
# and risk making an old browser retry billable again.
_MAX_TRACKED_REQUESTS = 128
_GENERATED_MESSAGE = "此课件已进入页面生成阶段；可以查看文本审核，但暂不应用到大纲，以免已生成页面与大纲不一致。"


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _as_dict(value) -> dict:
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def make_review_source(brief, plan, outline) -> dict:
    """Capture the actual saved outline, not an inferred replacement for it."""
    brief = ReviewBrief.model_validate(brief)
    plan = KindergartenLessonPlan.model_validate(plan)
    # Reuse the same bounded-input validation as the explicit content endpoint.
    KindergartenContentReviewRequest(brief=brief, plan=plan)
    actual_outline = (outline.model_dump(mode="json") if isinstance(outline, PresentationOutlineModel)
                      else copy.deepcopy(outline))
    parsed_outline = PresentationOutlineModel.model_validate(actual_outline)
    if len(parsed_outline.slides) != len(plan.slides):
        raise ValueError("审核源的教案页数必须与实际保存的大纲一致。")
    source = {"brief": brief.model_dump(mode="json"), "plan": plan.model_dump(mode="json"),
              "outline": actual_outline}
    source["source_version"] = _digest(source)
    return source


def preserve_review_metadata(old_theme, incoming_theme):
    """A general theme PATCH may neither inject nor remove server review state."""
    updated = _as_dict(incoming_theme)
    updated.pop(REVIEW_THEME_KEY, None)
    if isinstance(old_theme, dict) and REVIEW_THEME_KEY in old_theme:
        updated[REVIEW_THEME_KEY] = copy.deepcopy(old_theme[REVIEW_THEME_KEY])
    return updated if updated or incoming_theme is not None else None


def _fail(code: str, message: str, status_code: int = 409):
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})


async def _owned_row(session, presentation_id):
    owner = owner_id_from_session(session)
    if owner is None:
        _fail("review_login_required", "请先登录后再审核课件。", 401)
    row = (await session.execute(select(PresentationModel).where(
        PresentationModel.id == presentation_id,
    ).execution_options(skip_owner_scope=True, populate_existing=True))).scalar_one_or_none()
    if not is_row_owned_by(row, owner):
        _fail("presentation_not_found", "未找到当前账号的课件。", 404)
    return row


def _namespace(row):
    return _as_dict(_as_dict(row.theme).get(REVIEW_THEME_KEY))


def _source_state(row):
    namespace = _namespace(row)
    raw = namespace.get("source")
    if not isinstance(raw, dict):
        if isinstance(namespace.get("unavailable_reason"), str):
            return None, "review_source_unavailable", namespace["unavailable_reason"]
        return None, "review_source_missing", "此课件没有完整的原始教案快照，请使用新生成的幼教大纲进行审核。"
    try:
        source = make_review_source(raw["brief"], raw["plan"], raw["outline"])
        if source["source_version"] != raw.get("source_version"):
            raise ValueError("Source hash mismatch")
    except (KeyError, TypeError, ValueError, ValidationError):
        return None, "review_source_invalid", "已保存的审核源不完整，无法可靠对应当前课件。请重新生成大纲。"
    if source["outline"] != row.outlines:
        return source, "outline_changed", "大纲已经手动修改，原始教案快照不再对应当前内容；本次不能套用旧审核稿。"
    return source, None, "可以审核已保存的大纲；结果由你确认后才会应用。"


async def _generated(session, row) -> bool:
    if row.structure is not None:
        return True
    return bool((await session.execute(select(SlideModel.id).where(
        SlideModel.presentation == row.id,
    ).limit(1).execution_options(skip_owner_scope=True))).first())


def _active(namespace):
    value = namespace.get("active")
    if not isinstance(value, dict):
        return None
    try:
        deadline = datetime.fromisoformat(value["deadline_at"])
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return ActivePresentationReview(
            review_id=value["review_id"], request_id=value["request_id"],
            source_version=value["source_version"], deadline_at=deadline,
            expired=deadline <= datetime.now(timezone.utc),
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        _fail("review_state_invalid", "已有审核任务状态不完整，请先核对任务，暂不重复提交。")


def _completed(namespace, request_id):
    return _as_dict(_as_dict(namespace.get("completed")).get(str(request_id)))


def _archive_old_reports(namespace):
    records = _as_dict(namespace.get("completed"))
    full = [key for key, entry in records.items() if isinstance(entry, dict) and "response" in entry]
    full.sort(key=lambda key: (records[key].get("completed_at", ""), key), reverse=True)
    latest = namespace.get("latest_request_id")
    keep = {latest} if latest in full else set()
    for key in full:
        if len(keep) >= _MAX_SAVED_REVIEWS:
            break
        keep.add(key)
    for key in full:
        if key not in keep:
            record = records[key]
            response = record.pop("response")
            record.update(state="archived", review_id=response["review_id"],
                          source_version=response["source_version"])
    namespace["completed"] = records


def _stored_response(entry):
    try:
        return PresentationReviewResponse.model_validate(entry["response"])
    except (KeyError, TypeError, ValueError, ValidationError):
        _fail("review_result_invalid", "已保存的审核结果不完整，请重新发起一单审核，不能应用这份结果。")


def _changed(result):
    original, proposed = result.original_plan, result.plan
    if (original.meta != proposed.meta or original.lesson_goals != proposed.lesson_goals
            or original.lesson_arc != proposed.lesson_arc or len(original.slides) != len(proposed.slides)):
        return []
    return [after.slide_no for before, after in zip(original.slides, proposed.slides) if before != after]


def _verified_candidate(result):
    if not _changed(result) or not result.machine_quality.passed:
        return False
    if result.semantic_review is None or result.semantic_review.needs_human:
        return False
    digest = _plan_hash(result.plan)
    return any(snapshot.adopted and snapshot.round_no > 0 and snapshot.plan_sha256 == digest
               and snapshot.machine_quality.passed and not snapshot.semantic_review.needs_human
               and snapshot.semantic_review == result.semantic_review
               for snapshot in result.review_history)


def _effective_response(response, source, reason, *, generated, latest=True):
    current = response.model_copy(deep=True)
    current.stale = bool(reason or not source or source["source_version"] != current.source_version or not latest)
    current.can_apply = bool(not current.stale and not current.applied and not generated
                             and _verified_candidate(current.result))
    if current.applied:
        current.message = "这份审核稿已经应用，不会重复覆盖大纲。"
    elif current.stale:
        current.message = "大纲或审核版本已经变化，此结果保留供查看，不能覆盖当前内容。"
    elif generated:
        current.message = _GENERATED_MESSAGE
    elif current.can_apply:
        current.message = "已得到经过独立复核的修改稿，可确认后应用到当前大纲。"
    else:
        current.message = "当前没有可直接应用的已复核修改稿，请查看审核问题与处理建议。"
    return current


def _json_equal(column, value, *, dialect_name=None):
    # The existing columns are JSON, not JSONB. PostgreSQL JSON has no equality
    # operator; casting only this predicate avoids a schema migration. A JSONB
    # expression also gives the bound dictionary/JSON-null parameter JSONB type.
    comparable = cast(column, JSONB) if dialect_name == "postgresql" else column
    return or_(column.is_(None), comparable == JSON.NULL) if value is None else comparable == value


async def read_presentation_write_snapshot(session, row):
    """Read persisted JSON without flushing a planner's pending new outline."""
    table = PresentationModel.__table__
    with session.no_autoflush:
        snapshot = (await session.execute(select(table.c.theme, table.c.outlines).where(
            table.c.id == row.id, table.c.owner_id == row.owner_id,
        ))).mappings().one_or_none()
    return copy.deepcopy(dict(snapshot)) if snapshot is not None else None


async def stage_presentation_state_cas(session, row, *, expected_theme, expected_outlines,
                                       values, extra_conditions=()):
    """Stage one guarded UPDATE; the caller commits it with slides/other edits.

    Synchronize the loaded ORM attributes after the core UPDATE so a later
    autoflush cannot overwrite this state with the object's old JSON values.
    A conflict rolls back the whole transaction, including pending slide edits.
    """
    table = PresentationModel.__table__
    dialect_name = session.get_bind().dialect.name
    values = {**values, "updated_at": datetime.now(timezone.utc)}
    conditions = [table.c.id == row.id, table.c.owner_id == row.owner_id,
                  _json_equal(table.c.theme, expected_theme, dialect_name=dialect_name),
                  _json_equal(table.c.outlines, expected_outlines, dialect_name=dialect_name),
                  *extra_conditions]
    try:
        with session.no_autoflush:
            changed = await session.execute(update(table).where(*conditions).values(**values))
        if changed.rowcount != 1:
            await session.rollback()
            return False
        for key, value in values.items():
            set_committed_value(row, key, copy.deepcopy(value))
        return True
    except OperationalError:
        await session.rollback()
        return False


async def _cas(session, row, theme, *, outlines=None, apply=False):
    values, conditions = {"theme": theme}, []
    if apply:
        table = PresentationModel.__table__
        conditions = [_json_equal(table.c.structure, row.structure, dialect_name=session.get_bind().dialect.name),
                      ~exists(select(SlideModel.id).where(SlideModel.presentation == row.id))]
        values["outlines"] = outlines
    if not await stage_presentation_state_cas(
        session, row, expected_theme=copy.deepcopy(row.theme), expected_outlines=copy.deepcopy(row.outlines),
        values=values, extra_conditions=conditions,
    ):
        return False
    try:
        await session.commit()
        return True
    except OperationalError:
        await session.rollback()
        return False


async def read_review_source(session, presentation_id) -> PresentationReviewSourceResponse:
    row = await _owned_row(session, presentation_id)
    namespace = _namespace(row)
    source, reason, message = _source_state(row)
    generated = await _generated(session, row)
    active = _active(namespace)
    latest = None
    if namespace.get("latest_request_id"):
        entry = _completed(namespace, namespace["latest_request_id"])
        if entry:
            latest = _effective_response(_stored_response(entry), source, reason, generated=generated)
            if active:
                latest.can_apply = False
                latest.message = "请先处理当前审核任务，再应用修改稿。"
    if not reason and active:
        reason = "review_expired" if active.expired else "review_running"
        message = ("上次审核未完成，已超过等待期限，未自动重新调用模型。请核对后明确发起新一单审核。"
                   if active.expired else "此课件正在审核中，请等待结果，不要重复提交。")
    elif not reason and generated:
        message = _GENERATED_MESSAGE
    return PresentationReviewSourceResponse(
        available=source is not None and reason in {None, "review_expired"},
        reason=reason, message=message,
        source_version=source["source_version"] if source else None,
        brief=source["brief"] if source else None, plan=source["plan"] if source else None,
        latest_review=latest, active_review=active,
        apply_available=bool(latest and latest.can_apply and not active),
    )


def _fallback_result(request, *, cancelled):
    return KindergartenContentReviewResponse(
        status="cancelled" if cancelled else "model_error",
        message="审核已取消，保留当前原稿。" if cancelled else "本次审核未完成，已保留原稿，请查看任务状态后再重试。",
        original_plan=request.plan, plan=request.plan,
        machine_quality=validate_kindergarten_lesson_plan(request.plan, content_mode=request.brief.content_mode),
        elapsed_ms=0, failure_code="review_cancelled" if cancelled else "presentation_review_interrupted",
        limitations=["未取得完整执行记录；不能据本次记录推断远端没有消耗模型额度。"],
    )


async def _finish(session, presentation_id, payload, review_id, result):
    request_id = str(payload.request_id)
    for _ in range(4):
        row = await _owned_row(session, presentation_id)
        namespace = _namespace(row)
        source, reason, _ = _source_state(row)
        generated = await _generated(session, row)
        active = _active(namespace)
        owns_claim = active is not None and active.review_id == review_id
        response = PresentationReviewResponse(
            review_id=review_id, source_version=payload.source_version, result=result,
            can_apply=False, changed_slide_numbers=_changed(result),
        )
        response = _effective_response(response, source, reason, generated=generated, latest=owns_claim)
        records = _as_dict(namespace.get("completed"))
        records[request_id] = {"request_hash": _digest(payload.model_dump(mode="json")),
                               "completed_at": datetime.now(timezone.utc).isoformat(),
                               "response": response.model_dump(mode="json")}
        namespace["completed"] = records
        if owns_claim:
            namespace.pop("active", None)
            namespace["latest_request_id"] = request_id
        _archive_old_reports(namespace)
        theme = _as_dict(row.theme)
        theme[REVIEW_THEME_KEY] = namespace
        if await _cas(session, row, theme):
            return response
    _fail("review_save_conflict", "审核已结束，但课件正在被修改，结果暂未保存；请先刷新查看，避免重复调用模型。")


async def review_presentation(session, presentation_id, payload, *, caller, disconnect_checker=None):
    payload = PresentationReviewRequest.model_validate(payload)
    row = await _owned_row(session, presentation_id)
    namespace = _namespace(row)
    source, reason, message = _source_state(row)
    cached = _completed(namespace, payload.request_id)
    if cached:
        if "response" not in cached:
            _fail("review_result_archived", "此请求已经执行或超时，其完整结果已归档；不会再次调用模型。请使用新的请求编号明确发起新审核。")
        if cached.get("request_hash") != _digest(payload.model_dump(mode="json")):
            _fail("review_request_conflict", "同一请求编号不能用于不同审核参数，请为新任务使用新的请求编号。")
        response = _effective_response(
            _stored_response(cached), source, reason, generated=await _generated(session, row),
            latest=namespace.get("latest_request_id") == str(payload.request_id),
        )
        if _active(namespace):
            response.can_apply = False
            response.message = "请先处理当前审核任务，再应用修改稿。"
        await session.rollback()
        return response
    if reason or source is None:
        _fail(reason or "review_source_missing", message)
    if source["source_version"] != payload.source_version:
        _fail("review_source_changed", "审核源已经更新，请刷新大纲后再发起审核。")
    active = _active(namespace)
    if active and (not active.expired or active.request_id == payload.request_id):
        _fail("review_expired" if active.expired else "review_running",
              "上次请求未完成，未自动重发；请核对后明确发起新一单审核。" if active.expired else "此课件正在审核，请等待结果。")
    records = _as_dict(namespace.get("completed"))
    if active:
        records.setdefault(str(active.request_id), {
            "state": "expired", "review_id": str(active.review_id),
            "source_version": active.source_version,
            "request_hash": namespace["active"].get("request_hash"),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    if len(records) >= _MAX_TRACKED_REQUESTS:
        _fail("review_history_limit", "此课件已达到审核记录上限，请复制为新课件后再审核；已有请求记录仍保留，不会自动重调模型。")
    namespace["completed"] = records
    request = KindergartenContentReviewRequest(
        brief=source["brief"], plan=source["plan"], max_revision_rounds=payload.max_revision_rounds,
        timeout_seconds=payload.timeout_seconds, max_model_calls=payload.max_model_calls,
    )
    review_id = uuid4()
    namespace["active"] = {
        "review_id": str(review_id), "request_id": str(payload.request_id),
        "source_version": payload.source_version,
        "request_hash": _digest(payload.model_dump(mode="json")),
        "deadline_at": (datetime.now(timezone.utc) + timedelta(
            seconds=payload.timeout_seconds + _LEASE_GRACE_SECONDS)).isoformat(),
    }
    theme = _as_dict(row.theme)
    theme[REVIEW_THEME_KEY] = namespace
    if not await _cas(session, row, theme):
        _fail("review_claim_conflict", "课件刚被修改或已有其他审核，请刷新后查看任务状态。")
    # Commit above has returned the connection to the pool. No DB transaction
    # or row lock is held while the HTTP/model work is in flight.
    try:
        result = await review_kindergarten_content(request, caller=caller, disconnect_checker=disconnect_checker)
    except asyncio.CancelledError:
        result = _fallback_result(request, cancelled=True)
    except Exception:
        result = _fallback_result(request, cancelled=False)
    saving = asyncio.create_task(_finish(session, presentation_id, payload, review_id, result))
    try:
        return await asyncio.shield(saving)
    except asyncio.CancelledError:
        # Persist a result/release our own claim even when the browser disconnects
        # as the final model response arrives. Never release someone else's claim.
        return await asyncio.shield(saving)


def _replacement_outline(source, result, generation):
    from services.kindergarten_presentation_planning_service import _outline_for_audience
    from services.kindergarten_visual_planning_service import apply_ai_background_visual_plan

    brief = ReviewBrief.model_validate(source["brief"])
    content_mode = generation.get("content_mode") or brief.content_mode
    if content_mode not in {"classroom", "training"}:
        _fail("review_visual_context_invalid", "课件的展示模式不完整，暂不应用审核稿。")
    proposed = _outline_for_audience(result.plan, content_mode)
    if generation.get("visual_mode") == "ai-background" and content_mode != "training":
        proposed = apply_ai_background_visual_plan(
            proposed, topic=brief.topic, domain=generation.get("domain") or brief.domain,
            visual_style_hint=generation.get("visual_style"), content_mode=content_mode,
        )
    actual = copy.deepcopy(source["outline"])
    for page in _changed(result):
        actual["slides"][page - 1] = proposed.slides[page - 1].model_dump(mode="json")
    PresentationOutlineModel.model_validate(actual)
    return actual


async def apply_review(session, presentation_id, payload):
    payload = ApplyPresentationReviewRequest.model_validate(payload)
    row = await _owned_row(session, presentation_id)
    namespace = _namespace(row)
    entry = _completed(namespace, namespace.get("latest_request_id"))
    if not entry:
        _fail("review_result_missing", "没有可应用的已保存审核结果。")
    response = _stored_response(entry)
    if response.review_id != payload.review_id or response.source_version != payload.source_version:
        _fail("review_result_changed", "审核结果已经变化，请刷新并查看最新一份结果。")
    source, reason, message = _source_state(row)
    if response.applied:
        if not reason and source and source["source_version"] == response.applied_source_version:
            return ApplyPresentationReviewResponse(outlines=source["outline"], source_version=source["source_version"],
                                                   message="这份审核稿已经应用，本次没有重复修改大纲。")
        _fail("review_already_applied", "这份审核稿已经应用，之后大纲又有变化，不会再次覆盖。")
    if reason or source is None:
        _fail(reason or "review_source_missing", message)
    if source["source_version"] != payload.source_version:
        _fail("review_source_changed", "当前大纲与送审版本不同，不能覆盖手动修改。")
    if _active(namespace):
        _fail("review_running", "请先处理当前审核任务，再应用修改稿。")
    if await _generated(session, row):
        _fail("review_generated_deck", _GENERATED_MESSAGE)
    if response.result.original_plan.model_dump(mode="json") != source["plan"] or not _verified_candidate(response.result):
        _fail("review_not_applicable", "此结果没有经过独立复核并采用的修改稿，不能直接应用。")
    generation = _as_dict(_as_dict(row.theme).get("kindergarten_generation"))
    try:
        outline = _replacement_outline(source, response.result, generation)
        next_source = make_review_source(source["brief"], response.result.plan, outline)
    except (TypeError, ValueError, ValidationError):
        _fail("review_outline_invalid", "修改稿与当前课件的展示契约不兼容，原大纲已保留。")
    response = response.model_copy(update={
        "applied": True, "can_apply": False, "applied_source_version": next_source["source_version"],
        "message": "已应用已复核的修改稿，未改动页面保持原有内容和视觉契约。",
    })
    namespace["source"] = next_source
    namespace["completed"][namespace["latest_request_id"]]["response"] = response.model_dump(mode="json")
    theme = _as_dict(row.theme)
    generation = _as_dict(theme.get("kindergarten_generation"))
    if "quality_warning" in generation:
        generation.pop("quality_warning", None)
        theme["kindergarten_generation"] = generation
    theme[REVIEW_THEME_KEY] = namespace
    if not await _cas(session, row, theme, outlines=outline, apply=True):
        _fail("review_apply_conflict", "大纲刚被修改或开始生成页面，本次没有覆盖，请刷新查看。")
    return ApplyPresentationReviewResponse(outlines=outline, source_version=next_source["source_version"],
                                           message=response.message)
