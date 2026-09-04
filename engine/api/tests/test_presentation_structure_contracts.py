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
    _repair_generated_structure,
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
                    teaching_goal="通过局部特征识别小兔子",
                    required_asset_semantics=["小兔子的两只长耳朵"],
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
                json_schema={
                    "type": "object",
                    "properties": {
                        "image": {
                            "type": "object",
                            "properties": {
                                "image_prompt": {"type": "string"}
                            },
                        }
                    },
                },
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


def test_invalid_model_choice_is_repaired_without_changing_valid_pages():
    original = PresentationStructureModel(slides=[0, 1, 3, 5])
    allowed = [[0, 1], [0, 1], [0, 1, 2, 5, 7], [5, 7]]
    result = _repair_generated_structure(original, allowed)
    assert result.slides == [0, 1, 2, 5]
    assert original.slides == [0, 1, 3, 5]
    assert all(index in choices for index, choices in zip(result.slides, allowed))


def test_repair_does_not_hide_empty_candidates_or_wrong_page_counts():
    with pytest.raises(LayoutCompatibilityError, match="no allowed layout"):
        _repair_generated_structure(PresentationStructureModel(slides=[3]), [[]])
    with pytest.raises(LayoutCompatibilityError, match="count"):
        _repair_generated_structure(PresentationStructureModel(slides=[0, 1]), [[0]])


def test_generation_repairs_disallowed_provider_selection_in_one_call(monkeypatch):
    from utils.llm_calls import generate_presentation_structure as module

    calls = []

    async def generate(*args, **kwargs):
        calls.append(kwargs)
        return {"slides": [3]}

    monkeypatch.setattr(module, "get_client", lambda **kwargs: object())
    monkeypatch.setattr(module, "get_llm_config", lambda: {})
    monkeypatch.setattr(module, "get_model", lambda: "test-model")
    monkeypatch.setattr(module, "generate_structured_with_schema_retries", generate)
    layout = _layout()
    layout.slides.append(layout.slides[0].model_copy(update={"id": "second-compatible"}))
    result = asyncio.run(generate_presentation_structure(_outline(), layout, allowed_layout_indices=[[0, 1]]))
    assert result.slides == [0]
    assert len(calls) == 1
