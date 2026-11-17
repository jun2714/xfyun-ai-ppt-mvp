"""Contracts for an explicit, bounded review of existing lesson-plan text.

The reviewer never returns a passing grade. The service derives its status from
validated findings, source availability and the existing deterministic checks.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.kindergarten_lesson_plan import (
    KindergartenDomain,
    KindergartenLessonPlan,
    KindergartenSlidePlan,
)
from services.kindergarten_plan_quality_service import KindergartenPlanQualityReport


ReviewCriterion = Literal[
    "topic_focus",
    "age_and_audience",
    "teaching_feasibility",
    "cross_slide_coherence",
    "source_fidelity",
    "visual_brief_alignment",
]
REVIEW_CRITERIA: tuple[str, ...] = (
    "topic_focus",
    "age_and_audience",
    "teaching_feasibility",
    "cross_slide_coherence",
    "source_fidelity",
    "visual_brief_alignment",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewBrief(_StrictModel):
    topic: str = Field(min_length=1, max_length=200)
    age_group: str = Field(default="4-5岁", min_length=1, max_length=40)
    domain: KindergartenDomain = "comprehensive"
    content_mode: Literal["classroom", "training"] = "classroom"
    duration_minutes: int = Field(default=20, ge=5, le=90)
    n_slides: Optional[int] = Field(default=None, ge=3, le=40)
    instructions: Optional[str] = Field(default=None, max_length=1000)
    source_context: Optional[str] = Field(default=None, max_length=30000)


class KindergartenContentReviewRequest(_StrictModel):
    brief: ReviewBrief
    plan: KindergartenLessonPlan
    max_revision_rounds: int = Field(default=0, ge=0, le=2)
    timeout_seconds: float = Field(default=120, ge=1, le=600)
    # This bounds invocation attempts, including failures before submission. It
    # is deliberately not described as a number of billable model requests.
    max_model_calls: int = Field(default=5, ge=1, le=5)

    @model_validator(mode="after")
    def bound_review_input(self):
        serialized = json.dumps(self.plan.model_dump(mode="json"), ensure_ascii=False)
        if len(serialized) > 120000:
            raise ValueError("审核试点单份教案内容不能超过 120000 字符，请拆分材料。")
        return self


class SemanticFinding(_StrictModel):
    issue_id: str = Field(min_length=1, max_length=80)
    criterion: ReviewCriterion
    severity: Literal["error", "warning"]
    slide_no: int = Field(ge=1, le=40)
    # Relative to this slide, e.g. screen_content.title or assets.0.description.
    # Paths are resolved as data; they are never evaluated as Python expressions.
    field_path: str = Field(min_length=1, max_length=160)
    evidence: str = Field(min_length=1, max_length=2000)
    requirement: str = Field(min_length=1, max_length=2000)
    explanation: str = Field(min_length=1, max_length=2000)
    suggestion: str = Field(min_length=1, max_length=2000)
    requires_source: bool = False


class SemanticReview(_StrictModel):
    criteria_checked: list[ReviewCriterion] = Field(min_length=1, max_length=6)
    findings: list[SemanticFinding] = Field(default_factory=list, max_length=60)
    source_status: Literal["sufficient", "insufficient", "not_required"]
    source_quotes: list[str] = Field(default_factory=list, max_length=10)
    needs_human: bool = False
    human_questions: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_unique_findings(self):
        ids = [item.issue_id for item in self.findings]
        if len(ids) != len(set(ids)):
            raise ValueError("Semantic finding identifiers must be unique.")
        if len(self.criteria_checked) != len(set(self.criteria_checked)):
            raise ValueError("Review criteria must not be repeated.")
        if any(not text.strip() or len(text) > 2000 for text in self.source_quotes):
            raise ValueError("Source quotations must be non-empty and bounded.")
        if any(not text.strip() or len(text) > 2000 for text in self.human_questions):
            raise ValueError("Human questions must be non-empty and bounded.")
        return self


class SlideReplacement(_StrictModel):
    slide_no: int = Field(ge=1, le=40)
    issue_ids: list[str] = Field(min_length=1, max_length=60)
    replacement: KindergartenSlidePlan


class TargetedRevision(_StrictModel):
    # Whole-plan replacement is intentionally not part of this response schema.
    replacements: list[SlideReplacement] = Field(min_length=1, max_length=40)


class ProviderUsage(_StrictModel):
    # Null means the provider did not report this value. Never fill unknown usage
    # with zero or approximate character counts and call it measured usage.
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)
    cached_input_tokens: Optional[int] = Field(default=None, ge=0)


@dataclass(frozen=True)
class ModelCall:
    stage: Literal["review", "revise"]
    system_prompt: str
    payload: dict[str, Any]
    response_schema: dict[str, Any]
    round_no: int


@dataclass(frozen=True)
class ModelReply:
    payload: dict[str, Any]
    model: Optional[str] = None
    usage: Optional[ProviderUsage] = None
    # None means the adapter cannot establish whether an HTTP request was sent.
    submitted: Optional[bool] = None


class JsonCaller(Protocol):
    """One explicit invocation; implementations must not silently retry."""

    async def __call__(self, call: ModelCall) -> ModelReply: ...


class ModelCallRecord(_StrictModel):
    attempt: int
    stage: Literal["review", "revise"]
    round_no: int
    elapsed_ms: int = Field(ge=0)
    outcome: Literal["completed", "error", "timeout", "cancelled", "invalid_output"]
    model: Optional[str] = None
    usage: Optional[ProviderUsage] = None
    submitted: Optional[bool] = None
    error_code: Optional[str] = None


class ReviewSnapshot(_StrictModel):
    round_no: int = Field(ge=0, le=2)
    plan_sha256: str
    machine_quality: KindergartenPlanQualityReport
    semantic_review: SemanticReview
    adopted: bool


ReviewStatus = Literal[
    "passed",
    "needs_revision",
    "needs_human",
    "max_rounds_reached",
    "no_progress",
    "budget_exhausted",
    "timeout",
    "cancelled",
    "model_error",
    "invalid_output",
    "revision_rejected",
]


class KindergartenContentReviewResponse(_StrictModel):
    status: ReviewStatus
    message: str
    original_plan: KindergartenLessonPlan
    plan: KindergartenLessonPlan
    machine_quality: KindergartenPlanQualityReport
    semantic_review: Optional[SemanticReview] = None
    review_history: list[ReviewSnapshot] = Field(default_factory=list)
    rounds_completed: int = Field(default=0, ge=0, le=2)
    call_attempts: int = Field(default=0, ge=0, le=5)
    calls: list[ModelCallRecord] = Field(default_factory=list)
    elapsed_ms: int = Field(ge=0)
    failure_code: Optional[str] = None
    visual_validation: Literal["not_performed"] = "not_performed"
    limitations: list[str] = Field(default_factory=lambda: [
        "本次仅审核教案与逐页文稿、图片描述，未检查实际图片像素、PPT排版或导出。",
        "模型语义审核结果不等同于教师验收或对事实来源的独立验证。",
    ])
