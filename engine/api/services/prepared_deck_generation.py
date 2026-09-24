"""Run prepared-deck slide generation independently of the browser EventSource.

Teachers can leave after confirming the outline. The worker keeps generating
text/images, fans live SSE events out to any still-open viewers, and writes
progress onto both the async task and the presentation theme so 我的项目 can
animate.
"""

from __future__ import annotations

import asyncio
from contextlib import aclosing
import json
import logging
import uuid
from contextvars import ContextVar, Token
from datetime import datetime
from typing import Any, AsyncIterator, Optional

from fastapi import HTTPException
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import select

from api.v1.auth.context import (
    get_current_owner_id,
    get_current_owner_is_admin,
    reset_current_owner_id,
    reset_current_owner_is_admin,
    set_current_owner_id,
    set_current_owner_is_admin,
)
from enums.async_task_status import AsyncTaskStatus
from models.api_error_model import APIErrorModel
from models.presentation_with_slides import PresentationWithSlides
from models.sql.async_task import AsyncTaskModel
from models.sql.presentation import PresentationModel
from models.sql.slide import SlideModel
from models.sse_response import SSECompleteResponse, SSEErrorResponse, SSEStatusResponse
from services.database import async_session_maker

LOGGER = logging.getLogger("presenton.prepared_deck")

ASYNC_TASK_TYPE_DECK_GENERATE = "ppt.generate_slides"
DECK_STATUS_QUEUED = "queued"
DECK_STATUS_GENERATING = "generating"
DECK_STATUS_READY = "ready"
DECK_STATUS_FAILED = "failed"
ACTIVE_DECK_STATUSES = {DECK_STATUS_QUEUED, DECK_STATUS_GENERATING}

_GENERATING_DECK_ID: ContextVar[str | None] = ContextVar(
    "prepared_deck_generating_id", default=None
)
_DECK_JOBS: dict[str, asyncio.Task] = {}
_DECK_TASK_IDS: dict[str, str] = {}
_DECK_BROADCASTS: dict[str, "DeckBroadcast"] = {}


class DeckJobCancelled(Exception):
    """The teacher cancelled this deck job, or it already finished."""


class DeckBroadcast:
    def __init__(self) -> None:
        self.history: list[str] = []
        self.subscribers: set[asyncio.Queue[str | None]] = set()

    def publish(self, payload: str) -> None:
        if not payload:
            return
        self.history.append(payload)
        if len(self.history) > 400:
            self.history = self.history[-200:]
        for queue in list(self.subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                continue

    def subscribe(self) -> asyncio.Queue[str | None]:
        queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=500)
        for item in self.history:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                break
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str | None]) -> None:
        self.subscribers.discard(queue)


def generating_this_deck(presentation_id: uuid.UUID | str) -> bool:
    return _GENERATING_DECK_ID.get() == str(presentation_id)


def deck_job_running(presentation_id: uuid.UUID | str) -> bool:
    job = _DECK_JOBS.get(str(presentation_id))
    return bool(job and not job.done())


def _broadcast_for(presentation_id: uuid.UUID | str) -> DeckBroadcast:
    key = str(presentation_id)
    existing = _DECK_BROADCASTS.get(key)
    if existing is None:
        existing = DeckBroadcast()
        _DECK_BROADCASTS[key] = existing
    return existing


def iter_sse_json_events(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in str(raw or "").split("\n\n"):
        data_lines = [
            line[5:].lstrip()
            for line in block.splitlines()
            if line.startswith("data:")
        ]
        if not data_lines:
            continue
        try:
            parsed = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            events.append(parsed)
    return events


def _is_slide_chunk(chunk: Any) -> bool:
    if isinstance(chunk, dict):
        return "id" in chunk or "index" in chunk
    if not isinstance(chunk, str):
        return False
    text = chunk.strip()
    if not text.startswith("{") or "slides" in text[:24]:
        return False
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and ("id" in parsed or "index" in parsed)


def deck_task_data(
    *,
    topic: str = "",
    stage: str = "queued",
    progress: int = 0,
    presentation_id: str | uuid.UUID | None = None,
    created_slides: int = 0,
    n_slides: int = 0,
    previous: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = dict(previous or {})
    data.update(
        {
            "topic": topic or data.get("topic") or "",
            "stage": stage,
            "progress": max(0, min(100, int(progress))),
            "created_slides": max(int(created_slides), 0),
            "n_slides": max(int(n_slides), 0),
            "remaining_slides": max(max(int(n_slides), 0) - max(int(created_slides), 0), 0),
        }
    )
    if presentation_id:
        data["presentation_id"] = str(presentation_id)
    if warnings is not None:
        data["warnings"] = [str(item) for item in warnings if str(item).strip()]
    return data


def task_progress_writable(status: AsyncTaskStatus | str | None) -> bool:
    value = str(getattr(status, "value", status) or "").lower()
    return value == AsyncTaskStatus.PENDING.value


def _generation_dict(theme: Any) -> dict[str, Any]:
    payload = dict(theme or {}) if isinstance(theme, dict) else {}
    existing = payload.get("kindergarten_generation")
    return dict(existing) if isinstance(existing, dict) else {}


def read_deck_generation(presentation: PresentationModel | None) -> dict[str, Any]:
    if presentation is None:
        return {}
    return _generation_dict(presentation.theme)


async def persist_deck_generation_state(
    presentation_id: uuid.UUID | str,
    *,
    status: str,
    progress: int,
    message: str,
    task_id: str | None = None,
    created_slides: int | None = None,
    n_slides: int | None = None,
    stage: str | None = None,
) -> None:
    presentation_id = uuid.UUID(str(presentation_id))
    async with async_session_maker() as sql_session:
        presentation = await sql_session.get(PresentationModel, presentation_id)
        if presentation is None:
            return
        theme = dict(presentation.theme or {}) if isinstance(presentation.theme, dict) else {}
        generation = _generation_dict(theme)
        generation["deck_status"] = status
        generation["deck_progress"] = max(0, min(100, int(progress)))
        generation["deck_message"] = message
        if task_id:
            generation["deck_task_id"] = task_id
        if created_slides is not None:
            generation["deck_created_slides"] = max(int(created_slides), 0)
        if n_slides is not None:
            generation["deck_n_slides"] = max(int(n_slides), 0)
        if stage:
            generation["deck_stage"] = stage
        theme["kindergarten_generation"] = generation
        presentation.theme = theme
        flag_modified(presentation, "theme")
        sql_session.add(presentation)
        await sql_session.commit()


async def _save_task(sql_session, task: AsyncTaskModel) -> None:
    task.updated_at = datetime.now()
    sql_session.add(task)
    await sql_session.commit()


async def _save_task_progress(
    task_id: str,
    *,
    message: str,
    data: dict[str, Any],
) -> None:
    async with async_session_maker() as sql_session:
        task = await sql_session.get(AsyncTaskModel, task_id)
        if task is None or not task_progress_writable(task.status):
            raise DeckJobCancelled()
        task.message = message
        task.data = data
        await _save_task(sql_session, task)


def _bind_owner(owner_id, is_admin: bool) -> tuple[Token, Token]:
    return set_current_owner_id(owner_id), set_current_owner_is_admin(is_admin)


def _schedule_worker(
    task_id: str,
    presentation_id: uuid.UUID,
    owner_id,
    is_admin: bool,
) -> asyncio.Task:
    key = str(presentation_id)
    existing = _DECK_JOBS.get(key)
    if existing and not existing.done():
        _DECK_TASK_IDS[key] = task_id
        return existing

    job = asyncio.create_task(
        _run_prepared_deck_job(task_id, presentation_id, owner_id, is_admin),
        name=f"ppt-deck-{key}",
    )
    _DECK_JOBS[key] = job
    _DECK_TASK_IDS[key] = task_id

    def _clear(done: asyncio.Task) -> None:
        current = _DECK_JOBS.get(key)
        if current is done:
            _DECK_JOBS.pop(key, None)

    job.add_done_callback(_clear)
    return job


async def ensure_prepared_deck_job(
    presentation_id: uuid.UUID,
    *,
    topic: str = "",
    n_slides: int = 0,
) -> AsyncTaskModel:
    """Start or reuse the background worker for a prepared presentation."""
    key = str(presentation_id)
    owner_id = get_current_owner_id()
    is_admin = get_current_owner_is_admin()

    async with async_session_maker() as sql_session:
        presentation = await sql_session.get(PresentationModel, presentation_id)
        if presentation is None:
            raise HTTPException(status_code=404, detail="Presentation not found")
        meta = read_deck_generation(presentation)
        parent_id = meta.get("research_task_id")
        if parent_id:
            parent = await sql_session.get(AsyncTaskModel, str(parent_id))
            if parent and (parent.data or {}).get("stage") == "cancelled":
                raise HTTPException(status_code=409, detail="教研任务已取消")
        existing_task_id = str(meta.get("deck_task_id") or _DECK_TASK_IDS.get(key) or "")
        title = topic or presentation.title or ""
        expected = n_slides or presentation.n_slides or 0
        existing_slides = list(
            await sql_session.scalars(
                select(SlideModel)
                .where(SlideModel.presentation == presentation_id)
                .order_by(SlideModel.index)
            )
        )

        if existing_task_id:
            task = await sql_session.get(AsyncTaskModel, existing_task_id)
            if task is not None:
                if deck_job_running(presentation_id) and task_progress_writable(task.status):
                    return task
                if task.status == AsyncTaskStatus.COMPLETED:
                    return task
                if task_progress_writable(task.status):
                    await persist_deck_generation_state(
                        presentation_id,
                        status=DECK_STATUS_GENERATING,
                        progress=int((task.data or {}).get("progress") or 8),
                        message=task.message or "正在生成课件…",
                        task_id=task.id,
                        created_slides=int((task.data or {}).get("created_slides") or len(existing_slides)),
                        n_slides=int((task.data or {}).get("n_slides") or expected),
                        stage="slides",
                    )
                    _schedule_worker(task.id, presentation_id, owner_id, is_admin)
                    return task

        if meta.get("deck_status") == DECK_STATUS_READY and existing_slides:
            task = AsyncTaskModel(
                type=ASYNC_TASK_TYPE_DECK_GENERATE,
                status=AsyncTaskStatus.COMPLETED,
                message="课件已生成完成",
                data=deck_task_data(
                    topic=title,
                    stage="completed",
                    progress=100,
                    presentation_id=presentation_id,
                    created_slides=len(existing_slides),
                    n_slides=expected or len(existing_slides),
                ),
            )
            sql_session.add(task)
            await sql_session.commit()
            await sql_session.refresh(task)
            return task

        task = AsyncTaskModel(
            type=ASYNC_TASK_TYPE_DECK_GENERATE,
            status=AsyncTaskStatus.PENDING,
            message="已排队，正在后台生成课件",
            data=deck_task_data(
                topic=title,
                stage="queued",
                progress=6,
                presentation_id=presentation_id,
                created_slides=len(existing_slides),
                n_slides=expected,
            ),
        )
        sql_session.add(task)
        await sql_session.commit()
        await sql_session.refresh(task)

    await persist_deck_generation_state(
        presentation_id,
        status=DECK_STATUS_QUEUED,
        progress=6,
        message=task.message or "已排队，正在后台生成课件",
        task_id=task.id,
        created_slides=0,
        n_slides=n_slides,
        stage="queued",
    )
    _schedule_worker(task.id, presentation_id, owner_id, is_admin)
    return task


async def cancel_prepared_deck_job(task_id: str) -> AsyncTaskModel:
    async with async_session_maker() as sql_session:
        task = await sql_session.get(AsyncTaskModel, task_id)
        if task is None or task.type != ASYNC_TASK_TYPE_DECK_GENERATE:
            raise HTTPException(status_code=404, detail="No async task found")
        if task.status == AsyncTaskStatus.COMPLETED:
            return task
        data = task.data if isinstance(task.data, dict) else {}
        presentation_id = data.get("presentation_id")
        task.status = AsyncTaskStatus.ERROR
        task.message = "已取消"
        task.error = APIErrorModel.from_exception(
            HTTPException(status_code=409, detail="已取消")
        ).model_dump(mode="json")
        task.data = deck_task_data(
            topic=str(data.get("topic") or ""),
            stage="cancelled",
            progress=int(data.get("progress") or 0),
            presentation_id=presentation_id,
            created_slides=int(data.get("created_slides") or 0),
            n_slides=int(data.get("n_slides") or 0),
            previous=data,
        )
        await _save_task(sql_session, task)

    if presentation_id:
        job = _DECK_JOBS.get(str(presentation_id))
        if job and not job.done():
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
        await persist_deck_generation_state(
            presentation_id,
            status=DECK_STATUS_FAILED,
            progress=int(data.get("progress") or 0),
            message="已取消",
            task_id=task_id,
            created_slides=int(data.get("created_slides") or 0),
            n_slides=int(data.get("n_slides") or 0),
            stage="cancelled",
        )
    return task


def _progress_from_events(
    events: list[dict[str, Any]],
    *,
    created: int,
    streamed: int,
    n_slides: int,
    completed: bool,
) -> tuple[int, int, bool]:
    for event in events:
        event_type = event.get("type")
        if event_type == "error":
            detail = event.get("detail") or "课件页生成失败"
            raise HTTPException(status_code=500, detail=detail)
        if event_type == "slide_assets":
            index = event.get("slide_index")
            if isinstance(index, int):
                created = max(created, index + 1)
        elif event_type == "chunk" and _is_slide_chunk(event.get("chunk")):
            streamed += 1
        if event_type == "complete":
            completed = True
    return created, streamed, completed


async def _run_prepared_deck_job(
    task_id: str,
    presentation_id: uuid.UUID,
    owner_id,
    is_admin: bool,
) -> None:
    owner_token, admin_token = _bind_owner(owner_id, is_admin)
    generating_token = _GENERATING_DECK_ID.set(str(presentation_id))
    broadcast = _broadcast_for(presentation_id)
    try:
        async with async_session_maker() as sql_session:
            task = await sql_session.get(AsyncTaskModel, task_id)
            if task is None or not task_progress_writable(task.status):
                return
            data = task.data if isinstance(task.data, dict) else {}
            topic = str(data.get("topic") or "")
            n_slides = int(data.get("n_slides") or 0)
            task.message = "正在生成课件页与配图"
            task.data = deck_task_data(
                topic=topic,
                stage="slides",
                progress=12,
                presentation_id=presentation_id,
                created_slides=int(data.get("created_slides") or 0),
                n_slides=n_slides,
                previous=data,
            )
            await _save_task(sql_session, task)

        await persist_deck_generation_state(
            presentation_id,
            status=DECK_STATUS_GENERATING,
            progress=12,
            message="正在生成课件页与配图",
            task_id=task_id,
            n_slides=n_slides,
            stage="slides",
        )

        from api.v1.ppt.endpoints.presentation import stream_presentation

        created = 0
        streamed = 0
        completed = False
        last_progress_at: datetime | None = None
        buffer = ""
        async with async_session_maker() as sql_session:
            response = await stream_presentation(presentation_id, sql_session)
            async with aclosing(response.body_iterator):
                async for chunk in response.body_iterator:
                    piece = chunk.decode("utf-8") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
                    broadcast.publish(piece)
                    buffer += piece
                    while "\n\n" in buffer:
                        frame, buffer = buffer.split("\n\n", 1)
                        events = iter_sse_json_events(frame + "\n\n")
                        created, streamed, completed = _progress_from_events(
                            events,
                            created=created,
                            streamed=streamed,
                            n_slides=n_slides,
                            completed=completed,
                        )
                        if events:
                            displayed = created if created else streamed
                            if not completed and n_slides:
                                displayed = min(displayed, max(n_slides - 1, 0))
                            progress = 12 + int(80 * max(streamed, created) / max(n_slides, 1))
                            now = datetime.now()
                            should_save = (
                                completed
                                or last_progress_at is None
                                or (now - last_progress_at).total_seconds() >= 1.5
                            )
                            if should_save:
                                last_progress_at = now
                                message = (
                                    "课件已生成完成"
                                    if completed
                                    else f"正在生成课件（{max(displayed, 1)}/{max(n_slides, displayed, 1)}）"
                                )
                                await _save_task_progress(
                                    task_id,
                                    message=message,
                                    data=deck_task_data(
                                        topic=topic,
                                        stage="completed" if completed else "slides",
                                        progress=100 if completed else min(progress, 95),
                                        presentation_id=presentation_id,
                                        created_slides=displayed,
                                        n_slides=n_slides,
                                    ),
                                )
                                await persist_deck_generation_state(
                                    presentation_id,
                                    status=DECK_STATUS_READY if completed else DECK_STATUS_GENERATING,
                                    progress=100 if completed else min(progress, 95),
                                    message=message,
                                    task_id=task_id,
                                    created_slides=displayed,
                                    n_slides=n_slides,
                                    stage="completed" if completed else "slides",
                                )
            if buffer.strip():
                events = iter_sse_json_events(buffer + "\n\n")
                created, streamed, completed = _progress_from_events(
                    events,
                    created=created,
                    streamed=streamed,
                    n_slides=n_slides,
                    completed=completed,
                )

        async with async_session_maker() as sql_session:
            task = await sql_session.get(AsyncTaskModel, task_id)
            if task is None or not task_progress_writable(task.status):
                return
            if not completed:
                raise HTTPException(status_code=500, detail="课件生成中断，页面尚未写完")
            task.status = AsyncTaskStatus.COMPLETED
            task.message = "课件已生成完成，点击查看"
            task.error = None
            task.data = deck_task_data(
                topic=topic,
                stage="completed",
                progress=100,
                presentation_id=presentation_id,
                created_slides=max(created, streamed, n_slides),
                n_slides=n_slides,
                previous=task.data if isinstance(task.data, dict) else None,
            )
            await _save_task(sql_session, task)
        await persist_deck_generation_state(
            presentation_id,
            status=DECK_STATUS_READY,
            progress=100,
            message="课件已生成完成，点击查看",
            task_id=task_id,
            created_slides=max(created, streamed, n_slides),
            n_slides=n_slides,
            stage="completed",
        )
    except DeckJobCancelled:
        LOGGER.info("[prepared_deck] cancelled presentation_id=%s task_id=%s", presentation_id, task_id)
    except asyncio.CancelledError:
        LOGGER.info("[prepared_deck] worker cancelled presentation_id=%s", presentation_id)
        raise
    except Exception as exc:
        LOGGER.exception("[prepared_deck] failed presentation_id=%s task_id=%s", presentation_id, task_id)
        detail = str(getattr(exc, "detail", None) or exc or "课件生成失败")
        try:
            async with async_session_maker() as sql_session:
                task = await sql_session.get(AsyncTaskModel, task_id)
                if task is None or not task_progress_writable(task.status):
                    return
                data = task.data if isinstance(task.data, dict) else {}
                task.status = AsyncTaskStatus.ERROR
                task.message = detail
                task.error = APIErrorModel.from_exception(
                    exc if isinstance(exc, HTTPException) else HTTPException(status_code=500, detail=detail)
                ).model_dump(mode="json")
                task.data = deck_task_data(
                    topic=str(data.get("topic") or ""),
                    stage="error",
                    progress=int(data.get("progress") or 0),
                    presentation_id=presentation_id,
                    created_slides=int(data.get("created_slides") or 0),
                    n_slides=int(data.get("n_slides") or 0),
                    previous=data,
                )
                await _save_task(sql_session, task)
            await persist_deck_generation_state(
                presentation_id,
                status=DECK_STATUS_FAILED,
                progress=int((task.data or {}).get("progress") or 0),
                message=detail,
                task_id=task_id,
                stage="error",
            )
            broadcast.publish(SSEErrorResponse(detail=detail).to_string())
        except Exception:
            LOGGER.exception("[prepared_deck] failed to persist error presentation_id=%s", presentation_id)
    finally:
        _GENERATING_DECK_ID.reset(generating_token)
        reset_current_owner_is_admin(admin_token)
        reset_current_owner_id(owner_token)
        asyncio.create_task(_expire_broadcast(str(presentation_id)))


async def _expire_broadcast(key: str) -> None:
    await asyncio.sleep(45)
    if not deck_job_running(key):
        _DECK_BROADCASTS.pop(key, None)
        _DECK_TASK_IDS.pop(key, None)


async def follow_prepared_deck_job(
    presentation_id: uuid.UUID,
    task_id: str,
) -> AsyncIterator[str]:
    """Yield live SSE from the background worker, or poll DB if joining late."""
    key = str(presentation_id)
    broadcast: Optional[DeckBroadcast] = None
    for _ in range(40):
        job = _DECK_JOBS.get(key)
        broadcast = _DECK_BROADCASTS.get(key)
        if broadcast and broadcast.history:
            break
        if job and not job.done() and broadcast:
            break
        await asyncio.sleep(0.1)
        broadcast = _DECK_BROADCASTS.get(key)
        if broadcast:
            break

    if broadcast is not None:
        queue = broadcast.subscribe()
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=2.5)
                except asyncio.TimeoutError:
                    async with async_session_maker() as sql_session:
                        task = await sql_session.get(AsyncTaskModel, task_id)
                    if task is None:
                        yield SSEErrorResponse(detail="生成任务已失效").to_string()
                        return
                    if task.status == AsyncTaskStatus.COMPLETED:
                        async for payload in _complete_from_db(presentation_id):
                            yield payload
                        return
                    if task.status == AsyncTaskStatus.ERROR:
                        yield SSEErrorResponse(
                            detail=task.message or "课件生成失败"
                        ).to_string()
                        return
                    yield SSEStatusResponse(
                        status=task.message or "正在后台生成课件…"
                    ).to_string()
                    continue
                if item:
                    yield item
                    events = iter_sse_json_events(item)
                    if any(event.get("type") in {"complete", "error"} for event in events):
                        return
        finally:
            broadcast.unsubscribe(queue)
        return

    async for payload in _poll_prepared_deck_job(presentation_id, task_id):
        yield payload


async def _complete_from_db(presentation_id: uuid.UUID) -> AsyncIterator[str]:
    from api.v1.ppt.endpoints.presentation import _presentation_response_data

    async with async_session_maker() as sql_session:
        presentation = await sql_session.get(PresentationModel, presentation_id)
        slides = list(
            await sql_session.scalars(
                select(SlideModel)
                .where(SlideModel.presentation == presentation_id)
                .order_by(SlideModel.index)
            )
        )
        if presentation is None:
            yield SSEErrorResponse(detail="课件不存在").to_string()
            return
        response = PresentationWithSlides(
            **_presentation_response_data(presentation),
            slides=slides,
        )
        yield SSECompleteResponse(
            key="presentation",
            value=response.model_dump(mode="json"),
        ).to_string()


async def _poll_prepared_deck_job(
    presentation_id: uuid.UUID,
    task_id: str,
) -> AsyncIterator[str]:
    from api.v1.ppt.endpoints.presentation import _presentation_response_data

    last_count = -1
    last_message = ""
    while True:
        async with async_session_maker() as sql_session:
            task = await sql_session.get(AsyncTaskModel, task_id)
            presentation = await sql_session.get(PresentationModel, presentation_id)
            slides = list(
                await sql_session.scalars(
                    select(SlideModel)
                    .where(SlideModel.presentation == presentation_id)
                    .order_by(SlideModel.index)
                )
            )
        if task is None:
            yield SSEErrorResponse(detail="生成任务已失效").to_string()
            return
        message = task.message or "正在后台生成课件…"
        if message != last_message:
            yield SSEStatusResponse(status=message).to_string()
            last_message = message
        if len(slides) != last_count:
            for slide in slides:
                yield (
                    f"event: response\ndata: {json.dumps({'type': 'slide_assets', 'slide_index': slide.index, 'slide': slide.model_dump(mode='json'), 'warnings': []})}\n\n"
                )
            last_count = len(slides)
        if task.status == AsyncTaskStatus.COMPLETED:
            if presentation is not None:
                response = PresentationWithSlides(
                    **_presentation_response_data(presentation),
                    slides=slides,
                )
                yield SSECompleteResponse(
                    key="presentation",
                    value=response.model_dump(mode="json"),
                ).to_string()
            return
        if task.status == AsyncTaskStatus.ERROR:
            yield SSEErrorResponse(detail=task.message or "课件生成失败").to_string()
            return
        await asyncio.sleep(1.2)
