from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from models.presentation_outline_model import (
    PresentationOutlineModel,
    SlideContentContract,
    SlideOutlineModel,
)


KindergartenDomain = Literal[
    "science",
    "language",
    "math",
    "health",
    "social",
    "art",
    "comprehensive",
]

KindergartenSlideType = Literal[
    "cover-scene",
    "story-intro",
    "knowledge-single",
    "image-observation",
    "compare",
    "guess-partial",
    "guess-shadow",
    "answer-reveal",
    "memory-show",
    "memory-missing",
    "matching",
    "classification",
    "sequence",
    "recap",
    "ending-scene",
    "other",
]

KindergartenInteractionType = Literal[
    "none",
    "observe",
    "imitate",
    "choose",
    "guess",
    "match",
    "classify",
    "sequence",
    "discuss",
    "move",
    "recall",
]


class LessonMeta(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    age_group: str = Field(min_length=1, max_length=40)
    domain: KindergartenDomain = "comprehensive"
    duration_minutes: int = Field(default=20, ge=5, le=90)


class ScreenContent(BaseModel):
    section: Optional[str] = Field(default=None, max_length=80)
    title: str = Field(min_length=1, max_length=80)
    points: List[str] = Field(default_factory=list, max_length=6)
    instruction: Optional[str] = Field(default=None, max_length=120)


class LessonInteraction(BaseModel):
    type: KindergartenInteractionType = "none"
    instruction: Optional[str] = Field(default=None, max_length=180)


class LessonAssetSpec(BaseModel):
    slot: str = Field(min_length=1, max_length=80)
    semantic_label: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=800)
    required: bool = True
    expected_count: int = Field(default=1, ge=1, le=12)
    role: Literal["background", "framed-image", "cutout"] = "framed-image"
    qa_required: bool = True


class LessonGameSpec(BaseModel):
    type: Literal[
        "guess",
        "memory",
        "matching",
        "classification",
        "sequence",
        "choice",
    ]
    activity_id: str = Field(min_length=1, max_length=120)
    question: Optional[str] = Field(default=None, max_length=200)
    answer_key: Optional[str] = Field(default=None, max_length=300)
    options: Dict[str, str] = Field(default_factory=dict)
    answer_map: Dict[str, str] = Field(default_factory=dict)
    sequence_order: List[str] = Field(default_factory=list, max_length=12)


class KindergartenSlidePlan(BaseModel):
    slide_no: int = Field(ge=1, le=100)
    slide_type: KindergartenSlideType
    teaching_goal: str = Field(min_length=1, max_length=300)
    screen_content: ScreenContent
    interaction: LessonInteraction = Field(default_factory=LessonInteraction)
    teacher_note: str = Field(min_length=1, max_length=1200)
    assets: List[LessonAssetSpec] = Field(default_factory=list, max_length=12)
    game: Optional[LessonGameSpec] = None
    layout_capabilities: List[str] = Field(default_factory=list, max_length=8)


class KindergartenLessonPlan(BaseModel):
    meta: LessonMeta
    lesson_goals: List[str] = Field(min_length=1, max_length=6)
    lesson_arc: List[str] = Field(min_length=1, max_length=20)
    slides: List[KindergartenSlidePlan] = Field(min_length=1, max_length=40)

    @model_validator(mode="after")
    def validate_slide_numbers(self):
        expected = list(range(1, len(self.slides) + 1))
        actual = [slide.slide_no for slide in self.slides]
        if actual != expected:
            raise ValueError(
                "slide_no must be sequential and one-based: "
                f"expected {expected}, got {actual}"
            )
        return self

    def to_presentation_outline(self) -> PresentationOutlineModel:
        slides: list[SlideOutlineModel] = []
        for slide in self.slides:
            visible_lines: list[str] = [slide.screen_content.title]
            visible_lines.extend(f"- {point}" for point in slide.screen_content.points)
            if slide.screen_content.instruction:
                visible_lines.append(slide.screen_content.instruction)

            relationship = _relationship_for_slide(slide)
            required_semantics = [
                asset.semantic_label for asset in slide.assets if asset.required
            ]
            answer_key = slide.game.answer_key if slide.game else None
            activity_id = slide.game.activity_id if slide.game else None

            slides.append(
                SlideOutlineModel(
                    content="\n".join(visible_lines),
                    content_contract=SlideContentContract(
                        relationship=relationship,
                        item_count=max(
                            len(slide.screen_content.points),
                            len(slide.game.options) if slide.game else 0,
                            len(slide.game.answer_map) if slide.game else 0,
                        ),
                        requires_images=bool(required_semantics),
                        media_role=_media_role_for_assets(slide.assets),
                        visible_characters=len("".join(visible_lines)),
                        teaching_goal=slide.teaching_goal,
                        teacher_note=slide.teacher_note,
                        interaction_type=slide.interaction.type,
                        activity_id=activity_id,
                        answer_key=answer_key,
                        required_asset_semantics=required_semantics,
                    ),
                )
            )
        return PresentationOutlineModel(slides=slides)


def _relationship_for_slide(slide: KindergartenSlidePlan):
    if slide.slide_type in {"guess-partial", "guess-shadow"}:
        return "question"
    if slide.slide_type == "answer-reveal":
        return "reveal"
    if slide.slide_type == "matching":
        return "matching"
    if slide.slide_type == "classification":
        return "classification"
    if slide.slide_type == "sequence":
        return "sequence"
    if slide.slide_type == "compare":
        return "comparison"
    if slide.slide_type in {"cover-scene", "story-intro", "ending-scene"}:
        return "story"
    if len(slide.screen_content.points) > 1:
        return "multi-item"
    return "single"


def _media_role_for_assets(assets: List[LessonAssetSpec]):
    roles = {asset.role for asset in assets if asset.required}
    if not roles:
        return "none"
    if len(roles) > 1:
        return "mixed"
    return next(iter(roles))
