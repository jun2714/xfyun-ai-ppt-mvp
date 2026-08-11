from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

from constants.presentation import MAX_NUMBER_OF_SLIDES, MAX_OUTLINE_CONTENT_WORDS
from utils.outline_limits import normalize_outline_content


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
            "Machine-readable structure of this slide's audience-facing content. "
            "It is selection metadata, not visible slide text."
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
