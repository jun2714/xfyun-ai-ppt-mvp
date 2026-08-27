from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from enums.tone import Tone
from enums.verbosity import Verbosity
from models.image_policy import ImagePolicy


class GeneratePresentationRequest(BaseModel):
    content: str = Field(..., description="The content for generating the presentation")
    slides_markdown: Optional[List[str]] = Field(
        default=None, description="The markdown for the slides"
    )
    instructions: Optional[str] = Field(
        default=None, description="The instruction for generating the presentation"
    )
    tone: Tone = Field(default=Tone.DEFAULT, description="The tone to use for the text")
    verbosity: Verbosity = Field(
        default=Verbosity.STANDARD, description="How verbose the presentation should be"
    )
    web_search: bool = Field(default=False, description="Whether to enable web search")
    n_slides: Optional[int] = Field(
        default=None,
        description="Number of slides to generate. If omitted, model auto-detects slide count.",
    )
    language: Optional[str] = Field(
        default=None,
        description="Language for the presentation. If omitted, model auto-detects language.",
    )
    template: str = Field(
        default="general", description="Template to use for the presentation"
    )
    include_table_of_contents: bool = Field(
        default=False, description="Whether to include a table of contents"
    )
    include_title_slide: bool = Field(
        default=True, description="Whether to include a title slide"
    )
    files: Optional[List[str]] = Field(
        default=None, description="Files to use for the presentation"
    )
    export_as: Literal["pptx", "pdf"] = Field(
        default="pptx", description="Export format"
    )
    trigger_webhook: bool = Field(
        default=False, description="Whether to trigger subscribed webhooks"
    )
    image_policy: ImagePolicy = Field(
        default=ImagePolicy.STANDARD,
        description="Whether images are disabled, minimized, or generated normally",
    )

    # `presentation_mode` is deliberately separate from the persisted
    # standard/smart generation mode. It selects the content-planning contract
    # used before layout generation while keeping existing API requests backward
    # compatible.
    presentation_mode: Literal["general", "kindergarten"] = Field(
        default="general",
        description=(
            "Content planning mode. Kindergarten mode creates a structured lesson "
            "plan with teaching, interaction, game-answer, and image-semantic contracts "
            "before normal slide/layout generation."
        ),
    )
    kindergarten_age_group: str = Field(
        default="4-5岁",
        min_length=1,
        max_length=40,
        description="Target kindergarten age group when presentation_mode=kindergarten",
    )
    kindergarten_domain: Literal[
        "science",
        "language",
        "math",
        "health",
        "social",
        "art",
        "comprehensive",
    ] = Field(
        default="comprehensive",
        description="Kindergarten curriculum domain",
    )
    kindergarten_duration_minutes: int = Field(
        default=20,
        ge=5,
        le=90,
        description="Lesson duration when presentation_mode=kindergarten",
    )
