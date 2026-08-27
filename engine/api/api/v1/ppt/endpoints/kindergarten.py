from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from models.kindergarten_lesson_plan import (
    KindergartenDomain,
    KindergartenLessonPlan,
)
from models.presentation_outline_model import PresentationOutlineModel
from services.kindergarten_lesson_planning_service import (
    generate_kindergarten_lesson_plan,
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
    instructions: Optional[str] = Field(default=None, max_length=4000)
    source_context: Optional[str] = Field(default=None, max_length=30000)


class KindergartenLessonPlanResponse(BaseModel):
    plan: KindergartenLessonPlan
    outline: PresentationOutlineModel
    quality: KindergartenPlanQualityReport


@KINDERGARTEN_ROUTER.post(
    "/lesson-plan",
    response_model=KindergartenLessonPlanResponse,
)
async def create_kindergarten_lesson_plan(
    payload: KindergartenLessonPlanRequest,
    request: Request,
):
    plan = await generate_kindergarten_lesson_plan(
        topic=payload.topic,
        age_group=payload.age_group,
        domain=payload.domain,
        duration_minutes=payload.duration_minutes,
        n_slides=payload.n_slides,
        instructions=payload.instructions,
        source_context=payload.source_context,
        disconnect_checker=request.is_disconnected,
    )
    quality = validate_kindergarten_lesson_plan(plan)
    return KindergartenLessonPlanResponse(
        plan=plan,
        outline=plan.to_presentation_outline(),
        quality=quality,
    )


@KINDERGARTEN_ROUTER.post(
    "/lesson-plan/validate",
    response_model=KindergartenPlanQualityReport,
)
async def validate_kindergarten_plan(
    plan: KindergartenLessonPlan,
):
    return validate_kindergarten_lesson_plan(plan)
