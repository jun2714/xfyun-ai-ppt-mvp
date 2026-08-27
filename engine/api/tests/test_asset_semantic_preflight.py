import pytest

from models.sql.slide import SlideModel
from services.asset_planning_service import (
    AssetSemanticCoverageError,
    build_asset_plan,
)


def _slide(content: dict) -> SlideModel:
    return SlideModel(
        presentation="00000000-0000-0000-0000-000000000001",
        layout_group="test",
        layout="test",
        index=0,
        content=content,
        ui={
            "components": [
                {
                    "id": "main",
                    "elements": [
                        {
                            "type": "image",
                            "name": "item_1",
                            "position": {"x": 100, "y": 100},
                            "size": {"width": 300, "height": 300},
                        },
                        {
                            "type": "image",
                            "name": "item_2",
                            "position": {"x": 450, "y": 100},
                            "size": {"width": 300, "height": 300},
                        },
                    ],
                }
            ]
        },
    )


def test_semantic_contract_allows_matching_prompts():
    slide = _slide(
        {
            "main": {
                "item_1": {"image_prompt": "红苹果，单个主体，白色背景"},
                "item_2": {"image_prompt": "橙色胡萝卜，单个主体，白色背景"},
            },
            "__content_contract__": {
                "required_asset_semantics": ["红苹果", "橙色胡萝卜"]
            },
        }
    )

    plan = build_asset_plan([slide])

    assert len(plan) == 2


def test_semantic_contract_blocks_unrelated_prompts_before_paid_generation():
    slide = _slide(
        {
            "main": {
                "item_1": {"image_prompt": "一盏路灯，夜晚城市背景"},
                "item_2": {"image_prompt": "一台电视机，客厅场景"},
            },
            "__content_contract__": {
                "required_asset_semantics": ["红苹果", "橙色胡萝卜"]
            },
        }
    )

    with pytest.raises(AssetSemanticCoverageError) as exc_info:
        build_asset_plan([slide])

    message = str(exc_info.value)
    assert "红苹果" in message
    assert "橙色胡萝卜" in message
    assert "调用图片模型前阻断" in message


def test_completed_slide_is_not_reblocked_when_no_asset_is_pending():
    slide = _slide(
        {
            "main": {
                "item_1": {
                    "image_prompt": "红苹果，单个主体",
                    "image_url": "https://example.com/apple.png",
                },
                "item_2": {
                    "image_prompt": "橙色胡萝卜，单个主体",
                    "image_url": "https://example.com/carrot.png",
                },
            },
            "__content_contract__": {
                "required_asset_semantics": ["红苹果", "橙色胡萝卜"]
            },
        }
    )

    assert build_asset_plan([slide]) == []
