from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from models.kindergarten_lesson_plan import (
    KindergartenLessonPlan,
    KindergartenSlidePlan,
)


class KindergartenPlanIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    slide_no: Optional[int] = None


class KindergartenPlanQualityReport(BaseModel):
    passed: bool
    errors: list[KindergartenPlanIssue] = Field(default_factory=list)
    warnings: list[KindergartenPlanIssue] = Field(default_factory=list)


_GAME_SLIDE_TYPES = {
    "guess-partial",
    "guess-shadow",
    "memory-missing",
    "matching",
    "classification",
    "sequence",
}


def validate_kindergarten_lesson_plan(
    plan: KindergartenLessonPlan,
) -> KindergartenPlanQualityReport:
    issues: list[KindergartenPlanIssue] = []

    if len(plan.slides) < 3:
        issues.append(
            KindergartenPlanIssue(
                severity="warning",
                code="lesson-too-short",
                message="课堂页数少于 3 页，可能不足以形成完整的导入、活动和回顾。",
            )
        )

    for slide in plan.slides:
        issues.extend(_validate_slide(slide))

    issues.extend(_validate_activity_pairs(plan))

    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    return KindergartenPlanQualityReport(
        passed=not errors,
        errors=errors,
        warnings=warnings,
    )


def _validate_slide(slide: KindergartenSlidePlan) -> list[KindergartenPlanIssue]:
    issues: list[KindergartenPlanIssue] = []

    if slide.slide_type in _GAME_SLIDE_TYPES and slide.game is None:
        issues.append(
            _error(
                slide,
                "game-contract-missing",
                "互动/游戏页缺少 game 契约，无法锁定题目与答案。",
            )
        )
        return issues

    if slide.slide_type == "answer-reveal" and (
        slide.game is None or not slide.game.answer_key
    ):
        issues.append(
            _error(
                slide,
                "reveal-answer-missing",
                "答案揭晓页必须携带与题目页一致的 activity_id 和 answer_key。",
            )
        )

    if slide.game:
        game = slide.game
        if game.type in {"guess", "memory", "choice"}:
            if not game.answer_key:
                issues.append(
                    _error(
                        slide,
                        "answer-key-missing",
                        "猜测、记忆或选择活动必须先锁定 answer_key。",
                    )
                )
            if game.type in {"guess", "choice"} and len(game.options) < 2:
                issues.append(
                    _error(
                        slide,
                        "options-too-few",
                        "猜测或选择活动至少需要 2 个明确选项。",
                    )
                )
            if (
                game.answer_key
                and game.options
                and game.answer_key not in game.options
                and game.answer_key not in game.options.values()
            ):
                issues.append(
                    _error(
                        slide,
                        "answer-not-in-options",
                        "answer_key 必须对应某个选项键或选项值。",
                    )
                )
        elif game.type in {"matching", "classification"}:
            if not game.answer_map:
                issues.append(
                    _error(
                        slide,
                        "answer-map-missing",
                        "配对或分类活动必须提供 answer_map，不能只生成题面。",
                    )
                )
        elif game.type == "sequence" and len(game.sequence_order) < 2:
            issues.append(
                _error(
                    slide,
                    "sequence-order-missing",
                    "排序活动必须提供至少 2 项的正确 sequence_order。",
                )
            )

    required_assets = [asset for asset in slide.assets if asset.required]
    if slide.slide_type in {
        "knowledge-single",
        "image-observation",
        "guess-partial",
        "guess-shadow",
        "memory-show",
        "memory-missing",
        "matching",
        "classification",
    } and not required_assets:
        issues.append(
            _error(
                slide,
                "required-asset-missing",
                "该页依赖视觉认知，但没有声明必需图片语义。",
            )
        )

    seen: set[tuple[str, str]] = set()
    for asset in required_assets:
        key = (asset.slot.casefold(), asset.semantic_label.casefold())
        if key in seen:
            issues.append(
                KindergartenPlanIssue(
                    severity="warning",
                    code="duplicate-asset-contract",
                    message="同一图片槽与语义重复声明，可合并后再生成。",
                    slide_no=slide.slide_no,
                )
            )
        seen.add(key)
        if asset.qa_required and len(asset.semantic_label.strip()) < 2:
            issues.append(
                _error(
                    slide,
                    "asset-semantic-too-vague",
                    "需要质检的图片必须有明确 semantic_label。",
                )
            )

    visible_chars = len(slide.screen_content.title)
    visible_chars += sum(len(point) for point in slide.screen_content.points)
    visible_chars += len(slide.screen_content.instruction or "")
    if visible_chars > 150:
        issues.append(
            KindergartenPlanIssue(
                severity="warning",
                code="visible-copy-too-dense",
                message="幼儿课堂页可见文字超过 150 字，建议拆页或压缩为关键词。",
                slide_no=slide.slide_no,
            )
        )

    if len(slide.screen_content.points) > 4:
        issues.append(
            KindergartenPlanIssue(
                severity="warning",
                code="too-many-teaching-points",
                message="单页知识点超过 4 个，幼儿课堂建议每页只保留一个核心目标。",
                slide_no=slide.slide_no,
            )
        )

    if len(slide.teacher_note.strip()) < 8:
        issues.append(
            KindergartenPlanIssue(
                severity="warning",
                code="teacher-note-too-short",
                message="教师备注过短，建议补充提问方式、动作或课堂引导。",
                slide_no=slide.slide_no,
            )
        )

    return issues


def _validate_activity_pairs(
    plan: KindergartenLessonPlan,
) -> list[KindergartenPlanIssue]:
    issues: list[KindergartenPlanIssue] = []
    question_activities: dict[str, KindergartenSlidePlan] = {}
    reveal_activities: dict[str, KindergartenSlidePlan] = {}

    for slide in plan.slides:
        if not slide.game:
            continue
        activity_id = slide.game.activity_id
        if slide.slide_type in {"guess-partial", "guess-shadow"}:
            question_activities[activity_id] = slide
        elif slide.slide_type == "answer-reveal":
            reveal_activities[activity_id] = slide

    for activity_id, question in question_activities.items():
        reveal = reveal_activities.get(activity_id)
        if reveal is None:
            issues.append(
                _error(
                    question,
                    "reveal-slide-missing",
                    f"活动 {activity_id} 没有对应的答案揭晓页。",
                )
            )
            continue
        if reveal.slide_no <= question.slide_no:
            issues.append(
                _error(
                    reveal,
                    "reveal-before-question",
                    f"活动 {activity_id} 的答案页必须出现在题目页之后。",
                )
            )
        if question.game and reveal.game:
            if question.game.answer_key != reveal.game.answer_key:
                issues.append(
                    _error(
                        reveal,
                        "reveal-answer-mismatch",
                        f"活动 {activity_id} 的题目页与答案页 answer_key 不一致。",
                    )
                )

    for activity_id, reveal in reveal_activities.items():
        if activity_id not in question_activities:
            issues.append(
                KindergartenPlanIssue(
                    severity="warning",
                    code="orphan-reveal",
                    message=f"答案页活动 {activity_id} 没有找到对应的猜测题目页。",
                    slide_no=reveal.slide_no,
                )
            )

    return issues


def _error(
    slide: KindergartenSlidePlan,
    code: str,
    message: str,
) -> KindergartenPlanIssue:
    return KindergartenPlanIssue(
        severity="error",
        code=code,
        message=message,
        slide_no=slide.slide_no,
    )
