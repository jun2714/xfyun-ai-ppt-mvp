from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

from constants.presentation import MAX_NUMBER_OF_SLIDES, MAX_OUTLINE_CONTENT_WORDS
from utils.outline_limits import normalize_outline_content


class SlideAssetContract(BaseModel):
    """Hidden requirements for one planned visual asset.

    `planning_slot` is a semantic planning handle, not a template element id. The
    content generation stage is free to map it to any compatible image field; later
    stages correlate the contract by the semantic phrase present in image prompts.
    """

    planning_slot: str = Field(min_length=1, max_length=80)
    semantic_label: str = Field(min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=800)
    expected_count: int = Field(default=1, ge=1, le=12)
    role: Literal["background", "framed-image", "cutout"] = "framed-image"
    qa_required: bool = True

    @field_validator("planning_slot", "semantic_label", mode="before")
    @classmethod
    def normalize_required_text(cls, value):
        if not isinstance(value, str):
            return value
        return " ".join(value.strip().split())


class SlideContentContract(BaseModel):
    relationship: Literal[
        "single",
        "multi-item",
        "comparison",
        "sequence",
        "classification",
        "matching",
        "question",
        "reveal",
        "story",
        "data",
        "unknown",
    ] = "unknown"
    item_count: int = Field(default=0, ge=0, le=12)
    requires_images: bool = False
    media_role: Literal[
        "none", "background", "framed-image", "cutout", "mixed"
    ] = "none"
    visible_characters: int = Field(default=0, ge=0)

    # Optional teaching metadata. These fields never become audience-facing text;
    # they travel with the outline so later layout, asset and quality stages can
    # preserve the lesson intent without re-inferring it from rendered copy.
    teaching_goal: Optional[str] = Field(default=None, max_length=300)
    teacher_note: Optional[str] = Field(default=None, max_length=1200)
    interaction_type: Literal[
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
        "unknown",
    ] = "none"
    activity_id: Optional[str] = Field(default=None, max_length=120)
    answer_key: Optional[str] = Field(default=None, max_length=300)
    # Lesson planning normally needs far fewer than twelve assets. The extra four
    # slots are deliberately reserved for presentation-stage visual contracts such
    # as an AI-generated background, without discarding teaching-object semantics.
    required_asset_semantics: List[str] = Field(default_factory=list, max_length=16)
    asset_contracts: List[SlideAssetContract] = Field(default_factory=list, max_length=16)
    preferred_layout_capabilities: List[str] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "Hidden semantic layout preferences such as question, reveal, scene, "
            "matching, classification, sequence, image-text, or recap. These are "
            "capability hints, never template ids."
        ),
    )

    @field_validator("relationship", mode="before")
    @classmethod
    def normalize_unrecognized_relationship(cls, value):
        """Keep provider vocabulary drift from invalidating a paid outline.

        Relationships are a closed machine contract, not business-page roles.
        We deliberately do not maintain a growing synonym map: a provider value
        outside the contract loses its semantic hint and is selected only by
        the remaining capacity and media constraints.
        """
        if not isinstance(value, str):
            return "unknown"
        normalized = value.strip().casefold().replace("_", "-")
        allowed = {
            "single",
            "multi-item",
            "comparison",
            "sequence",
            "classification",
            "matching",
            "question",
            "reveal",
            "story",
            "data",
            "unknown",
        }
        return normalized if normalized in allowed else "unknown"

    @field_validator("interaction_type", mode="before")
    @classmethod
    def normalize_unrecognized_interaction(cls, value):
        if not isinstance(value, str):
            return "unknown"
        normalized = value.strip().casefold().replace("_", "-")
        allowed = {
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
            "unknown",
        }
        return normalized if normalized in allowed else "unknown"

    @field_validator(
        "required_asset_semantics",
        "preferred_layout_capabilities",
        mode="before",
    )
    @classmethod
    def normalize_unique_string_list(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        seen: set[str] = set()
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            label = " ".join(item.strip().split())
            key = label.casefold()
            if not label or key in seen:
                continue
            seen.add(key)
            normalized.append(label)
        return normalized[:16]


class SlideOutlineModel(BaseModel):
    content: str = Field(
        ...,
        description=(
            "Audience-facing Markdown content and data for the finished slide; never "
            "slide-creation commands, visual/layout configuration, styling notes, or "
            f"model instructions. Maximum {MAX_OUTLINE_CONTENT_WORDS} words."
        ),
    )
    content_contract: Optional[SlideContentContract] = Field(
        default=None,
        description=(
            "Machine-readable structure and optional teaching intent for this slide. "
            "It is selection/quality metadata, not visible slide text."
        ),
    )

    @field_validator("content", mode="before")
    @classmethod
    def limit_content_words(cls, value):
        return normalize_outline_content(value)


class PresentationOutlineModel(BaseModel):
    slides: List[SlideOutlineModel] = Field(
        description="List of slide outlines",
        max_length=MAX_NUMBER_OF_SLIDES,
    )

    def to_string(self):
        message = ""
        for i, slide in enumerate(self.slides):
            message += f"## Slide {i+1}:\n"
            message += f"  - Content: {slide} \n"
        return message
