from __future__ import annotations

from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.v1.ppt.endpoints.presentation import (
    create_presentation,
    prepare_presentation,
)
from enums.tone import Tone
from enums.verbosity import Verbosity
from models.image_policy import ImagePolicy
from models.kindergarten_lesson_plan import (
    KindergartenDomain,
    KindergartenLessonPlan,
)
from models.presentation_outline_model import PresentationOutlineModel
from services.database import get_async_session
from services.documents_loader import DocumentsLoader
from services.kindergarten_presentation_planning_service import (
    KindergartenPlanningQualityError,
    ValidatedKindergartenPlanningResult,
    generate_validated_kindergarten_presentation_outline,
)
from services.kindergarten_plan_quality_service import (
    KindergartenPlanQualityReport,
    validate_kindergarten_lesson_plan,
)
from services.kindergarten_template_routing_service import (
    AUTO_TEMPLATE_NAME,
    resolve_kindergarten_template,
)
from services.mem0_presentation_memory_service import (
    MEM0_PRESENTATION_MEMORY_SERVICE,
)


KINDERGARTEN_ROUTER = APIRouter(prefix="/kindergarten", tags=["Kindergarten"])
MAX_KINDERGARTEN_SOURCE_CONTEXT_CHARS = 30000


class KindergartenLessonPlanRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    age_group: str = Field(default="4-5岁", min_length=1, max_length=40)
    domain: KindergartenDomain = "comprehensive"
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


class KindergartenPresentationPrepareResponse(KindergartenPresentationCreateResponse):
    stream_path: str


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
) -> ValidatedKindergartenPlanningResult:
    try:
        return await generate_validated_kindergarten_presentation_outline(
            topic=payload.topic,
            age_group=payload.age_group,
            domain=payload.domain,
            duration_minutes=payload.duration_minutes,
            n_slides=payload.n_slides,
            instructions=payload.instructions,
            source_context=await _planning_source_context(payload),
            disconnect_checker=request.is_disconnected,
        )
    except KindergartenPlanningQualityError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "KINDERGARTEN_PLAN_QUALITY_FAILED",
                "message": "幼教课堂规划经过自动修复后仍未通过硬性质量校验",
                "planning_attempts": exc.attempts,
                "quality": exc.report.model_dump(mode="json"),
            },
        ) from exc


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


def _routing_response_fields(routing) -> dict:
    return {
        "selected_template": routing.template,
        "template_selection_reason": routing.reason,
        "template_scores": routing.scores,
    }


@KINDERGARTEN_ROUTER.post(
    "/lesson-plan",
    response_model=KindergartenLessonPlanResponse,
)
async def create_kindergarten_lesson_plan(
    payload: KindergartenLessonPlanRequest,
    request: Request,
):
    result = await _generate_validated_plan(payload, request)
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

    This is the product-facing kindergarten entry point. It runs the dedicated
    lesson planner + repair/quality loop, stores the machine-contract outline, and
    returns the recommended template. The browser can now open the existing outline
    editor, let the teacher review/edit it, and only then call `/presentation/prepare`.
    No paid image generation or slide materialization happens in this endpoint.
    """
    result = await _generate_validated_plan(payload, request)
    routing = resolve_kindergarten_template(
        result.plan,
        payload.template,
        instructions=payload.instructions,
    )
    presentation = await _create_reviewable_presentation(
        payload,
        result,
        sql_session,
    )

    return KindergartenPresentationCreateResponse(
        presentation_id=presentation.id,
        outline_path=f"/presentations/{presentation.id}/outline",
        plan=result.plan,
        outline=result.outline,
        quality=result.quality,
        planning_attempts=result.attempts,
        **_routing_response_fields(routing),
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
    """One-shot plan + route + prepare endpoint for API clients without review UI.

    Interactive Teachnova creation should prefer `/presentation/create`, which keeps
    the human outline-review checkpoint. This endpoint remains useful to service/API
    callers that deliberately want to skip that checkpoint.
    """
    result = await _generate_validated_plan(payload, request)
    routing = resolve_kindergarten_template(
        result.plan,
        payload.template,
        instructions=payload.instructions,
    )

    presentation = await _create_reviewable_presentation(
        payload,
        result,
        sql_session,
    )
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
        **_routing_response_fields(routing),
    )


@KINDERGARTEN_ROUTER.post(
    "/lesson-plan/validate",
    response_model=KindergartenPlanQualityReport,
)
async def validate_kindergarten_plan(
    plan: KindergartenLessonPlan,
):
    return validate_kindergarten_lesson_plan(plan)
