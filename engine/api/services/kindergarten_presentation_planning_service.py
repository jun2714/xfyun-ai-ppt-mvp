from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from models.kindergarten_lesson_plan import (
    KindergartenLessonPlan,
    LessonAssetSpec,
)
from models.presentation_outline_model import PresentationOutlineModel
from services.kindergarten_lesson_planning_service import (
    generate_kindergarten_lesson_plan,
)
from services.kindergarten_plan_quality_service import (
    KindergartenPlanQualityReport,
    validate_kindergarten_lesson_plan,
)
from utils.llm_utils import DisconnectChecker, TextChunkCallback


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidatedKindergartenPlanningResult:
    plan: KindergartenLessonPlan
    outline: PresentationOutlineModel
    quality: KindergartenPlanQualityReport
    attempts: int


class KindergartenPlanningQualityError(ValueError):
    """Raised when a lesson plan still violates hard teaching contracts."""

    def __init__(self, report: KindergartenPlanQualityReport, attempts: int):
        self.report = report
        self.attempts = attempts
        codes = ", ".join(issue.code for issue in report.errors) or "unknown"
        super().__init__(
            f"幼教课堂规划质检失败（模型调用 {attempts} 次）：{codes}"
        )


def _safe_label(slide) -> str:
    title = (slide.screen_content.title or "").strip()
    goal = (slide.teaching_goal or "").strip()
    return (title or goal or "课堂核心对象")[:160]


def _repair_asset_semantics(slide):
    label = _safe_label(slide)
    repaired_assets = []
    for index, asset in enumerate(slide.assets):
        semantic = (asset.semantic_label or "").strip()
        if len(semantic) < 2 or semantic in {
            "图片",
            "插画",
            "相关图片",
            "教育图片",
            "可爱图片",
        }:
            semantic = label
        description = (asset.description or "").strip()
        if len(description) < 4:
            description = (
                f"清楚呈现{semantic}，主体完整、数量明确、特征可辨认，"
                "适合幼儿园课堂观察，不出现文字、Logo或水印。"
            )
        repaired_assets.append(
            asset.model_copy(
                update={
                    "slot": asset.slot or f"visual-{index + 1}",
                    "semantic_label": semantic[:160],
                    "description": description[:800],
                }
            )
        )
    return slide.model_copy(update={"assets": repaired_assets})


def _add_required_asset(slide):
    if any(asset.required for asset in slide.assets):
        return slide
    label = _safe_label(slide)
    asset = LessonAssetSpec(
        slot="main-image",
        semantic_label=label,
        description=(
            f"清楚呈现{label}，主体完整、数量明确、关键特征可辨认，"
            "适合幼儿园课堂观察，不出现文字、数字、Logo或水印。"
        ),
        expected_count=1,
        role="framed-image",
        qa_required=True,
    )
    return slide.model_copy(update={"assets": [*slide.assets, asset]})


def _question_for_activity(slides, activity_id: str | None):
    if not activity_id:
        return None
    for slide in slides:
        if slide.slide_type not in {"guess-partial", "guess-shadow", "memory-missing"}:
            continue
        if slide.game and slide.game.activity_id == activity_id:
            return slide
    return None


def _repair_reveal_answer(slides, index: int):
    slide = slides[index]
    if not slide.game:
        return slide
    question = _question_for_activity(slides, slide.game.activity_id)
    if not question or not question.game or not question.game.answer_key:
        return slide
    return slide.model_copy(
        update={
            "game": slide.game.model_copy(
                update={"answer_key": question.game.answer_key}
            )
        }
    )


def _downgrade_contract_slide(slide):
    """Keep teacher-visible copy while removing an invalid machine-only contract.

    A malformed optional game/image contract should not throw away a complete paid
    outline. Downgrading the semantic type lets layout generation continue with the
    visible teaching content; the teacher can still edit that page before generation.
    """
    return slide.model_copy(
        update={
            "slide_type": "other",
            "game": None,
            "assets": [],
            "layout_capabilities": [
                capability
                for capability in slide.layout_capabilities
                if capability not in {
                    "question",
                    "reveal",
                    "matching",
                    "classification",
                    "sequence",
                }
            ],
        }
    )


def _repair_machine_contracts(
    plan: KindergartenLessonPlan,
    report: KindergartenPlanQualityReport,
) -> KindergartenLessonPlan:
    """Repair recoverable hidden contracts without a second paid model call."""
    slides = list(plan.slides)

    # First preserve useful semantics where a deterministic correction is obvious.
    for issue in report.errors:
        if issue.slide_no is None or not (1 <= issue.slide_no <= len(slides)):
            continue
        index = issue.slide_no - 1
        if issue.code == "reveal-answer-mismatch":
            slides[index] = _repair_reveal_answer(slides, index)
        elif issue.code == "required-asset-missing":
            slides[index] = _add_required_asset(slides[index])
        elif issue.code == "asset-semantic-too-vague":
            slides[index] = _repair_asset_semantics(slides[index])

    repaired = plan.model_copy(update={"slides": slides})

    # Revalidate. Any remaining hard error is a machine-contract problem that
    # cannot be repaired safely from deterministic data alone. Preserve the
    # visible page text and remove only the invalid optional interaction metadata.
    # Two bounded passes handle pair dependencies such as reveal-before-question
    # becoming reveal-slide-missing on the corresponding question page.
    for _ in range(2):
        remaining = validate_kindergarten_lesson_plan(repaired)
        if remaining.passed:
            return repaired
        bad_slide_numbers = {
            issue.slide_no
            for issue in remaining.errors
            if issue.slide_no is not None
        }
        if not bad_slide_numbers:
            return repaired
        slides = [
            _downgrade_contract_slide(slide)
            if slide.slide_no in bad_slide_numbers
            else slide
            for slide in repaired.slides
        ]
        repaired = repaired.model_copy(update={"slides": slides})

    return repaired


async def generate_validated_kindergarten_presentation_outline(
    *,
    topic: str,
    age_group: str,
    domain: str,
    duration_minutes: int,
    n_slides: Optional[int],
    instructions: Optional[str],
    source_context: Optional[str],
    disconnect_checker: Optional[DisconnectChecker] = None,
    text_chunk_callback: Optional[TextChunkCallback] = None,
    max_attempts: int = 1,
) -> ValidatedKindergartenPlanningResult:
    """Generate once, then repair recoverable quality-gate metadata locally.

    Previously a first draft could stream all pages to the browser, fail a hidden
    game/image contract, and silently trigger a second full LLM generation with no
    streaming callback. That made the UI appear frozen on the final page for several
    more minutes and could still end by discarding the whole outline. The visible
    classroom plan is now generated only once; recoverable machine contracts are
    repaired deterministically and revalidated before downstream slide generation.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    plan = await generate_kindergarten_lesson_plan(
        topic=topic,
        age_group=age_group,
        domain=domain,
        duration_minutes=duration_minutes,
        n_slides=n_slides,
        instructions=instructions,
        source_context=source_context,
        disconnect_checker=disconnect_checker,
        text_chunk_callback=text_chunk_callback,
    )
    report = validate_kindergarten_lesson_plan(plan)
    if report.passed:
        return ValidatedKindergartenPlanningResult(
            plan=plan,
            outline=plan.to_presentation_outline(),
            quality=report,
            attempts=1,
        )

    LOGGER.warning(
        "Kindergarten outline needs deterministic contract repair: %s",
        ", ".join(issue.code for issue in report.errors),
    )
    repaired_plan = _repair_machine_contracts(plan, report)
    repaired_report = validate_kindergarten_lesson_plan(repaired_plan)
    if repaired_report.passed:
        return ValidatedKindergartenPlanningResult(
            plan=repaired_plan,
            outline=repaired_plan.to_presentation_outline(),
            quality=repaired_report,
            attempts=1,
        )

    raise KindergartenPlanningQualityError(repaired_report, 1)
