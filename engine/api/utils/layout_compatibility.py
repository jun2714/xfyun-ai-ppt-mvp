from dataclasses import dataclass
from typing import Any

from models.image_policy import ImagePolicy
from models.layout_metadata import LayoutMetadata
from models.presentation_layout import PresentationLayoutModel
from models.presentation_outline_model import PresentationOutlineModel, SlideContentContract
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


def _normalized_capabilities(values: list[str]) -> set[str]:
    return {
        value.strip().casefold().replace("_", "-")
        for value in values
        if isinstance(value, str) and value.strip()
    }


def _media_matches(contract: SlideContentContract, metadata: LayoutMetadata) -> bool:
    media = metadata.media
    if not contract.requires_images:
        return True
    if media.total_slots < 1:
        return False
    if contract.media_role == "background":
        return media.background_slots >= 1
    if contract.media_role == "framed-image":
        return media.framed_image_slots >= 1
    if contract.media_role == "cutout":
        return media.cutout_slots >= 1
    if contract.media_role == "mixed":
        available_roles = sum(
            count > 0
            for count in (
                media.background_slots,
                media.framed_image_slots,
                media.cutout_slots,
            )
        )
        return available_roles >= 2
    return media.total_slots >= 1


def _metadata_matches_contract(
    contract: SlideContentContract,
    metadata: LayoutMetadata,
) -> bool:
    shape = metadata.content_shape
    relationship = (shape.relationship or "").strip().casefold().replace("_", "-")
    if (
        relationship
        and contract.relationship != "unknown"
        and relationship != contract.relationship
    ):
        return False

    if contract.item_count < shape.min_items or contract.item_count > shape.max_items:
        return False
    if not _media_matches(contract, metadata):
        return False
    if contract.visible_characters > metadata.readability.maximum_visible_characters:
        return False

    preferred = _normalized_capabilities(contract.preferred_layout_capabilities)
    available = _normalized_capabilities(metadata.capabilities)
    # Capabilities are soft alternatives inside a hard-audited layout family. A
    # planner may request [question, image-text]; matching either one is useful,
    # while the relationship/media/capacity checks above remain mandatory.
    if preferred and available and not preferred.intersection(available):
        return False
    return True


def get_allowed_layout_indices_for_outline(
    presentation_outline: PresentationOutlineModel,
    presentation_layout: PresentationLayoutModel,
) -> list[list[int]] | None:
    """Build per-slide hard choices when a template carries audited metadata.

    Existing community/general templates often have no capability metadata. Those
    keep the legacy LLM layout selection unchanged. Once a template is audited,
    however, an incompatible question/matching/image/count/readability layout is
    removed *before* the LLM selects a layout. We never silently fall back from a
    fully audited template whose metadata says no layout can satisfy the contract.
    """
    audited_indices = [
        index
        for index, layout in enumerate(presentation_layout.slides)
        if layout.metadata is not None
        and layout.metadata.quality_status.strip().casefold() == "passed"
    ]
    if not audited_indices:
        return None

    all_indices = list(range(len(presentation_layout.slides)))
    allowed_by_slide: list[list[int]] = []
    for slide_number, outline_slide in enumerate(presentation_outline.slides, start=1):
        contract = outline_slide.content_contract
        if contract is None:
            allowed_by_slide.append(all_indices)
            continue

        compatible = [
            index
            for index in audited_indices
            if _metadata_matches_contract(
                contract,
                presentation_layout.slides[index].metadata,
            )
        ]
        if not compatible:
            raise LayoutCompatibilityError(
                f"Slide {slide_number} has no audited layout compatible with its content contract",
                slide_number=slide_number,
                contract=contract.model_dump(mode="json"),
            )
        allowed_by_slide.append(compatible)

    return allowed_by_slide


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
