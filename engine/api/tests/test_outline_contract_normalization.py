from models.presentation_outline_model import SlideContentContract


def test_unknown_provider_relationship_degrades_without_business_mapping():
    contract = SlideContentContract.model_validate(
        {
            "relationship": "decision",
            "item_count": 1,
            "requires_images": False,
            "media_role": "none",
            "visible_characters": 20,
        }
    )

    assert contract.relationship == "unknown"


def test_relationship_normalization_accepts_schema_spelling_variation():
    contract = SlideContentContract.model_validate(
        {"relationship": " Multi_Item ", "item_count": 3}
    )

    assert contract.relationship == "multi-item"
