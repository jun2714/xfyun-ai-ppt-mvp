from models.layout_metadata import LayoutMetadata
from templates.v2.derivation import (
    AssetSlotSpec,
    CuratedLayoutSpec,
    EditableFieldSpec,
    derive_template_layouts_without_model,
)
from templates.v2.models.layouts import RawSlideLayout


def _metadata() -> LayoutMetadata:
    return LayoutMetadata.model_validate(
        {
            "capabilities": ["single-focus"],
            "contentShape": {
                "minItems": 1,
                "maxItems": 1,
                "textBlocks": 1,
                "imageSlots": 1,
            },
            "media": {"framedImageSlots": 1, "required": False},
            "readability": {
                "minimumFontSize": 24,
                "maximumVisibleCharacters": 40,
            },
            "qualityStatus": "pending",
        }
    )


def test_derives_only_explicitly_curated_fields_without_a_model_call():
    raw = RawSlideLayout.model_validate(
        {
            "id": "slide_1",
            "description": "Imported source slide",
            "elements": [
                {
                    "type": "text",
                    "position": {"x": 100, "y": 80},
                    "size": {"width": 500, "height": 80},
                    "runs": [{"text": "Source title"}],
                    "decorative": True,
                    "name": "source_title",
                    "min_length": 1,
                    "max_length": 40,
                },
                {
                    "type": "image",
                    "position": {"x": 700, "y": 120},
                    "size": {"width": 400, "height": 400},
                    "data": "/source.png",
                    "decorative": True,
                    "name": "source_photo",
                    "is_icon": False,
                },
            ],
        }
    )
    spec = CuratedLayoutSpec(
        sourceIndex=0,
        id="title_with_visual",
        description="Large title with one replaceable visual on the right.",
        metadata=_metadata(),
        editableFields=[
            EditableFieldSpec(
                sourceName="source_title",
                name="title",
                fontSize=64,
                fontFamily="Microsoft YaHei",
                maxLength=12,
            )
        ],
        assetSlots=[
            AssetSlotSpec(
                sourceName="source_photo",
                name="main_visual",
                role="framed-image",
                aspectRatio="1:1",
                required=False,
            )
        ],
    )

    layouts, merged, indexes = derive_template_layouts_without_model([raw], [spec])

    layout = layouts.layouts[0]
    assert indexes == [0]
    assert len(merged.components) == 1
    assert layout.metadata is not None
    title, image = layout.components[0].elements
    assert title.name == "title" and title.decorative is False
    assert title.font is not None and title.font.size == 64
    assert title.font.family == "Microsoft YaHei"
    assert title.max_length == 12 and title.min_length == 6
    assert image.name == "main_visual" and image.decorative is False
    assert image.asset_role == "framed-image"


def test_rejects_missing_curated_source_element():
    raw = RawSlideLayout.model_validate(
        {
            "id": "slide_1",
            "description": "Imported source slide",
            "elements": [
                {
                    "type": "text",
                    "runs": [{"text": "Source title"}],
                    "decorative": True,
                    "name": "source_title",
                    "min_length": 1,
                    "max_length": 40,
                }
            ],
        }
    )
    spec = CuratedLayoutSpec(
        sourceIndex=0,
        id="title_only",
        description="A concise title-only layout for section transitions.",
        metadata=_metadata(),
        editableFields=[EditableFieldSpec(sourceName="missing", name="title")],
    )

    try:
        derive_template_layouts_without_model([raw], [spec])
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("missing source element should fail")


def test_duplicate_imported_name_selects_the_requested_semantic_type():
    raw = RawSlideLayout.model_validate(
        {
            "id": "slide_1",
            "description": "Imported source slide with duplicate OOXML names",
            "elements": [
                {
                    "type": "image",
                    "data": "/decorative.svg",
                    "decorative": True,
                    "name": "duplicated_source_name",
                    "is_icon": False,
                },
                {
                    "type": "text",
                    "runs": [{"text": "Editable label"}],
                    "decorative": True,
                    "name": "duplicated_source_name",
                    "min_length": 1,
                    "max_length": 20,
                },
            ],
        }
    )
    spec = CuratedLayoutSpec(
        sourceIndex=0,
        id="duplicate_name_layout",
        description="A layout proving semantic type selection for duplicate names.",
        metadata=_metadata(),
        editableFields=[
            EditableFieldSpec(
                sourceName="duplicated_source_name",
                name="title",
                fontSize=40,
                maxLength=12,
            )
        ],
    )

    layouts, _, _ = derive_template_layouts_without_model([raw], [spec])

    image, title = layouts.layouts[0].components[0].elements
    assert image.decorative is True
    assert image.name == "duplicated_source_name"
    assert title.decorative is False
    assert title.name == "title"
