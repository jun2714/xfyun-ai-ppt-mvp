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
    CLASSROOM_CONTENT_ERRORS,
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


def _repair_classroom_activity_contracts(
    plan: KindergartenLessonPlan,
) -> KindergartenLessonPlan:
    """Complete deterministic choice/reveal contracts without changing the answer."""
    slides = []
    for slide in plan.slides:
        game = slide.game
        if (
            game
            and game.type in {"guess", "choice"}
            and game.answer_key
            and game.options
            and game.answer_key not in game.options
            and game.answer_key not in game.options.values()
        ):
            option_key = "答案"
            suffix = 2
            while option_key in game.options:
                option_key = f"答案{suffix}"
                suffix += 1
            slide = slide.model_copy(
                update={
                    "game": game.model_copy(
                        update={
                            "options": {
                                **game.options,
                                option_key: game.answer_key,
                            }
                        }
                    )
                }
            )
        slides.append(slide)

    reveal_activity_ids = {
        slide.game.activity_id
        for slide in slides
        if slide.slide_type == "answer-reveal" and slide.game
    }
    completed = []
    for slide in slides:
        completed.append(slide)
        if (
            slide.slide_type not in {"guess-partial", "guess-shadow"}
            or not slide.game
            or not slide.game.answer_key
            or slide.game.activity_id in reveal_activity_ids
        ):
            continue
        answer = (slide.game.options or {}).get(
            slide.game.answer_key, slide.game.answer_key,
        )
        completed.append(
            slide.model_copy(
                update={
                    "slide_type": "answer-reveal",
                    "teaching_goal": f"揭晓并确认答案：{answer}"[:300],
                    "screen_content": slide.screen_content.model_copy(
                        update={
                            "title": "答案揭晓",
                            "points": [f"正确答案：{answer}"[:80]],
                            "instruction": None,
                        }
                    ),
                    "interaction": slide.interaction.model_copy(
                        update={
                            "type": "observe",
                            "instruction": "请幼儿观察完整画面并说出判断依据。",
                        }
                    ),
                    "teacher_note": (
                        f"揭晓正确答案“{answer}”，回扣上一页线索，"
                        "邀请幼儿说明自己判断时观察到了什么。"
                    ),
                    "assets": [
                        LessonAssetSpec(
                            slot="answer-image",
                            semantic_label=answer[:160],
                            description=(
                                f"完整、清晰展示正确答案“{answer}”，主体明确，"
                                "适合幼儿观察，不出现文字、字母、数字或水印。"
                            )[:800],
                            role="framed-image",
                        )
                    ],
                    "layout_capabilities": ["reveal", "single-focus", "scene"],
                }
            )
        )
        reveal_activity_ids.add(slide.game.activity_id)

    renumbered = [
        slide.model_copy(update={"slide_no": index})
        for index, slide in enumerate(completed, start=1)
    ]
    return plan.model_copy(update={"slides": renumbered})


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


def _ensure_cover_contract(
    plan: KindergartenLessonPlan,
    content_mode: str,
) -> KindergartenLessonPlan:
    """Guarantee a real first-page cover without discarding opening content."""
    topic_focus = plan.meta.topic
    for separator in ("，", "。", "；", ";", "\n"):
        topic_focus = topic_focus.split(separator, 1)[0]
    topic_focus = topic_focus.strip()[:60] or plan.meta.topic[:60]
    purpose = "；".join(plan.lesson_goals[:2]).strip("；")
    cover_points = (
        [
            f"培训目的：{purpose or '围绕核心问题形成可落地的改进方案'}"[:64],
            "幼儿园园本教研培训",
        ]
        if content_mode == "training"
        else [
            f"活动目标：{purpose or '在观察与互动中获得新的发现'}"[:64],
            "幼儿园集体教学",
        ]
    )

    original_first = plan.slides[0]
    cover = original_first.model_copy(
        update={
            "slide_no": 1,
            "slide_type": "cover-scene",
            "teaching_goal": (
                "说明培训主题、目的与使用类型"
                if content_mode == "training"
                else "呈现活动主题、目标与使用类型"
            ),
            "screen_content": original_first.screen_content.model_copy(
                update={
                    "section": None,
                    "title": topic_focus,
                    "points": cover_points,
                    "instruction": None,
                }
            ),
            "interaction": original_first.interaction.model_copy(
                update={"type": "none", "instruction": None}
            ),
            "teacher_note": (
                "封面页。简要介绍本次培训主题与目标。"
                if content_mode == "training"
                else "封面页。简要介绍本次活动主题与目标。"
            ),
            "assets": [],
            "game": None,
            "layout_capabilities": ["cover", "single-focus"],
        }
    )

    if original_first.slide_type == "cover-scene":
        slides = [cover, *plan.slides[1:]]
    elif len(plan.slides) >= 40:
        raise ValueError(
            "大纲已达到 40 页上限且缺少封面，无法在不丢失正文的情况下补充标题页。"
        )
    else:
        slides = [cover, *plan.slides]
    renumbered = [
        slide.model_copy(update={"slide_no": index})
        for index, slide in enumerate(slides, start=1)
    ]
    return plan.model_copy(update={"slides": renumbered})


def _normalize_training_contracts(
    plan: KindergartenLessonPlan,
) -> KindergartenLessonPlan:
    """Remove child-game metadata and keep projected training copy layout-safe."""
    child_game_types = {
        "guess-partial",
        "guess-shadow",
        "memory-show",
        "memory-missing",
        "matching",
        "classification",
        "sequence",
        "answer-reveal",
    }
    slides = []
    topic_focus = plan.meta.topic
    for separator in ("，", "。", "；", ";", "\n"):
        topic_focus = topic_focus.split(separator, 1)[0]
    topic_focus = topic_focus.strip()[:60] or plan.meta.topic[:60]

    for index, slide in enumerate(plan.slides):
        original_points = list(slide.screen_content.points)
        visible_chars = len(slide.screen_content.title) + sum(
            len(point) for point in original_points
        )
        compacted_points = original_points
        teacher_note = slide.teacher_note
        char_limit = (
            70
            if index == 0
            else 160
            if slide.slide_type in {"compare", "sequence"}
            else 140
        )
        if visible_chars > char_limit:
            if len(original_points) > 4:
                compacted_points = [
                    (point.split("：", 1)[0] if "：" in point else point)[:24]
                    for point in original_points[:6]
                ]
            else:
                compacted_points = [point[:36] for point in original_points]
            details = "\n".join(f"- {point}" for point in original_points)
            teacher_note = (
                f"{teacher_note.rstrip()}\n\n本页屏幕文案已压缩，讲解时补充：\n{details}"
            )[:1200]

        screen_title = topic_focus if index == 0 else slide.screen_content.title[:36]
        if index == 0:
            purpose = "；".join(plan.lesson_goals[:2]).strip("；")
            compacted_points = [
                f"培训目的：{purpose or '围绕核心问题形成可落地的改进方案'}"[:64],
                "幼儿园园本教研培训",
            ]
        updates = {
            "screen_content": slide.screen_content.model_copy(
                update={
                    "title": screen_title,
                    "points": compacted_points,
                    "instruction": None if index == 0 else slide.screen_content.instruction,
                }
            ),
            "teacher_note": teacher_note,
        }
        if index == 0:
            updates.update(
                {
                    "slide_type": "cover-scene",
                    "game": None,
                    "interaction": slide.interaction.model_copy(
                        update={"type": "none", "instruction": None}
                    ),
                    "layout_capabilities": ["scene", "single-focus"],
                }
            )
        is_plain_training_sequence = (
            slide.slide_type == "sequence" and slide.game is None
        )
        if index == 0 or is_plain_training_sequence or (
            slide.slide_type not in child_game_types and slide.game is None
        ):
            slides.append(slide.model_copy(update=updates))
            continue
        slides.append(
            slide.model_copy(
                update={
                    **updates,
                    "slide_type": "other",
                    "game": None,
                    "layout_capabilities": [
                        capability
                        for capability in slide.layout_capabilities
                        if capability
                        not in {
                            "question",
                            "reveal",
                            "matching",
                            "classification",
                            "sequence",
                        }
                    ],
                }
            )
        )
    # Turn an evidence page into an explicit two-column subjective/objective
    # comparison even when the model returns an extra explanatory bullet.
    for index, slide in enumerate(slides[1:], start=1):
        subjective = next(
            (
                point
                for point in slide.screen_content.points
                if point.startswith("主观判断：")
            ),
            None,
        )
        objective = next(
            (
                point
                for point in slide.screen_content.points
                if point.startswith("客观证据：")
            ),
            None,
        )
        if not subjective or not objective:
            continue
        omitted = [
            point
            for point in slide.screen_content.points
            if point not in {subjective, objective}
        ]
        note = slide.teacher_note
        if omitted:
            note = (
                f"{note.rstrip()}\n\n补充说明："
                + "；".join(omitted)
            )[:1200]
        slides[index] = slide.model_copy(
            update={
                "slide_type": "compare",
                "screen_content": slide.screen_content.model_copy(
                    update={"points": [subjective, objective]}
                ),
                "teacher_note": note,
                "layout_capabilities": ["scene", "compare", "observation"],
            }
        )
        break

    # Synthesize one explicit answer page from the generated problem, action and
    # evaluation pages. This makes the deck directly answer "遇到后怎么解决".
    problem = next(
        (
            slide
            for slide in slides[1:]
            if any(term in slide.screen_content.title for term in ("为何", "为什么", "问题"))
        ),
        None,
    )
    action = next(
        (
            slide
            for slide in slides[1:]
            if any(
                term in slide.screen_content.title
                for term in ("调整", "策略", "阶段", "循环", "行动")
            )
        ),
        None,
    )
    metric_index = next(
        (
            index
            for index, slide in enumerate(slides[1:-1], start=1)
            if any(term in slide.screen_content.title for term in ("验证", "指标", "检验"))
        ),
        None,
    )
    if problem is not None and action is not None and metric_index is not None:
        target = slides[metric_index]
        original_copy = "\n".join(target.screen_content.points)
        metric = (
            target.screen_content.points[0]
            if target.screen_content.points
            else target.screen_content.title
        )
        slides[metric_index] = target.model_copy(
            update={
                "slide_type": "other",
                "screen_content": target.screen_content.model_copy(
                    update={
                        "title": "问题如何解决并验证",
                        "points": [
                            f"问题表现：{problem.screen_content.title}"[:52],
                            f"解决动作：{action.screen_content.title}"[:52],
                            f"验证指标：{metric}"[:52],
                        ],
                    }
                ),
                "teacher_note": (
                    f"{target.teacher_note.rstrip()}\n\n原验证要点：{original_copy}"
                )[:1200],
                "layout_capabilities": ["scene", "problem-solution", "sequence"],
            }
        )

    return plan.model_copy(update={"slides": slides})


def _repair_machine_contracts(
    plan: KindergartenLessonPlan,
    report: KindergartenPlanQualityReport,
) -> KindergartenLessonPlan:
    """Repair recoverable hidden contracts without a second paid model call."""
    repaired = _repair_classroom_activity_contracts(plan)
    report = validate_kindergarten_lesson_plan(repaired)
    if report.passed:
        return repaired
    if any(issue.code in CLASSROOM_CONTENT_ERRORS for issue in report.errors):
        # Never hide a pedagogical failure by removing its semantic contract.
        return repaired
    slides = list(repaired.slides)

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
        elif issue.code == "asset-caption-mismatch":
            # A provider may supply a paraphrase/title instead of an exact point.
            # Keep the lesson and visual subject, but remove that unproven pairing.
            # Classroom routing then uses a whole scene, never an arbitrary card.
            slide = slides[index]
            slides[index] = slide.model_copy(update={"assets": [
                asset.model_copy(update={"audience_text": None})
                if asset.audience_text not in slide.screen_content.points else asset
                for asset in slide.assets
            ]})

    repaired = repaired.model_copy(update={"slides": slides})

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
    content_mode: str = "classroom",
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
        content_mode=content_mode,
        disconnect_checker=disconnect_checker,
        text_chunk_callback=text_chunk_callback,
    )
    plan = _ensure_cover_contract(plan, content_mode)
    if content_mode == "training":
        plan = _normalize_training_contracts(plan)
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
