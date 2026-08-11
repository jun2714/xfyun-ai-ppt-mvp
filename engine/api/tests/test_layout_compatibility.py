import pytest

from models.image_policy import ImagePolicy
from models.presentation_layout import PresentationLayoutModel, SlideLayoutModel
from models.presentation_structure_model import PresentationStructureModel
from utils.layout_compatibility import (
    LayoutCompatibilityError,
    get_layout_candidates,
    remap_and_validate_structure,
)


def _layout() -> PresentationLayoutModel:
    return PresentationLayoutModel(
        name="test",
        slides=[
            SlideLayoutModel(
                id="visual",
                json_schema={
                    "type": "object",
                    "properties": {
                        "image": {
                            "properties": {"image_prompt": {"type": "string"}}
                        }
                    },
                },
            ),
            SlideLayoutModel(
                id="text",
                json_schema={
                    "type": "object",
                    "properties": {"title": {"type": "string"}},
                },
            ),
        ],
    )


def test_disabled_policy_excludes_layouts_with_image_slots():
    candidates = get_layout_candidates(_layout(), ImagePolicy.DISABLED)

    assert [slide.id for slide in candidates.layout.slides] == ["text"]
    assert candidates.original_indices == [1]
    assert remap_and_validate_structure(
        PresentationStructureModel(slides=[0]), candidates, 1
    ).slides == [1]


def test_invalid_layout_index_is_rejected_instead_of_randomly_replaced():
    candidates = get_layout_candidates(_layout(), ImagePolicy.STANDARD)

    with pytest.raises(LayoutCompatibilityError, match="invalid candidate index"):
        remap_and_validate_structure(
            PresentationStructureModel(slides=[2]), candidates, 1
        )


def test_layout_selection_count_must_match_confirmed_outline():
    candidates = get_layout_candidates(_layout(), ImagePolicy.STANDARD)

    with pytest.raises(LayoutCompatibilityError, match="outline count"):
        remap_and_validate_structure(
            PresentationStructureModel(slides=[0]), candidates, 2
        )
