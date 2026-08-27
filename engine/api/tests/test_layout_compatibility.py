import pytest

from models.image_policy import ImagePolicy
from models.presentation_layout import PresentationLayoutModel, SlideLayoutModel
from models.presentation_outline_model import (
    PresentationOutlineModel,
    SlideContentContract,
    SlideOutlineModel,
)
from models.presentation_structure_model import PresentationStructureModel
from utils.layout_compatibility import (
    LayoutCompatibilityError,
    get_allowed_layout_indices_for_outline,
    get_layout_candidates,
    remap_and_validate_structure,
    schema_contains_chart_slot,
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


def _chart_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "chart": {
                "type": "object",
                "properties": {
                    "chart_type": {"type": "string"},
                    "labels": {"type": "array"},
                    "series": {"type": "array"},
                },
            }
        },
    }


def _audited_metadata(
    *,
    relationship: str,
    capabilities: list[str],
    min_items: int = 0,
    max_items: int = 4,
    framed_images: int = 0,
    background_images: int = 0,
    maximum_visible_characters: int = 120,
) -> dict:
    return {
        "capabilities": capabilities,
        "contentShape": {
            "relationship": relationship,
            "minItems": min_items,
            "maxItems": max_items,
            "textBlocks": 2,
            "imageSlots": framed_images + background_images,
        },
        "media": {
            "backgroundSlots": background_images,
            "framedImageSlots": framed_images,
            "cutoutSlots": 0,
            "required": framed_images + background_images > 0,
        },
        "readability": {
            "minimumFontSize": 24,
            "maximumVisibleCharacters": maximum_visible_characters,
        },
        "qualityStatus": "passed",
    }


def _question_outline() -> PresentationOutlineModel:
    return PresentationOutlineModel(
        slides=[
            SlideOutlineModel(
                content="猜猜是谁？\n- 谁有长长的耳朵？",
                content_contract=SlideContentContract(
                    relationship="question",
                    item_count=2,
                    requires_images=True,
                    media_role="framed-image",
                    visible_characters=18,
                    preferred_layout_capabilities=["question", "image-text"],
                ),
            )
        ]
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


def test_chart_schema_detection_handles_generated_chart_contract():
    assert schema_contains_chart_slot(_chart_schema()) is True
    assert schema_contains_chart_slot({"properties": {"title": {"type": "string"}}}) is False


def test_kindergarten_template_family_excludes_legacy_chart_layouts():
    layout = PresentationLayoutModel(
        name="dynamic",
        slides=[
            SlideLayoutModel(id="chart", json_schema=_chart_schema()),
            SlideLayoutModel(
                id="image-text",
                json_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "image": {
                            "properties": {"image_prompt": {"type": "string"}}
                        },
                    },
                },
            ),
        ],
    )

    assert layout.allow_charts is False
    candidates = get_layout_candidates(layout, ImagePolicy.STANDARD)
    assert [slide.id for slide in candidates.layout.slides] == ["image-text"]
    assert candidates.original_indices == [1]


def test_adult_or_general_template_keeps_chart_layouts():
    for template_name in ("executive", "general", "custom-school-report"):
        layout = PresentationLayoutModel(
            name=template_name,
            slides=[SlideLayoutModel(id="chart", json_schema=_chart_schema())],
        )
        assert layout.allow_charts is True
        candidates = get_layout_candidates(layout, ImagePolicy.STANDARD)
        assert [slide.id for slide in candidates.layout.slides] == ["chart"]


def test_explicit_chart_override_wins_over_kindergarten_family_default():
    layout = PresentationLayoutModel(
        name="dynamic",
        allow_charts=True,
        slides=[SlideLayoutModel(id="chart", json_schema=_chart_schema())],
    )

    assert layout.allow_charts is True
    assert [
        slide.id for slide in get_layout_candidates(layout, ImagePolicy.STANDARD).layout.slides
    ] == ["chart"]


def test_audited_layouts_are_filtered_by_hidden_slide_contract():
    layout = PresentationLayoutModel(
        name="kindergarten-audited",
        slides=[
            SlideLayoutModel(
                id="question-image",
                json_schema={},
                metadata=_audited_metadata(
                    relationship="question",
                    capabilities=["question", "image-text"],
                    min_items=1,
                    max_items=3,
                    framed_images=1,
                ),
            ),
            SlideLayoutModel(
                id="single-text",
                json_schema={},
                metadata=_audited_metadata(
                    relationship="single",
                    capabilities=["single", "text"],
                    min_items=0,
                    max_items=2,
                ),
            ),
        ],
    )

    allowed = get_allowed_layout_indices_for_outline(_question_outline(), layout)

    assert allowed == [[0]]


def test_templates_without_audited_metadata_keep_legacy_selection():
    assert get_allowed_layout_indices_for_outline(_question_outline(), _layout()) is None


def test_audited_template_without_compatible_layout_fails_before_generation():
    layout = PresentationLayoutModel(
        name="kindergarten-audited",
        slides=[
            SlideLayoutModel(
                id="question-no-image",
                json_schema={},
                metadata=_audited_metadata(
                    relationship="question",
                    capabilities=["question"],
                    min_items=1,
                    max_items=3,
                    framed_images=0,
                ),
            )
        ],
    )

    with pytest.raises(LayoutCompatibilityError) as exc_info:
        get_allowed_layout_indices_for_outline(_question_outline(), layout)

    assert exc_info.value.slide_number == 1
    assert "no audited layout compatible" in str(exc_info.value)
