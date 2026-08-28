from models.presentation_outline_model import PresentationOutlineModel
from services.kindergarten_visual_planning_service import (
    apply_ai_background_visual_plan,
    get_kindergarten_visual_style_summary,
)


def _outline() -> PresentationOutlineModel:
    return PresentationOutlineModel.model_validate(
        {
            "slides": [
                {
                    "content": "# 森林动物大冒险\n一起去森林里找朋友。",
                    "content_contract": {
                        "relationship": "single",
                        "requires_images": True,
                        "media_role": "framed-image",
                        "required_asset_semantics": ["完整亚洲象"],
                        "asset_contracts": [
                            {
                                "planning_slot": "animal",
                                "semantic_label": "完整亚洲象",
                                "description": "完整亚洲象，全身清楚。",
                                "expected_count": 1,
                                "role": "framed-image",
                                "qa_required": True,
                            }
                        ],
                        "preferred_layout_capabilities": ["single-focus"],
                    },
                },
                {
                    "content": "# 猜一猜\n谁有长长的鼻子？",
                    "content_contract": {
                        "relationship": "question",
                        "interaction_type": "guess",
                        "activity_id": "animal-guess-1",
                        "answer_key": "大象",
                    },
                },
            ]
        }
    )


def test_ai_background_plan_keeps_visible_copy_and_existing_assets():
    source = _outline()
    planned = apply_ai_background_visual_plan(
        source,
        topic="森林动物大冒险",
        domain="science",
        visual_style_hint="自然温馨",
    )

    assert [slide.content for slide in planned.slides] == [
        slide.content for slide in source.slides
    ]
    first = planned.slides[0].content_contract
    assert first is not None
    assert first.media_role == "mixed"
    assert any(asset.semantic_label == "完整亚洲象" for asset in first.asset_contracts)
    assert first.asset_contracts[0].role == "background"
    assert first.asset_contracts[0].planning_slot == "ai_background"
    assert "16:9" in (first.asset_contracts[0].description or "")
    assert "自然温馨" in (first.asset_contracts[0].description or "")
    assert "不得出现任何文字" in (first.asset_contracts[0].description or "")
    assert "知名IP" in (first.asset_contracts[0].description or "")


def test_each_slide_gets_unique_background_semantic_and_safe_scene():
    planned = apply_ai_background_visual_plan(
        _outline(),
        topic="森林动物大冒险",
        domain="science",
    )
    semantics = [
        slide.content_contract.asset_contracts[0].semantic_label
        for slide in planned.slides
        if slide.content_contract is not None
    ]

    assert len(semantics) == 2
    assert len(set(semantics)) == 2
    assert all(
        semantic in slide.content_contract.required_asset_semantics
        for semantic, slide in zip(semantics, planned.slides)
        if slide.content_contract is not None
    )
    question_description = planned.slides[1].content_contract.asset_contracts[0].description or ""
    assert "避免提前暴露答案" in question_description


def test_domain_style_bible_changes_with_teaching_domain():
    science = get_kindergarten_visual_style_summary(domain="science")
    language = get_kindergarten_visual_style_summary(domain="language")

    assert science != language
    assert "探索" in science
    assert "故事" in language
