from typing import List
from pydantic import Field
from constants.presentation import MAX_OUTLINE_CONTENT_WORDS
from models.presentation_outline_model import (
    PresentationOutlineModel,
    SlideOutlineModel,
)
from models.presentation_structure_model import PresentationStructureModel


def get_presentation_outline_model_with_n_slides(n_slides: int):
    class SlideOutlineModelWithNSlides(SlideOutlineModel):
        content: str = Field(
            description=(
                "Audience-facing Markdown content and data for the finished slide. "
                "Short question, reveal, transition and young-child teaching slides are "
                "valid; do not pad them with filler just to reach a character minimum. "
                f"Maximum {MAX_OUTLINE_CONTENT_WORDS} words."
            ),
            min_length=1,
            max_length=1200,
        )

    class PresentationOutlineModelWithNSlides(PresentationOutlineModel):
        slides: List[SlideOutlineModelWithNSlides] = Field(
            description="List of slide outlines",
            min_length=n_slides,
            max_length=n_slides,
        )

    return PresentationOutlineModelWithNSlides


def get_presentation_structure_model_with_n_slides(n_slides: int):
    class PresentationStructureModelWithNSlides(PresentationStructureModel):
        slides: List[int] = Field(
            description="List of slide layouts",
            min_length=n_slides,
            max_length=n_slides,
        )

    return PresentationStructureModelWithNSlides
