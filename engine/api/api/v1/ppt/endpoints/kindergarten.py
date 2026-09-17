from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.v1.auth.context import (
    get_current_owner_id,
    get_current_owner_is_admin,
    reset_current_owner_id,
    reset_current_owner_is_admin,
    set_current_owner_id,
    set_current_owner_is_admin,
)
from api.v1.ppt.endpoints.presentation import (
    create_presentation,
    prepare_presentation,
    stream_presentation,
)
from enums.async_task_status import AsyncTaskStatus
from models.api_error_model import APIErrorModel
from models.sql.async_task import AsyncTaskModel
from models.sql.slide import SlideModel
from enums.tone import Tone
from enums.verbosity import Verbosity
from models.image_policy import ImagePolicy
from models.kindergarten_lesson_plan import (
    KindergartenDomain,
    KindergartenLessonPlan,
)
from models.presentation_outline_model import PresentationOutlineModel
from models.sse_response import (
    SSECompleteResponse,
    SSEErrorResponse,
    SSEResponse,
    SSEStatusResponse,
)
from models.sql.presentation import PresentationModel
from models.sql.template_v2 import TemplateV2
from services.database import async_session_maker, get_async_session
from services.documents_loader import DocumentsLoader
from services.kindergarten_presentation_planning_service import (
    KindergartenPlanningQualityError,
    ValidatedKindergartenPlanningResult,
    _outline_for_audience,
    generate_validated_kindergarten_presentation_outline,
)
from services.kindergarten_plan_quality_service import (
    KindergartenPlanQualityReport,
    validate_kindergarten_lesson_plan,
)
from services.kindergarten_planner_runtime import (
    get_kindergarten_planner_runtime,
)
from services.kindergarten_lesson_planning_service import (
    resolve_kindergarten_slide_count,
)
from services.kindergarten_template_routing_service import (
    AUTO_TEMPLATE_NAME,
    KindergartenTemplateRoutingDecision,
    resolve_kindergarten_template,
)
from services.kindergarten_visual_planning_service import (
    AI_BACKGROUND_TEMPLATE_NAME,
    KindergartenVisualMode,
    apply_ai_background_visual_plan,
    get_kindergarten_visual_style_summary,
)
from services.research_ppt_generation_context import (
    ResearchPptImageOptions,
    looks_like_english_teaching_request,
    research_ppt_image_options,
)
from services.mem0_presentation_memory_service import (
    MEM0_PRESENTATION_MEMORY_SERVICE,
)
from services.owner_scope import get_by_id_unscoped
from templates.ai_visual_production import build_production_ai_visual_template
from utils.sse import safe_sse_stream
from utils.outline_utils import get_saved_outline_failure


KINDERGARTEN_ROUTER = APIRouter(prefix="/kindergarten", tags=["Kindergarten"])
MAX_KINDERGARTEN_SOURCE_CONTEXT_CHARS = 30000
LOGGER = logging.getLogger(__name__)
KindergartenContentMode = Literal["classroom", "training"]
ASYNC_TASK_TYPE_KINDERGARTEN_COMPLETE = "kindergarten.generate_complete"


class _AlwaysConnectedRequest:
    async def is_disconnected(self) -> bool:
        return False


class KindergartenLessonPlanRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    age_group: str = Field(default="4-5岁", min_length=1, max_length=40)
    domain: KindergartenDomain = "comprehensive"
    content_mode: KindergartenContentMode = "classroom"
    duration_minutes: int = Field(default=20, ge=5, le=90)
    n_slides: Optional[int] = Field(default=None, ge=3, le=40)
    # PresentationModel currently stores instructions in VARCHAR(1024). Keep this
    # endpoint inside that persistence contract instead of accepting data that can
    # plan successfully but fail when the prepared deck is saved.
    instructions: Optional[str] = Field(default=None, max_length=1000)
    source_context: Optional[str] = Field(default=None, max_length=30000)


class KindergartenLessonPlanResponse(BaseModel):
    plan: KindergartenLessonPlan
    outline: PresentationOutlineModel
    quality: KindergartenPlanQualityReport
    planning_attempts: int = 1


class KindergartenPresentationCreateRequest(KindergartenLessonPlanRequest):
    # `auto` is resolved only after the reviewed lesson plan exists, so routing can
    # use domain + actual slide semantics rather than guessing from the raw title.
    # Sending a concrete template id/name still preserves manual selection exactly.
    template: str = Field(default=AUTO_TEMPLATE_NAME, min_length=1, max_length=200)
    visual_mode: KindergartenVisualMode = "template"
    visual_style: Optional[str] = Field(default=None, max_length=160)
    language: str = Field(default="Chinese", min_length=1, max_length=80)
    image_policy: ImagePolicy = ImagePolicy.STANDARD
    file_paths: list[str] = Field(default_factory=list, max_length=20)
    tone: Tone = Tone.EDUCATIONAL
    verbosity: Verbosity = Verbosity.STANDARD


class KindergartenPresentationPrepareRequest(KindergartenPresentationCreateRequest):
    pass


class KindergartenPresentationCreateResponse(KindergartenLessonPlanResponse):
    presentation_id: uuid.UUID
    outline_path: str
    selected_template: str
    template_selection_reason: str
    template_scores: dict[str, int] = Field(default_factory=dict)
    visual_mode: KindergartenVisualMode = "template"
    visual_style_summary: Optional[str] = None


class KindergartenPresentationPrepareResponse(KindergartenPresentationCreateResponse):
    stream_path: str


class KindergartenPresentationStartResponse(BaseModel):
    presentation_id: uuid.UUID
    outline_path: str
    outline_stream_path: str
    n_slides: int
    visual_mode: KindergartenVisualMode


class KindergartenPlannerRuntimeResponse(BaseModel):
    profile: str
    model: str
    source: str
    max_tokens: int
    call_timeout_seconds: float
    total_timeout_seconds: float
    stream: bool


async def _planning_source_context(
    payload: KindergartenLessonPlanRequest,
) -> Optional[str]:
    source_parts: list[str] = []
    if payload.source_context and payload.source_context.strip():
        source_parts.append(payload.source_context.strip())

    file_paths = getattr(payload, "file_paths", None)
    if isinstance(file_paths, list) and file_paths:
        language = getattr(payload, "language", None)
        documents_loader = DocumentsLoader(
            file_paths=file_paths,
            presentation_language=language,
        )
        await documents_loader.load_documents()
        source_parts.extend(
            document.strip()
            for document in documents_loader.documents
            if isinstance(document, str) and document.strip()
        )

    if not source_parts:
        return None
    # The planner prompt should remain bounded even when several source documents
    # were uploaded. The full original files still stay attached to PresentationModel
    # for later inspection/generation; this is only the planning context window.
    return "\n\n".join(source_parts)[:MAX_KINDERGARTEN_SOURCE_CONTEXT_CHARS]


async def _generate_validated_plan(
    payload: KindergartenLessonPlanRequest,
    request: Request,
    *,
    text_chunk_callback=None,
    stop_on_disconnect: bool = True,
) -> ValidatedKindergartenPlanningResult:
    runtime = get_kindergarten_planner_runtime()
    try:
        async with asyncio.timeout(runtime.total_timeout_seconds):
            return await generate_validated_kindergarten_presentation_outline(
                topic=payload.topic,
                age_group=payload.age_group,
                domain=payload.domain,
                content_mode=payload.content_mode,
                duration_minutes=payload.duration_minutes,
                n_slides=payload.n_slides,
                instructions=payload.instructions,
                source_context=await _planning_source_context(payload),
                disconnect_checker=(
                    request.is_disconnected if stop_on_disconnect else None
                ),
                text_chunk_callback=text_chunk_callback,
            )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Kindergarten planner {runtime.model} exceeded the complete "
                f"{runtime.total_timeout_seconds:g}-second outline deadline"
            ),
        ) from exc


def _quality_failure_http(exc: KindergartenPlanningQualityError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "KINDERGARTEN_PLAN_QUALITY_FAILED",
            "message": "幼教课堂规划经过自动修复后仍未通过硬性质量校验",
            "planning_attempts": exc.attempts,
            "quality": exc.report.model_dump(mode="json"),
        },
    )


def reviewable_result_from_quality_error(
    exc: KindergartenPlanningQualityError,
    content_mode: str,
) -> ValidatedKindergartenPlanningResult | None:
    """Keep a streamed outline when pages exist, instead of wiping the review UI."""
    if exc.plan is None or len(exc.plan.slides) < 3:
        return None
    return ValidatedKindergartenPlanningResult(
        plan=exc.plan,
        outline=_outline_for_audience(exc.plan, content_mode),
        quality=exc.report,
        attempts=exc.attempts,
    )


QUALITY_REVIEW_WARNING = "大纲已保存，部分硬性校验未通过，请核对后再生成课件"


def _quality_review_warning(
    result: ValidatedKindergartenPlanningResult,
) -> Optional[str]:
    if result.quality.passed:
        return None
    details = "；".join(
        (f"第 {issue.slide_no} 页：" if issue.slide_no else "") + issue.message
        for issue in result.quality.errors
    )
    return QUALITY_REVIEW_WARNING + ("。" + details if details else "")


def _require_automatic_quality(result, presentation_id):
    if result.quality.passed:
        return
    raise HTTPException(status_code=422, detail={
        "code": "KINDERGARTEN_PLAN_REVIEW_REQUIRED",
        "message": _quality_review_warning(result),
        "presentation_id": str(presentation_id),
        "outline_path": f"/presentations/{presentation_id}/outline",
        "quality": result.quality.model_dump(mode="json"),
    })


async def _generate_reviewable_plan(
    payload: KindergartenLessonPlanRequest,
    request: Request,
    *,
    text_chunk_callback=None,
    stop_on_disconnect: bool = True,
) -> ValidatedKindergartenPlanningResult:
    """Return a usable plan when hard quality still fails after local repair."""
    try:
        return await _generate_validated_plan(
            payload,
            request,
            text_chunk_callback=text_chunk_callback,
            stop_on_disconnect=stop_on_disconnect,
        )
    except KindergartenPlanningQualityError as exc:
        reviewable = reviewable_result_from_quality_error(
            exc,
            payload.content_mode,
        )
        if reviewable is None:
            raise _quality_failure_http(exc) from exc
        LOGGER.warning(
            "[kindergarten.plan] keeping reviewable outline after quality gate: %s",
            exc,
        )
        return reviewable


def _layout_count(template: TemplateV2) -> int:
    if not isinstance(template.layouts, dict):
        return 0
    layouts = template.layouts.get("layouts")
    return len(layouts) if isinstance(layouts, list) else 0


async def _ensure_ai_visual_template(sql_session: AsyncSession) -> None:
    """Install or upgrade the internal neutral skeleton used by AI free visual."""
    production = build_production_ai_visual_template()
    existing = await get_by_id_unscoped(
        sql_session, TemplateV2, AI_BACKGROUND_TEMPLATE_NAME
    )
    if existing is None:
        sql_session.add(production)
        await sql_session.commit()
        return

    if _layout_count(existing) >= _layout_count(production):
        return

    # This template is an internal product contract, not user-authored content.
    # Upgrade stale copies so deployments that tried an earlier six-layout build
    # automatically receive the production eight-layout skeleton.
    existing.name = production.name
    existing.description = production.description
    existing.raw_layouts = production.raw_layouts
    existing.components = production.components
    existing.merged_components = production.merged_components
    existing.layouts = production.layouts
    existing.assets = production.assets
    existing.is_default = True
    sql_session.add(existing)
    await sql_session.commit()


async def _available_auto_templates(payload, sql_session):
    if not _uses_template_routing(payload) or (payload.template or "auto").strip().casefold() != "auto":
        return None
    rows = await sql_session.scalars(select(TemplateV2).where(TemplateV2.is_default.is_(True)))
    pool = {template.id: template for template in rows}
    if payload.content_mode == "training" and not any(
        key in pool for key in ("training-case", "training-action", "teacher-training", "training-workshop")
    ):
        return None
    return pool


def _uses_template_routing(payload: KindergartenPresentationCreateRequest) -> bool:
    # Teacher-training decks keep reviewed copy. The AI-background skeleton is
    # sized for short classroom captions and will reject dense 教研正文.
    return payload.visual_mode == "template" or payload.content_mode == "training"


def _uses_ai_background(payload: KindergartenPresentationCreateRequest) -> bool:
    return payload.visual_mode == "ai-background" and payload.content_mode != "training"


def _apply_visual_mode(
    payload: KindergartenPresentationCreateRequest,
    result: ValidatedKindergartenPlanningResult,
    *,
    available_templates: dict | None = None,
) -> tuple[
    ValidatedKindergartenPlanningResult,
    KindergartenTemplateRoutingDecision,
    Optional[str],
]:
    if _uses_template_routing(payload):
        routing = resolve_kindergarten_template(
            result.plan,
            payload.template,
            instructions=payload.instructions,
            allow_classroom=payload.image_policy != ImagePolicy.DISABLED,
            content_mode=payload.content_mode,
            topic=payload.topic,
            available_templates=available_templates,
        )
        return result, routing, None

    if payload.image_policy != ImagePolicy.STANDARD:
        raise HTTPException(
            status_code=400,
            detail=(
                "AI 自由视觉需要 image_policy=standard，"
                "因为每页都必须生成一张可校验的 16:9 背景图。"
            ),
        )

    visual_outline = apply_ai_background_visual_plan(
        result.outline,
        topic=payload.topic,
        domain=payload.domain,
        visual_style_hint=payload.visual_style,
        content_mode=payload.content_mode,
    )
    visual_result = ValidatedKindergartenPlanningResult(
        plan=result.plan,
        outline=visual_outline,
        quality=result.quality,
        attempts=result.attempts,
    )
    routing = KindergartenTemplateRoutingDecision(
        template=AI_BACKGROUND_TEMPLATE_NAME,
        reason="visual-mode:ai-background;neutral-skeleton+generated-backgrounds",
        scores={AI_BACKGROUND_TEMPLATE_NAME: 100},
    )
    style_summary = get_kindergarten_visual_style_summary(
        domain=payload.domain,
        visual_style_hint=payload.visual_style,
        content_mode=payload.content_mode,
    )
    return visual_result, routing, style_summary


async def _create_reviewable_presentation(
    payload: KindergartenPresentationCreateRequest,
    result: ValidatedKindergartenPlanningResult,
    sql_session: AsyncSession,
):
    presentation = await create_presentation(
        content=payload.topic,
        n_slides=len(result.outline.slides),
        language=payload.language,
        file_paths=payload.file_paths or None,
        tone=payload.tone,
        verbosity=payload.verbosity,
        instructions=payload.instructions,
        include_table_of_contents=False,
        include_title_slide=True,
        web_search=False,
        generation_mode="standard",
        community_design_ids=None,
        image_policy=payload.image_policy,
        sql_session=sql_session,
    )
    presentation.outlines = result.outline.model_dump(mode="json")
    presentation.n_slides = len(result.outline.slides)
    presentation.title = payload.topic
    sql_session.add(presentation)
    await sql_session.commit()
    await sql_session.refresh(presentation)

    await MEM0_PRESENTATION_MEMORY_SERVICE.store_generated_outlines(
        presentation.id,
        presentation.outlines,
    )
    return presentation


async def _persist_kindergarten_generation_metadata(
    presentation,
    *,
    payload: KindergartenPresentationCreateRequest,
    routing: KindergartenTemplateRoutingDecision,
    visual_style_summary: Optional[str],
    sql_session: AsyncSession,
    quality_warning: Optional[str] = None,
) -> None:
    """Persist routing so a saved outline can be resumed without URL-only state."""
    theme = dict(presentation.theme or {})
    existing = theme.get("kindergarten_generation")
    generation = dict(existing) if isinstance(existing, dict) else {}
    generation.update({
        "version": 1,
        "age_group": payload.age_group,
        "domain": payload.domain,
        "content_mode": payload.content_mode,
        "duration_minutes": payload.duration_minutes,
        "visual_mode": payload.visual_mode,
        "visual_style": payload.visual_style,
        "visual_style_summary": visual_style_summary,
        "selected_template": routing.template,
        "template_selection_reason": routing.reason,
        "template_scores": routing.scores,
        "outline_status": "ready",
    })
    generation.pop("outline_error", None)
    if quality_warning:
        generation["quality_warning"] = quality_warning
    else:
        generation.pop("quality_warning", None)
    theme["kindergarten_generation"] = generation
    presentation.theme = theme
    sql_session.add(presentation)
    await sql_session.commit()


def _routing_response_fields(routing) -> dict:
    return {
        "selected_template": routing.template,
        "template_selection_reason": routing.reason,
        "template_scores": routing.scores,
    }


def _start_request_metadata(
    payload: KindergartenPresentationCreateRequest,
    resolved_n_slides: int,
) -> dict:
    request_payload = payload.model_dump(mode="json")
    request_payload["n_slides"] = resolved_n_slides
    return {
        "version": 1,
        "outline_status": "pending",
        "requested_template": payload.template,
        "selected_template": None,
        "visual_mode": payload.visual_mode,
        "request": request_payload,
    }


async def _persist_start_metadata(
    presentation,
    payload: KindergartenPresentationCreateRequest,
    resolved_n_slides: int,
    sql_session: AsyncSession,
) -> None:
    theme = dict(presentation.theme or {})
    theme["kindergarten_generation"] = _start_request_metadata(
        payload,
        resolved_n_slides,
    )
    presentation.theme = theme
    sql_session.add(presentation)
    await sql_session.commit()


async def _persist_outline_failure(
    presentation,
    detail: str,
    sql_session: AsyncSession,
) -> None:
    """Mark incomplete records so the project list can identify failed generation."""
    await sql_session.rollback()
    # Rollback expires ORM attributes even with expire_on_commit=False. Reload
    # explicitly so reading theme does not trigger synchronous IO in async code.
    await sql_session.refresh(presentation)
    theme = dict(presentation.theme or {})
    existing = theme.get("kindergarten_generation")
    generation = dict(existing) if isinstance(existing, dict) else {}
    generation.update(
        {
            "outline_status": "failed",
            "outline_error": detail[:500],
        }
    )
    theme["kindergarten_generation"] = generation
    presentation.theme = theme
    sql_session.add(presentation)
    await sql_session.commit()


def _stream_presentation_payload(presentation) -> dict:
    return {
        **presentation.model_dump(exclude={"layout", "structure", "theme"}, mode="json"),
        "slides": [],
        "generation_metadata": (presentation.theme or {}).get(
            "kindergarten_generation"
        ),
    }


@KINDERGARTEN_ROUTER.get(
    "/planner/runtime",
    response_model=KindergartenPlannerRuntimeResponse,
)
async def kindergarten_planner_runtime():
    """Expose non-secret planner routing so deployments can verify it cheaply."""
    runtime = get_kindergarten_planner_runtime()
    return KindergartenPlannerRuntimeResponse(
        profile=runtime.profile,
        model=runtime.model,
        source=runtime.source,
        max_tokens=runtime.max_tokens,
        call_timeout_seconds=runtime.timeout_seconds,
        total_timeout_seconds=runtime.total_timeout_seconds,
        stream=runtime.stream,
    )


@KINDERGARTEN_ROUTER.post(
    "/lesson-plan",
    response_model=KindergartenLessonPlanResponse,
)
async def create_kindergarten_lesson_plan(
    payload: KindergartenLessonPlanRequest,
    request: Request,
):
    result = await _generate_reviewable_plan(payload, request)
    return KindergartenLessonPlanResponse(
        plan=result.plan,
        outline=result.outline,
        quality=result.quality,
        planning_attempts=result.attempts,
    )


@KINDERGARTEN_ROUTER.post(
    "/presentation/create",
    response_model=KindergartenPresentationCreateResponse,
)
async def create_kindergarten_presentation(
    payload: KindergartenPresentationCreateRequest,
    request: Request,
    sql_session: AsyncSession = Depends(get_async_session),
):
    """Create a reviewed-outline checkpoint without starting slide generation.

    The normal mode routes to a stable kindergarten template. AI-background mode
    keeps only a neutral layout skeleton, injects a shared art direction plus one
    page-specific full-canvas background contract per slide, and defers paid image
    generation until after the teacher reviews the outline.
    """
    result = await _generate_reviewable_plan(payload, request)
    result, routing, style_summary = _apply_visual_mode(
        payload, result, available_templates=await _available_auto_templates(payload, sql_session),
    )
    if _uses_ai_background(payload):
        await _ensure_ai_visual_template(sql_session)

    presentation = await _create_reviewable_presentation(payload, result, sql_session)
    await _persist_kindergarten_generation_metadata(
        presentation,
        payload=payload,
        routing=routing,
        visual_style_summary=style_summary,
        sql_session=sql_session,
        quality_warning=_quality_review_warning(result),
    )
    return KindergartenPresentationCreateResponse(
        presentation_id=presentation.id,
        outline_path=f"/presentations/{presentation.id}/outline",
        plan=result.plan,
        outline=result.outline,
        quality=result.quality,
        planning_attempts=result.attempts,
        visual_mode=payload.visual_mode,
        visual_style_summary=style_summary,
        **_routing_response_fields(routing),
    )


@KINDERGARTEN_ROUTER.post(
    "/presentation/start",
    response_model=KindergartenPresentationStartResponse,
)
async def start_kindergarten_presentation(
    payload: KindergartenPresentationCreateRequest,
    sql_session: AsyncSession = Depends(get_async_session),
):
    """Persist the project immediately so the browser can stream its outline.

    Planning no longer blocks navigation on the editor upload screen. The
    stream endpoint below owns the paid model call and writes the validated
    result back into this durable checkpoint.
    """
    resolved_n_slides = resolve_kindergarten_slide_count(
        payload.n_slides,
        payload.duration_minutes,
    )
    start_payload = payload.model_copy(update={"n_slides": resolved_n_slides})
    presentation = await create_presentation(
        content=start_payload.topic,
        n_slides=resolved_n_slides,
        language=start_payload.language,
        file_paths=start_payload.file_paths or None,
        tone=start_payload.tone,
        verbosity=start_payload.verbosity,
        instructions=start_payload.instructions,
        include_table_of_contents=False,
        include_title_slide=True,
        web_search=False,
        generation_mode="standard",
        community_design_ids=None,
        image_policy=start_payload.image_policy,
        sql_session=sql_session,
    )
    presentation.title = start_payload.topic
    await _persist_start_metadata(
        presentation,
        start_payload,
        resolved_n_slides,
        sql_session,
    )
    return KindergartenPresentationStartResponse(
        presentation_id=presentation.id,
        outline_path=f"/presentations/{presentation.id}/outline",
        outline_stream_path=(
            f"/api/v1/ppt/kindergarten/presentation/outline/stream/{presentation.id}"
        ),
        n_slides=resolved_n_slides,
        visual_mode=start_payload.visual_mode,
    )


@KINDERGARTEN_ROUTER.get("/presentation/outline/stream/{presentation_id}")
async def stream_kindergarten_presentation_outline(
    presentation_id: uuid.UUID,
    request: Request,
    sql_session: AsyncSession = Depends(get_async_session),
):
    presentation = await get_by_id_unscoped(
        sql_session,
        PresentationModel,
        presentation_id,
    )
    if presentation is None:
        raise HTTPException(status_code=404, detail="Presentation not found")

    failure = get_saved_outline_failure(presentation.theme)
    if not presentation.outlines and failure:
        raise HTTPException(status_code=409, detail=failure)

    async def inner():
        if presentation.outlines:
            yield SSEStatusResponse(status="Loading saved kindergarten outline").to_string()
            yield SSEResponse(
                event="response",
                data=json.dumps(
                    {
                        "type": "outline",
                        "outline": presentation.outlines,
                    },
                    ensure_ascii=False,
                ),
            ).to_string()
            yield SSECompleteResponse(
                key="presentation",
                value=_stream_presentation_payload(presentation),
            ).to_string()
            return

        generation = (presentation.theme or {}).get("kindergarten_generation")
        raw_payload = generation.get("request") if isinstance(generation, dict) else None
        if not isinstance(raw_payload, dict):
            yield SSEErrorResponse(
                detail="幼教大纲生成参数已丢失，请返回首页重新创建。"
            ).to_string()
            return

        try:
            payload = KindergartenPresentationCreateRequest.model_validate(raw_payload)
        except Exception:
            yield SSEErrorResponse(
                detail="幼教大纲生成参数无效，请返回首页重新创建。"
            ).to_string()
            return

        yield SSEStatusResponse(
            status=(
                "正在生成教研培训大纲"
                if payload.content_mode == "training"
                else "正在生成幼教课堂大纲"
            )
        ).to_string()
        chunk_queue: asyncio.Queue[str] = asyncio.Queue()

        async def on_chunk(chunk: str) -> None:
            await chunk_queue.put(chunk)

        planning_task = asyncio.create_task(
            _generate_reviewable_plan(
                payload,
                request,
                text_chunk_callback=on_chunk,
                stop_on_disconnect=False,
            )
        )
        disconnected = False
        try:
            while not planning_task.done() or not chunk_queue.empty():
                try:
                    chunk = await asyncio.wait_for(chunk_queue.get(), timeout=1)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        # Nginx/proxy idle timeouts look like a client drop.
                        # Keep generating so a refresh can load the saved outline
                        # instead of leaving a failed shell.
                        disconnected = True
                        LOGGER.warning(
                            "[kindergarten.outline] client disconnected; "
                            "continuing generation presentation_id=%s",
                            presentation.id,
                        )
                        break
                    continue
                yield SSEResponse(
                    event="response",
                    data=json.dumps(
                        {"type": "kindergarten_chunk", "chunk": chunk},
                        ensure_ascii=False,
                    ),
                ).to_string()
            result = await planning_task
            quality_warning = _quality_review_warning(result)
            if not disconnected:
                yield SSEStatusResponse(
                    status=quality_warning or "正在校验并保存大纲"
                ).to_string()
            result, routing, style_summary = _apply_visual_mode(
                payload, result, available_templates=await _available_auto_templates(payload, sql_session),
            )
            if _uses_ai_background(payload):
                await _ensure_ai_visual_template(sql_session)

            presentation.outlines = result.outline.model_dump(mode="json")
            presentation.n_slides = len(result.outline.slides)
            presentation.title = payload.topic
            sql_session.add(presentation)
            await sql_session.commit()
            await _persist_kindergarten_generation_metadata(
                presentation,
                payload=payload,
                routing=routing,
                visual_style_summary=style_summary,
                sql_session=sql_session,
                quality_warning=quality_warning,
            )
            await MEM0_PRESENTATION_MEMORY_SERVICE.store_generated_outlines(
                presentation.id,
                presentation.outlines,
            )
            if disconnected:
                return
            yield SSEResponse(
                event="response",
                data=json.dumps(
                    {"type": "outline", "outline": presentation.outlines},
                    ensure_ascii=False,
                ),
            ).to_string()
            yield SSECompleteResponse(
                key="presentation",
                value=_stream_presentation_payload(presentation),
            ).to_string()
        except HTTPException as exc:
            detail = exc.detail
            if not isinstance(detail, str):
                detail = (
                    detail.get("message")
                    if isinstance(detail, dict)
                    else None
                ) or json.dumps(detail, ensure_ascii=False)
            await _persist_outline_failure(presentation, detail, sql_session)
            yield SSEErrorResponse(detail=detail).to_string()
        except KindergartenPlanningQualityError as exc:
            detail = f"幼教课堂大纲质检失败：{exc}"
            await _persist_outline_failure(presentation, detail, sql_session)
            yield SSEErrorResponse(detail=detail).to_string()
        except Exception as exc:
            await _persist_outline_failure(
                presentation,
                "幼教大纲生成失败，请重试。",
                sql_session,
            )
            raise
        finally:
            if not planning_task.done():
                planning_task.cancel()
                await asyncio.gather(planning_task, return_exceptions=True)

    return StreamingResponse(
        safe_sse_stream(
            inner(),
            logger=LOGGER,
            error_detail="幼教大纲生成失败，请重试。",
            on_error=sql_session.rollback,
        ),
        media_type="text/event-stream",
    )

@KINDERGARTEN_ROUTER.post(
    "/presentation/prepare",
    response_model=KindergartenPresentationPrepareResponse,
)
async def prepare_kindergarten_presentation(
    payload: KindergartenPresentationPrepareRequest,
    request: Request,
    sql_session: AsyncSession = Depends(get_async_session),
):
    """One-shot plan + route + prepare endpoint for API clients without review UI."""
    result = await _generate_reviewable_plan(payload, request)
    result, routing, style_summary = _apply_visual_mode(
        payload, result, available_templates=await _available_auto_templates(payload, sql_session),
    )
    if _uses_ai_background(payload):
        await _ensure_ai_visual_template(sql_session)

    presentation = await _create_reviewable_presentation(payload, result, sql_session)
    await _persist_kindergarten_generation_metadata(
        presentation,
        payload=payload,
        routing=routing,
        visual_style_summary=style_summary,
        sql_session=sql_session,
        quality_warning=_quality_review_warning(result),
    )
    # The automatic path has no teacher review step. Save the paid outline and
    # stop before page/image generation if the teaching contract is invalid.
    _require_automatic_quality(result, presentation.id)
    try:
        prepared = await prepare_presentation(
            presentation_id=presentation.id,
            outlines=result.outline.slides,
            layout=routing.template,
            title=payload.topic,
            sql_session=sql_session,
        )
    except Exception:
        # The one-shot endpoint should not leave an empty/prepared shell on failure.
        # The reviewable create endpoint intentionally persists its checkpoint.
        await sql_session.delete(presentation)
        await sql_session.commit()
        raise

    presentation_id = prepared.presentation_id
    return KindergartenPresentationPrepareResponse(
        presentation_id=presentation_id,
        outline_path=f"/presentations/{presentation_id}/outline",
        stream_path=f"/api/v1/ppt/presentation/stream/{presentation_id}",
        plan=result.plan,
        outline=result.outline,
        quality=result.quality,
        planning_attempts=result.attempts,
        visual_mode=payload.visual_mode,
        visual_style_summary=style_summary,
        **_routing_response_fields(routing),
    )


def kindergarten_complete_task_data(
    *,
    topic: str = "",
    stage: str = "queued",
    progress: int = 0,
    presentation_id: str | uuid.UUID | None = None,
    created_slides: int = 0,
    n_slides: int = 0,
    previous: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    missing_image_pages: list[int] | None = None,
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
        data["has_warnings"] = bool(data["warnings"])
    if missing_image_pages is not None:
        data["missing_image_pages"] = sorted(set(int(page) for page in missing_image_pages))
    return data


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


def _exception_detail(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail or "")
    return str(exc or "")


def is_retryable_complete_generation_error(exc: Exception) -> bool:
    text = _exception_detail(exc)
    lowered = text.lower()
    if any(
        marker in lowered
        for marker in (
            "does not fit any compatible layout",
            "roomier template",
            "大字号",
            "无法完整容纳",
            "template not found",
            "outlines can not be empty",
            "invalid generated data",
        )
    ):
        return False
    return any(
        marker in lowered
        for marker in (
            "ai provider",
            "please try again",
            "failed to generate presentation",
            "llm api error",
            "课件生成中断",
            "没有可见正文",
            "尚未写完",
            "只生成了",
        )
    )


def friendly_complete_generation_detail(detail: str) -> str:
    text = str(detail or "").strip()
    lowered = text.lower()
    if any(
        marker in lowered
        for marker in (
            "ai provider",
            "please try again",
            "failed to generate presentation",
            "llm api error",
            "the ai provider returned an error",
        )
    ):
        return "课件生成服务暂时失败，请重新生成"
    return text or "教研 PPT 生成失败"


class CompleteTaskCancelled(Exception):
    """Stop the worker because the task was cancelled or already finished."""


def complete_task_progress_writable(status: AsyncTaskStatus | str | None) -> bool:
    value = str(getattr(status, "value", status) or "").lower()
    return value == AsyncTaskStatus.PENDING.value


async def _save_complete_task(sql_session: AsyncSession, task: AsyncTaskModel) -> None:
    task.updated_at = datetime.now()
    sql_session.add(task)
    await sql_session.commit()


async def _save_complete_task_by_id(
    task_id: str,
    *,
    message: str,
    data: dict[str, Any],
) -> None:
    """Progress updates must not share the slide-generation session.

    Committing that session mid-stream can persist an empty deck, then the
    generator still emits `complete` after a later rollback miss.
    """
    async with async_session_maker() as sql_session:
        task = await sql_session.get(AsyncTaskModel, task_id)
        if task is None or not complete_task_progress_writable(task.status):
            raise CompleteTaskCancelled()
        task.message = message
        task.data = data
        await _save_complete_task(sql_session, task)


def _collect_ui_text(node: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "text" and node.get("decorative") is not True:
            for run in node.get("runs") or []:
                if isinstance(run, dict):
                    value = str(run.get("text") or "").strip()
                    if value:
                        texts.append(value)
        for child in node.values():
            texts.extend(_collect_ui_text(child))
    elif isinstance(node, list):
        for child in node:
            texts.extend(_collect_ui_text(child))
    return texts


def slide_has_visible_content(slide) -> bool:
    placeholders = {"title", "text", "cue", "point", "heading"}
    return any(
        value not in placeholders and len(value) > 1
        for value in _collect_ui_text(getattr(slide, "ui", None))
    )


async def _clear_incomplete_slides(
    sql_session: AsyncSession,
    presentation_id: uuid.UUID,
) -> None:
    try:
        await sql_session.rollback()
    except Exception:
        pass
    await sql_session.execute(
        delete(SlideModel).where(SlideModel.presentation == presentation_id)
    )
    await sql_session.commit()


async def _inspect_persisted_visible_slides(
    sql_session: AsyncSession,
    presentation_id: uuid.UUID,
    expected_slides: int,
) -> dict[str, Any]:
    """Return a usable-deck report; missing images are warnings, not fatal."""
    await sql_session.commit()
    sql_session.expire_all()
    rows = list(
        await sql_session.scalars(
            select(SlideModel)
            .where(SlideModel.presentation == presentation_id)
            .order_by(SlideModel.index)
        )
    )
    visible = [slide for slide in rows if slide_has_visible_content(slide)]
    structural_error = None
    if not rows:
        structural_error = "课件页尚未写入，请重新生成"
    elif expected_slides > 0 and len(rows) != expected_slides:
        structural_error = f"课件只生成了 {len(rows)}/{expected_slides} 页，请重新生成"
    elif len(visible) != len(rows):
        structural_error = "课件页已创建但没有可见正文，请重新生成"

    missing_pages: list[int] = []
    from services.asset_planning_service import build_asset_plan
    presentation = await sql_session.get(PresentationModel, presentation_id)
    if rows and (presentation is None or presentation.image_policy != ImagePolicy.DISABLED):
        pending = build_asset_plan(rows)
        missing_pages = sorted({slot.slide_index + 1 for item in pending for slot in item.slots})
    warnings = []
    if missing_pages:
        warnings.append(
            f"第 {', '.join(map(str, missing_pages))} 页配图未完成；课件文字与其他页面已保存，可先打开课件，再补齐缺图。"
        )
    return {
        "rows": rows,
        "visible_count": len(visible),
        "missing_image_pages": missing_pages,
        "warnings": warnings,
        "structural_error": structural_error,
        "usable": structural_error is None,
    }


async def _require_persisted_visible_slides(
    sql_session: AsyncSession,
    presentation_id: uuid.UUID,
    expected_slides: int,
) -> dict[str, Any]:
    report = await _inspect_persisted_visible_slides(
        sql_session, presentation_id, expected_slides
    )
    if report["structural_error"]:
        raise HTTPException(status_code=500, detail=report["structural_error"])
    return report


async def _consume_presentation_stream(
    presentation_id: uuid.UUID,
    sql_session: AsyncSession,
    task_id: str,
    *,
    topic: str,
    n_slides: int,
) -> None:
    response = await stream_presentation(presentation_id, sql_session)
    created = 0
    streamed = 0
    buffer = ""
    completed = False
    last_progress_at: datetime | None = None
    async for chunk in response.body_iterator:
        piece = chunk.decode("utf-8") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
        buffer += piece
        while "\n\n" in buffer:
            frame, buffer = buffer.split("\n\n", 1)
            for event in iter_sse_json_events(frame + "\n\n"):
                event_type = event.get("type")
                if event_type == "error":
                    raise HTTPException(
                        status_code=500,
                        detail=event.get("detail") or "课件页生成失败",
                    )
                if event_type == "slide_assets":
                    index = event.get("slide_index")
                    if isinstance(index, int):
                        created = max(created, index + 1)
                elif event_type == "chunk" and _is_slide_chunk(event.get("chunk")):
                    streamed += 1
                if event_type == "complete":
                    completed = True
                if event_type in {"chunk", "slide_assets", "status", "complete"}:
                    displayed = created if created else streamed
                    if not completed and n_slides:
                        displayed = min(displayed, max(n_slides - 1, 0))
                    progress = 30 + int(60 * max(streamed, created) / max(n_slides, 1))
                    now = datetime.now()
                    should_save = (
                        completed
                        or last_progress_at is None
                        or (now - last_progress_at).total_seconds() >= 1.5
                    )
                    if should_save:
                        last_progress_at = now
                        await _save_complete_task_by_id(
                            task_id,
                            message=f"正在生成课件（{displayed}/{max(n_slides, displayed)}）",
                            data=kindergarten_complete_task_data(
                                topic=topic,
                                stage="slides",
                                progress=min(progress, 95),
                                presentation_id=presentation_id,
                                created_slides=displayed,
                                n_slides=n_slides,
                            ),
                        )
    if buffer.strip():
        for event in iter_sse_json_events(buffer + "\n\n"):
            if event.get("type") == "error":
                raise HTTPException(
                    status_code=500,
                    detail=event.get("detail") or "课件页生成失败",
                )
            if event.get("type") == "complete":
                completed = True
    if not completed:
        raise HTTPException(
            status_code=500,
            detail="课件生成中断，页面尚未写完",
        )


async def _run_kindergarten_complete_task(
    task_id: str,
    payload_data: dict[str, Any],
    owner_id=None,
    is_admin: bool = False,
) -> None:
    """Auto-confirm the research-plan outline and generate the full deck."""
    owner_token = set_current_owner_id(owner_id)
    admin_token = set_current_owner_is_admin(is_admin)
    image_option_token = None
    try:
        async with async_session_maker() as sql_session:
            task = await sql_session.get(AsyncTaskModel, task_id)
            if task is None:
                LOGGER.warning(
                    "[kindergarten.generate_complete] task missing task_id=%s",
                    task_id,
                )
                return
            topic = str(payload_data.get("topic") or "")
            try:
                payload = KindergartenPresentationCreateRequest.model_validate(payload_data)
                image_option_token = research_ppt_image_options.set(
                    ResearchPptImageOptions(
                        enabled=True,
                        forbid_latin_text=not looks_like_english_teaching_request(
                            payload.topic,
                            payload.instructions,
                            (payload.source_context or "")[:800],
                        ),
                    )
                )
                task.status = AsyncTaskStatus.PENDING
                task.message = "正在根据教研方案规划课件大纲"
                task.data = kindergarten_complete_task_data(
                    topic=payload.topic,
                    stage="outline",
                    progress=12,
                    previous=task.data if isinstance(task.data, dict) else None,
                )
                await _save_complete_task(sql_session, task)

                prepared = await prepare_kindergarten_presentation(
                    payload,
                    _AlwaysConnectedRequest(),  # type: ignore[arg-type]
                    sql_session,
                )
                n_slides = len(prepared.outline.slides)
                task.message = "大纲已自动确认，正在生成课件页"
                task.data = kindergarten_complete_task_data(
                    topic=payload.topic,
                    stage="slides",
                    progress=28,
                    presentation_id=prepared.presentation_id,
                    created_slides=0,
                    n_slides=n_slides,
                    previous=task.data if isinstance(task.data, dict) else None,
                )
                await _save_complete_task(sql_session, task)

                last_error: Exception | None = None
                report: dict[str, Any] | None = None
                for attempt in range(2):
                    try:
                        sql_session.expire_all()
                        task = await sql_session.get(AsyncTaskModel, task_id)
                        if task is None or not complete_task_progress_writable(task.status):
                            raise CompleteTaskCancelled()
                        if attempt > 0:
                            # Only replay after a confirmed structural/provider
                            # failure. Missing images stay as warnings, not a wipe.
                            await _clear_incomplete_slides(
                                sql_session,
                                prepared.presentation_id,
                            )
                            task = await sql_session.get(AsyncTaskModel, task_id)
                            if task is None or not complete_task_progress_writable(task.status):
                                raise CompleteTaskCancelled()
                            task.message = "生成中断，正在重新生成课件页"
                            await _save_complete_task(sql_session, task)
                        await _consume_presentation_stream(
                            prepared.presentation_id,
                            sql_session,
                            task.id,
                            topic=payload.topic,
                            n_slides=n_slides,
                        )
                        report = await _require_persisted_visible_slides(
                            sql_session,
                            prepared.presentation_id,
                            n_slides,
                        )
                        last_error = None
                        break
                    except CompleteTaskCancelled:
                        raise
                    except HTTPException as exc:
                        last_error = exc
                        if attempt == 0 and is_retryable_complete_generation_error(exc):
                            LOGGER.warning(
                                "[kindergarten.generate_complete] retrying slides task_id=%s detail=%s",
                                task_id,
                                exc.detail,
                            )
                            continue
                        raise
                if last_error is not None:
                    raise last_error
                if report is None:
                    report = await _require_persisted_visible_slides(
                        sql_session, prepared.presentation_id, n_slides,
                    )

                sql_session.expire_all()
                task = await sql_session.get(AsyncTaskModel, task_id)
                if task is None or not complete_task_progress_writable(task.status):
                    return
                task.status = AsyncTaskStatus.COMPLETED
                task.message = (
                    f"教研 PPT 已生成并可打开；第 {', '.join(map(str, report['missing_image_pages']))} 页配图待补充"
                    if report["warnings"] else
                    "教研 PPT 已生成完成，点击查看"
                )
                task.error = None
                task.data = kindergarten_complete_task_data(
                    topic=payload.topic,
                    stage="completed_with_warnings" if report["warnings"] else "completed",
                    progress=100,
                    presentation_id=prepared.presentation_id,
                    created_slides=n_slides,
                    n_slides=n_slides,
                    warnings=report["warnings"],
                    missing_image_pages=report["missing_image_pages"],
                    previous=task.data if isinstance(task.data, dict) else None,
                )
                await _save_complete_task(sql_session, task)
            except CompleteTaskCancelled:
                LOGGER.info(
                    "[kindergarten.generate_complete] cancelled task_id=%s",
                    task_id,
                )
                return
            except Exception as exc:
                LOGGER.exception(
                    "[kindergarten.generate_complete] failed task_id=%s",
                    task_id,
                )
                try:
                    await sql_session.rollback()
                except Exception:
                    pass
                sql_session.expire_all()
                task = await sql_session.get(AsyncTaskModel, task_id)
                if task is None or not complete_task_progress_writable(task.status):
                    return
                detail = friendly_complete_generation_detail(_exception_detail(exc))
                task_data = task.data if isinstance(task.data, dict) else {}
                if (isinstance(exc, HTTPException) and isinstance(exc.detail, dict)
                        and exc.detail.get("code") == "KINDERGARTEN_PLAN_REVIEW_REQUIRED"):
                    task.status = AsyncTaskStatus.ERROR
                    task.message = exc.detail["message"]
                    task.error = APIErrorModel.from_exception(exc).model_dump(mode="json")
                    task.data = kindergarten_complete_task_data(
                        topic=topic, stage="review_required", progress=20,
                        presentation_id=exc.detail["presentation_id"], previous=task_data,
                    )
                    task.data["outline_path"] = exc.detail["outline_path"]
                    task.data["quality"] = exc.detail["quality"]
                    await _save_complete_task(sql_session, task)
                    return
                saved_id = task_data.get("presentation_id")
                expected = int(task_data.get("n_slides") or 0)
                report = None
                if saved_id and expected:
                    try:
                        report = await _inspect_persisted_visible_slides(
                            sql_session, uuid.UUID(str(saved_id)), expected
                        )
                    except Exception:
                        LOGGER.exception("Could not inspect saved deck after generation warning")
                if report and report["usable"]:
                    warnings = [detail, *report["warnings"]]
                    task.status = AsyncTaskStatus.COMPLETED
                    missing_label = ", ".join(map(str, report["missing_image_pages"]))
                    task.message = (
                        f"课件已生成并可打开；第 {missing_label} 页配图待补充"
                        if missing_label else
                        "课件已生成并可打开；生成过程有提示，请进入课件检查"
                    )
                    task.error = None
                    task.data = kindergarten_complete_task_data(
                        topic=topic,
                        stage="completed_with_warnings",
                        progress=100,
                        presentation_id=saved_id,
                        created_slides=report["visible_count"],
                        n_slides=expected,
                        warnings=warnings,
                        missing_image_pages=report["missing_image_pages"],
                        previous=task_data,
                    )
                    await _save_complete_task(sql_session, task)
                    return
                api_error = APIErrorModel.from_exception(
                    HTTPException(status_code=500, detail=detail)
                )
                task.status = AsyncTaskStatus.ERROR
                task.message = detail
                task.error = api_error.model_dump(mode="json")
                task.data = kindergarten_complete_task_data(
                    topic=topic,
                    stage="error",
                    progress=int((task.data or {}).get("progress") or 0),
                    presentation_id=(task.data or {}).get("presentation_id"),
                    created_slides=int((task.data or {}).get("created_slides") or 0),
                    n_slides=int((task.data or {}).get("n_slides") or 0),
                    previous=task.data if isinstance(task.data, dict) else None,
                )
                await _save_complete_task(sql_session, task)
    finally:
        if image_option_token is not None:
            research_ppt_image_options.reset(image_option_token)
        reset_current_owner_is_admin(admin_token)
        reset_current_owner_id(owner_token)


@KINDERGARTEN_ROUTER.post(
    "/presentation/generate-complete/async",
    response_model=AsyncTaskModel,
)
async def generate_kindergarten_presentation_complete_async(
    payload: KindergartenPresentationCreateRequest,
    background_tasks: BackgroundTasks,
    sql_session: AsyncSession = Depends(get_async_session),
):
    task = AsyncTaskModel(
        type=ASYNC_TASK_TYPE_KINDERGARTEN_COMPLETE,
        status=AsyncTaskStatus.PENDING,
        message="已排队，正在后台生成教研课件",
        data=kindergarten_complete_task_data(
            topic=payload.topic,
            stage="queued",
            progress=4,
        ),
    )
    sql_session.add(task)
    await sql_session.commit()
    await sql_session.refresh(task)
    background_tasks.add_task(
        _run_kindergarten_complete_task,
        task.id,
        payload.model_dump(mode="json"),
        get_current_owner_id(),
        get_current_owner_is_admin(),
    )
    return task


@KINDERGARTEN_ROUTER.post(
    "/presentation/generate-complete/{task_id}/cancel",
    response_model=AsyncTaskModel,
)
async def cancel_kindergarten_presentation_complete(
    task_id: str,
    sql_session: AsyncSession = Depends(get_async_session),
):
    task = await sql_session.get(AsyncTaskModel, task_id)
    if task is None or task.type != ASYNC_TASK_TYPE_KINDERGARTEN_COMPLETE:
        raise HTTPException(status_code=404, detail="No async task found")
    if task.status == AsyncTaskStatus.COMPLETED:
        return task
    if task.status != AsyncTaskStatus.ERROR:
        data = task.data if isinstance(task.data, dict) else {}
        task.status = AsyncTaskStatus.ERROR
        task.message = "已取消"
        task.error = APIErrorModel.from_exception(
            HTTPException(status_code=409, detail="已取消")
        ).model_dump(mode="json")
        task.data = kindergarten_complete_task_data(
            topic=str(data.get("topic") or ""),
            stage="cancelled",
            progress=int(data.get("progress") or 0),
            presentation_id=data.get("presentation_id"),
            created_slides=int(data.get("created_slides") or 0),
            n_slides=int(data.get("n_slides") or 0),
            previous=data,
        )
        await _save_complete_task(sql_session, task)
    return task


@KINDERGARTEN_ROUTER.post(
    "/lesson-plan/validate",
    response_model=KindergartenPlanQualityReport,
)
async def validate_kindergarten_plan(
    plan: KindergartenLessonPlan,
    content_mode: Literal["classroom", "training"] = "classroom",
):
    return validate_kindergarten_lesson_plan(plan, content_mode=content_mode)
