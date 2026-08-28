from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from models.kindergarten_lesson_plan import KindergartenLessonPlan
from models.presentation_outline_model import PresentationOutlineModel
from services.kindergarten_lesson_planning_service import (
    generate_kindergarten_lesson_plan,
)
from services.kindergarten_plan_quality_service import (
    KindergartenPlanQualityReport,
    validate_kindergarten_lesson_plan,
)
from utils.llm_utils import DisconnectChecker


@dataclass(frozen=True)
class ValidatedKindergartenPlanningResult:
    plan: KindergartenLessonPlan
    outline: PresentationOutlineModel
    quality: KindergartenPlanQualityReport
    attempts: int


class KindergartenPlanningQualityError(ValueError):
    """Raised when a paid lesson plan still violates hard teaching contracts."""

    def __init__(self, report: KindergartenPlanQualityReport, attempts: int):
        self.report = report
        self.attempts = attempts
        codes = ", ".join(issue.code for issue in report.errors) or "unknown"
        super().__init__(
            f"幼教课堂规划质检失败（尝试 {attempts} 次）：{codes}"
        )


def _repair_feedback(report: KindergartenPlanQualityReport) -> str:
    lines = [
        "上一次课堂计划没有通过硬性质量校验。重新规划整份课堂时必须修复以下问题，",
        "不要只在文字上解释问题，也不要删除课堂核心内容来规避校验：",
    ]
    for issue in report.errors:
        location = f"第 {issue.slide_no} 页" if issue.slide_no else "整份课堂"
        lines.append(f"- {location} [{issue.code}] {issue.message}")
    lines.extend(
        [
            "重新检查题目页/答案页 activity_id 与 answer_key 是否完全一致；",
            "重新检查互动页的 game 契约；重新检查每个视觉认知页的必需图片语义、",
            "数量和可验证特征。输出仍必须严格符合原 JSON Schema。",
        ]
    )
    return "\n".join(lines)


def _append_repair_instructions(
    instructions: Optional[str],
    report: KindergartenPlanQualityReport,
) -> str:
    base = (instructions or "").strip()
    repair = _repair_feedback(report)
    return f"{base}\n\n{repair}" if base else repair


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
    max_attempts: int = 2,
) -> ValidatedKindergartenPlanningResult:
    """Plan a kindergarten lesson and gate it before layout/image generation.

    A schema-valid JSON response can still contain a wrong reveal answer, a game
    without its answer map, or a visual-recognition page without required image
    semantics. We therefore allow one bounded planner repair and stop before the
    downstream slide/image calls when the repaired plan is still invalid.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    attempt_instructions = instructions
    last_report: KindergartenPlanQualityReport | None = None

    for attempt in range(1, max_attempts + 1):
        plan = await generate_kindergarten_lesson_plan(
            topic=topic,
            age_group=age_group,
            domain=domain,
            duration_minutes=duration_minutes,
            n_slides=n_slides,
            instructions=attempt_instructions,
            source_context=source_context,
            disconnect_checker=disconnect_checker,
        )
        report = validate_kindergarten_lesson_plan(plan)
        last_report = report
        if report.passed:
            return ValidatedKindergartenPlanningResult(
                plan=plan,
                outline=plan.to_presentation_outline(),
                quality=report,
                attempts=attempt,
            )

        if attempt < max_attempts:
            attempt_instructions = _append_repair_instructions(
                instructions,
                report,
            )

    assert last_report is not None
    raise KindergartenPlanningQualityError(last_report, max_attempts)
