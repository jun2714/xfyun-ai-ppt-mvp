from __future__ import annotations

import re
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

# These concern what children see, not optional machine metadata. They may not
# be turned into a passing lesson by erasing game/image contracts.
CLASSROOM_CONTENT_ERRORS = {
    "question-reveals-answer", "game-contract-missing",
    "reveal-slide-missing", "reveal-before-question", "question-slide-missing",
    "topic-replaced-by-unrequested-storyline",
}

_ANIMAL_STORY_ROLES = (
    "小熊", "熊宝宝", "小兔", "兔宝宝", "小猫", "猫咪", "小狗", "狗狗",
    "小狐狸", "小松鼠", "小猴", "小猪", "动物朋友",
)
_FANTASY_STORY_ROLES = (
    "小精灵", "魔法师", "公主", "王子", "外星人", "机器人朋友", "神秘朋友",
)


def validate_kindergarten_lesson_plan(
    plan: KindergartenLessonPlan,
    *, content_mode: Literal["classroom", "training"] = "classroom",
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
        issues.extend(_validate_slide(slide, content_mode=content_mode))

    issues.extend(_validate_activity_pairs(plan))
    issues.extend(_validate_unrequested_storyline(plan))

    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    return KindergartenPlanQualityReport(
        passed=not errors,
        errors=errors,
        warnings=warnings,
    )


def _validate_unrequested_storyline(
    plan: KindergartenLessonPlan,
) -> list[KindergartenPlanIssue]:
    topic = plan.meta.topic
    allowed_roles = {
        term
        for term in (*_ANIMAL_STORY_ROLES, *_FANTASY_STORY_ROLES)
        if term in topic
    }
    if re.search(r"动物|昆虫|森林朋友|生肖", topic):
        allowed_roles.update(_ANIMAL_STORY_ROLES)
    if re.search(r"童话|魔法|奇幻|幻想", topic):
        allowed_roles.update(_FANTASY_STORY_ROLES)
    unrequested_roles = [
        term
        for term in (*_ANIMAL_STORY_ROLES, *_FANTASY_STORY_ROLES)
        if term not in allowed_roles
    ]

    role_slides: dict[str, list[KindergartenSlidePlan]] = {
        term: [] for term in unrequested_roles
    }
    for slide in plan.slides:
        visible_and_notes = "\n".join(
            [
                slide.screen_content.title,
                *slide.screen_content.points,
                slide.teaching_goal,
                slide.teacher_note,
                *(asset.semantic_label for asset in slide.assets),
            ]
        )
        for term in unrequested_roles:
            if term in visible_and_notes:
                role_slides[term].append(slide)

    arc_text = "\n".join(plan.lesson_arc)
    violating_role = next(
        (
            term
            for term in unrequested_roles
            if len(role_slides[term]) >= 2 or term in arc_text
        ),
        None,
    )
    if not violating_role:
        return []

    affected = role_slides[violating_role]
    first = affected[0] if affected else plan.slides[0]
    return [
        _error(
            first,
            "topic-replaced-by-unrequested-storyline",
            (
                f"用户未要求的角色“{violating_role}”进入课程主线并替代原主题；"
                "必须围绕用户指定的真实主角、核心变化和教学目标展开。"
            ),
        )
    ]


def _validate_slide(
    slide: KindergartenSlidePlan, *, content_mode: str = "classroom",
) -> list[KindergartenPlanIssue]:
    issues: list[KindergartenPlanIssue] = []

    training_steps = content_mode == "training" and slide.slide_type == "sequence"
    if slide.slide_type in _GAME_SLIDE_TYPES and slide.game is None and not training_steps:
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
        if asset.audience_text and asset.audience_text not in slide.screen_content.points:
            issues.append(_error(
                slide, "asset-caption-mismatch",
                "图片 audience_text 必须逐字对应本页一条屏幕短句，不能自动按位置配图。",
            ))
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

    if slide.interaction.type == "guess" or slide.slide_type in {"guess-partial", "guess-shadow"}:
        visible = "\n".join([slide.screen_content.title, *slide.screen_content.points,
                             slide.screen_content.instruction or ""])
        if re.search(r"答案[是为：:]|正确[选答]项?[是为：:]|先出现的是|先长出的是", visible):
            issues.append(_error(
                slide, "question-reveals-answer",
                "提问页同时显示了答案结论，请把结论放到独立揭晓页，不能只在备注里写先猜后揭晓。",
            ))

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
