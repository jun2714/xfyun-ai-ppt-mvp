import pytest
from pydantic import ValidationError

from models.layout_metadata import LayoutMetadata
from models.presentation_layout import PresentationLayoutModel, SlideLayoutModel
from templates.v2.models.layouts import SlideLayouts


def _metadata() -> dict:
    return {
        "capabilities": ["matching", "visual-items"],
        "contentShape": {
            "relationship": "matching",
            "minItems": 2,
            "maxItems": 4,
            "textBlocks": 3,
            "imageSlots": 4,
        },
        "media": {
            "backgroundSlots": 0,
            "framedImageSlots": 4,
            "cutoutSlots": 0,
            "required": True,
        },
        "readability": {
            "minimumFontSize": 24,
            "maximumVisibleCharacters": 90,
        },
        "qualityStatus": "passed",
    }


def test_layout_metadata_is_preserved_in_model_prompt():
    layout = PresentationLayoutModel(
        name="test",
        slides=[
            SlideLayoutModel(id="matching", json_schema={}, metadata=_metadata())
        ],
    )

    assert layout.slides[0].metadata is not None
    assert layout.slides[0].metadata.media.total_slots == 4
    assert '"matching"' in layout.to_string()
    assert '"maxItems": 4' in layout.to_string()


def test_invalid_capacity_range_is_rejected():
    metadata = _metadata()
    metadata["contentShape"]["minItems"] = 5

    with pytest.raises(ValidationError, match="maxItems"):
        LayoutMetadata.model_validate(metadata)


def test_template_layout_round_trip_preserves_metadata():
    payload = {
        "layouts": [
            {
                "id": "generic",
                "description": "A generic audited layout for round-trip testing.",
                "components": [],
                "metadata": _metadata(),
            }
        ]
    }
    dumped = SlideLayouts.model_validate(payload).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    assert dumped["layouts"][0]["metadata"]["qualityStatus"] == "passed"
    assert dumped["layouts"][0]["metadata"]["contentShape"]["maxItems"] == 4
