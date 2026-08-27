import asyncio

import pytest

from models.presentation_layout import PresentationLayoutModel, SlideLayoutModel
from models.presentation_outline_model import (
    PresentationOutlineModel,
    SlideContentContract,
    SlideOutlineModel,
)
from models.presentation_structure_model import PresentationStructureModel
from utils.layout_compatibility import LayoutCompatibilityError
from utils.llm_calls.generate_presentation_structure import (
    _validate_structure_against_allowed_layouts,
    generate_presentation_structure,
)


def _metadata() -> dict:
    return {
        "capabilities": ["question", "image-text"],
        "contentShape": {
            "relationship": "question",
            "minItems": 1,
            "maxItems": 3,
            "textBlocks": 2,
            "imageSlots": 1,
        },
        "media": {
            "backgroundSlots": 0,
            "framedImageSlots": 1,
            "cutoutSlots": 0,
            "required": True,
        },
        "readability": {
            "minimumFontSize": 24,
            "maximumVisibleCharacters": 90,
        },
        "qualityStatus": "passed",
    }


def _outline() -> PresentationOutlineModel:
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
                    preferred_layout_capabilities=["question"],
                ),
            )
        ]
    )


def _layout() -> PresentationLayoutModel:
    return PresentationLayoutModel(
        name="audited-kindergarten",
        slides=[
            SlideLayoutModel(
                id="question-image",
                json_schema={"type": "object", "properties": {}},
                metadata=_metadata(),
            )
        ],
    )


def test_structure_generation_uses_single_audited_choice_without_llm_call():
    structure = asyncio.run(
        generate_presentation_structure(
            presentation_outline=_outline(),
            presentation_layout=_layout(),
        )
    )

    assert structure.slides == [0]


def test_generated_structure_cannot_escape_hard_layout_choices():
    with pytest.raises(LayoutCompatibilityError, match="outside allowed choices"):
        _validate_structure_against_allowed_layouts(
            PresentationStructureModel(slides=[1]),
            [[0]],
        )
