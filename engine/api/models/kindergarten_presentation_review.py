"""Owner-scoped, versioned review of a saved kindergarten outline."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from models.kindergarten_content_review import KindergartenContentReviewResponse, ReviewBrief
from models.kindergarten_lesson_plan import KindergartenLessonPlan
from models.presentation_outline_model import PresentationOutlineModel


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PresentationReviewRequest(_StrictModel):
    source_version: str = Field(pattern=r"^[a-f0-9]{64}$")
    max_revision_rounds: int = Field(default=0, ge=0, le=2)
    timeout_seconds: float = Field(default=360, ge=1, le=600)
    max_model_calls: int = Field(default=5, ge=1, le=5)
    request_id: UUID


class PresentationReviewResponse(_StrictModel):
    review_id: UUID
    source_version: str
    result: KindergartenContentReviewResponse
    can_apply: bool
    changed_slide_numbers: list[int] = Field(default_factory=list)
    stale: bool = False
    applied: bool = False
    applied_source_version: Optional[str] = None
    message: str = ""


class ActivePresentationReview(_StrictModel):
    review_id: UUID
    request_id: UUID
    source_version: str
    deadline_at: datetime
    expired: bool


class PresentationReviewSourceResponse(_StrictModel):
    available: bool
    reason: Optional[str] = None
    message: str
    source_version: Optional[str] = None
    brief: Optional[ReviewBrief] = None
    plan: Optional[KindergartenLessonPlan] = None
    latest_review: Optional[PresentationReviewResponse] = None
    active_review: Optional[ActivePresentationReview] = None
    apply_available: bool = False


class ApplyPresentationReviewRequest(_StrictModel):
    review_id: UUID
    source_version: str = Field(pattern=r"^[a-f0-9]{64}$")


class ApplyPresentationReviewResponse(_StrictModel):
    outlines: PresentationOutlineModel
    source_version: str
    message: str
