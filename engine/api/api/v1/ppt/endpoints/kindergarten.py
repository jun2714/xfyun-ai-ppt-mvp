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
from models.image_policy import ImagePolicy
from models.kindergarten_lesson_plan import (
    KindergartenDomain,
    KindergartenLessonPlan,
)
from models.presentation_outline_model import PresentationOutlineModel
from services.database import get_async_session
from services.kindergarten_presentation_planning_service import (
    KindergartenPlanningQualityError,
    ValidatedKindergartenPlanningResult,
    generate_validated_kindergarten_presentation_outline,
)
from services.kindergarten_plan_quality_service import (
    KindergartenPlanQualityReport,
    validate_kindergarten_lesson_plan,
)


KINDERGARTEN_ROUTER = APIRouter(prefix="/kindergarten", tags=["Kindergarten"])


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


class KindergartenPresentationPrepareRequest(KindergartenLessonPlanRequest):
    template: str = Field(default="general", min_length=1, max_length=200)
    language: str = Field(default="Chinese", min_length=1, max_length=80)
    image_policy: ImagePolicy = ImagePolicy.STANDARD


class KindergartenPresentationPrepareResponse(KindergartenLessonPlanResponse):
    presentation_id: uuid.UUID
    stream_path: str


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
            source_context=payload.source_context,
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
    "/presentation/prepare",
    response_model=KindergartenPresentationPrepareResponse,
)
async def prepare_kindergarten_presentation(
    payload: KindergartenPresentationPrepareRequest,
    request: Request,
    sql_session: AsyncSession = Depends(get_async_session),
):
    """Create a reviewed-outline deck that continues through the normal PPT stream.

    The important boundary is that the kindergarten lesson plan is converted into
    `SlideOutlineModel` objects *with hidden machine contracts intact* before the
    standard layout selector and slide-content generator run. The existing
    `/presentation/stream/{id}` route then performs slide generation, semantic
    preflight, image generation, post-image vision QA, persistence, and resume.
    """
    result = await _generate_validated_plan(payload, request)

    presentation = await create_presentation(
        content=payload.topic,
        n_slides=len(result.outline.slides),
        language=payload.language,
        file_paths=None,
        instructions=payload.instructions,
        include_table_of_contents=False,
        include_title_slide=True,
        web_search=False,
        generation_mode="standard",
        community_design_ids=None,
        image_policy=payload.image_policy,
        sql_session=sql_session,
    )
    try:
        prepared = await prepare_presentation(
            presentation_id=presentation.id,
            outlines=result.outline.slides,
            layout=payload.template,
            title=payload.topic,
            sql_session=sql_session,
        )
    except Exception:
        # The presentation row is useful only if preparation succeeds. Avoid
        # leaving an empty shell when a template/layout contract rejects the plan.
        await sql_session.delete(presentation)
        await sql_session.commit()
        raise

    presentation_id = prepared.presentation_id
    return KindergartenPresentationPrepareResponse(
        presentation_id=presentation_id,
        stream_path=f"/api/v1/ppt/presentation/stream/{presentation_id}",
        plan=result.plan,
        outline=result.outline,
        quality=result.quality,
        planning_attempts=result.attempts,
    )


@KINDERGARTEN_ROUTER.post(
    "/lesson-plan/validate",
    response_model=KindergartenPlanQualityReport,
)
async def validate_kindergarten_plan(
    plan: KindergartenLessonPlan,
):
    return validate_kindergarten_lesson_plan(plan)
