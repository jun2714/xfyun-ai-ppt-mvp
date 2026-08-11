from dataclasses import dataclass
from typing import Any

from models.image_policy import ImagePolicy
from models.presentation_layout import PresentationLayoutModel
from models.presentation_structure_model import PresentationStructureModel


IMAGE_PROMPT_KEYS = {"image_prompt", "__image_prompt__"}


class LayoutCompatibilityError(ValueError):
    """Raised when the confirmed outline cannot use the available layouts safely."""

    def __init__(
        self,
        message: str,
        *,
        slide_number: int | None = None,
        contract: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.slide_number = slide_number
        self.contract = contract


def schema_contains_image_slot(value: Any) -> bool:
    if isinstance(value, dict):
        if any(key in value for key in IMAGE_PROMPT_KEYS):
            return True
        return any(schema_contains_image_slot(child) for child in value.values())
    if isinstance(value, list):
        return any(schema_contains_image_slot(child) for child in value)
    return False


@dataclass(frozen=True)
class LayoutCandidates:
    layout: PresentationLayoutModel
    original_indices: list[int]


def get_layout_candidates(
    layout: PresentationLayoutModel,
    image_policy: ImagePolicy,
) -> LayoutCandidates:
    if image_policy is ImagePolicy.DISABLED:
        original_indices = [
            index
            for index, slide in enumerate(layout.slides)
            if not schema_contains_image_slot(slide.json_schema)
        ]
    else:
        original_indices = list(range(len(layout.slides)))

    if not original_indices:
        raise LayoutCompatibilityError(
            "The selected template has no layout compatible with imagePolicy=disabled"
        )

    candidate_slides = [layout.slides[index] for index in original_indices]
    return LayoutCandidates(
        layout=PresentationLayoutModel(
            name=layout.name,
            # An ordered template is only still ordered when filtering retained every
            # layout. Otherwise its original sequence can no longer be applied safely.
            ordered=layout.ordered and len(candidate_slides) == len(layout.slides),
            icon_type=layout.icon_type,
            icon_weight=layout.icon_weight,
            slides=candidate_slides,
        ),
        original_indices=original_indices,
    )


def remap_and_validate_structure(
    structure: PresentationStructureModel,
    candidates: LayoutCandidates,
    expected_slide_count: int,
) -> PresentationStructureModel:
    if len(structure.slides) != expected_slide_count:
        raise LayoutCompatibilityError(
            "Layout selection count does not match the confirmed outline count"
        )

    candidate_count = len(candidates.original_indices)
    invalid = next(
        (
            index
            for index in structure.slides
            if index < 0 or index >= candidate_count
        ),
        None,
    )
    if invalid is not None:
        raise LayoutCompatibilityError(
            f"Layout selection returned invalid candidate index {invalid}"
        )

    return PresentationStructureModel(
        slides=[candidates.original_indices[index] for index in structure.slides]
    )

