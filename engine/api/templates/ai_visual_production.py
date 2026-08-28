from __future__ import annotations

from models.sql.template_v2 import TemplateV2
from templates.ai_visual_default import (
    AI_VISUAL_TEMPLATE_ID,
    _background,
    _component,
    _layouts,
    _metadata,
    _panel,
    _text,
)
from templates.v2.models.layouts import SlideLayouts


def _comparison_layout() -> dict:
    return {
        "id": "ai_compare",
        "description": "AI自由视觉双栏比较页，在统一背景上放置两个并列观察卡，适合找不同和特征比较。",
        "components": [
            _component(
                "background",
                "全屏生成比较场景，主体尽量分居左右并保持中央低细节。",
                [_background(safe="center")],
            ),
            _component(
                "content",
                "顶部标题和左右两个比较卡，文字量克制且关系一眼可见。",
                [
                    _panel(180, 55, 920, 84, _text("title", 884, 60, 36, 30)),
                    _panel(
                        80,
                        410,
                        520,
                        190,
                        _text(
                            "left_item",
                            484,
                            166,
                            27,
                            70,
                            color="#2A6F62",
                            align="left",
                        ),
                    ),
                    _panel(
                        680,
                        410,
                        520,
                        190,
                        _text(
                            "right_item",
                            484,
                            166,
                            27,
                            70,
                            color="#355C7D",
                            align="left",
                        ),
                    ),
                ],
            ),
        ],
        "metadata": _metadata(
            ["scene", "compare", "comparison", "observation", "image-text"],
            "comparison",
            3,
            max_chars=150,
        ),
    }


def _sequence_layout() -> dict:
    return {
        "id": "ai_sequence",
        "description": "AI自由视觉三步过程页，在统一背景上用大字号步骤卡表现先后顺序和动作过程。",
        "components": [
            _component(
                "background",
                "全屏生成过程场景，背景具有轻微方向感但不绘制文字或数字。",
                [_background(safe="center")],
            ),
            _component(
                "content",
                "顶部标题和三个横向步骤卡，适合实验、生活技能和课堂动作流程。",
                [
                    _panel(180, 55, 920, 84, _text("title", 884, 60, 36, 30)),
                    _panel(
                        70,
                        390,
                        350,
                        180,
                        _text(
                            "step_1",
                            314,
                            156,
                            26,
                            60,
                            color="#2A6F62",
                        ),
                    ),
                    _panel(
                        465,
                        390,
                        350,
                        180,
                        _text(
                            "step_2",
                            314,
                            156,
                            26,
                            60,
                            color="#C06B32",
                        ),
                    ),
                    _panel(
                        860,
                        390,
                        350,
                        180,
                        _text(
                            "step_3",
                            314,
                            156,
                            26,
                            60,
                            color="#355C7D",
                        ),
                    ),
                ],
            ),
        ],
        "metadata": _metadata(
            ["scene", "sequence", "process", "move"],
            "sequence",
            4,
            max_chars=150,
        ),
    }


def build_production_ai_visual_template() -> TemplateV2:
    """Build the internal AI-background skeleton with at least eight layouts.

    The skeleton deliberately stays visually neutral. The generated background is
    the art direction; these layouts only guarantee projection-safe hierarchy,
    spacing, interaction structure and text-safe regions.
    """
    layout_values = [*_layouts(), _comparison_layout(), _sequence_layout()]
    layouts = SlideLayouts.model_validate({"layouts": layout_values}).model_dump(
        mode="json",
        exclude_none=True,
    )
    return TemplateV2(
        id=AI_VISUAL_TEMPLATE_ID,
        name="AI 自由视觉",
        description=(
            "内部中性骨架模板：八类以上可复用版式负责可读性、课堂互动和文字安全区，"
            "每页背景由AI按同一视觉规范单独生成。"
        ),
        raw_layouts=None,
        components=None,
        merged_components=None,
        layouts=layouts,
        assets={
            "template_id": AI_VISUAL_TEMPLATE_ID,
            "icon_type": "bold",
            "icon_weight": "bold",
            "fonts": {},
            "images": [],
            "template_metadata": {
                "audiences": ["child"],
                "domains": ["通用"],
                "scenes": ["教学", "公开课"],
                "styles": ["AI自由视觉"],
                "auto_match": False,
                "allow_charts": False,
                "quality_status": "candidate",
                "internal_visual_mode": "ai-background",
                "minimum_layout_count": 8,
            },
        },
        is_default=True,
    )
