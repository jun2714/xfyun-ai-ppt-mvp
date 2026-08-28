from __future__ import annotations

from math import ceil
from typing import Any

from models.sql.template_v2 import TemplateV2
from templates.v2.models.layouts import SlideLayouts


AI_VISUAL_TEMPLATE_ID = "ai-visual"
FONT_FAMILY = "Microsoft YaHei"
PLACEHOLDER_IMAGE = "/static/images/replaceable_template_image.png"


def _text(
    name: str,
    width: int,
    height: int,
    size: int,
    max_length: int,
    *,
    color: str = "#173B2F",
    bold: bool = True,
    align: str = "center",
) -> dict[str, Any]:
    return {
        "type": "text",
        "size": {"width": width, "height": height},
        "font": {
            "size": size,
            "family": FONT_FAMILY,
            "color": color,
            "bold": bold,
        },
        "alignment": {"horizontal": align, "vertical": "middle"},
        "runs": [{"text": name}],
        "decorative": False,
        "name": name,
        "max_length": max_length,
        "min_length": max(1, ceil(max_length / 2)),
    }


def _panel(
    x: int,
    y: int,
    width: int,
    height: int,
    child: dict[str, Any],
) -> dict[str, Any]:
    return {
        "type": "container",
        "position": {"x": x, "y": y},
        "size": {"width": width, "height": height},
        "fill": {"color": "#FFFDF7", "opacity": 0.92},
        "padding": {"top": 12, "right": 18, "bottom": 12, "left": 18},
        "child": child,
    }


def _background(*, safe: str = "center") -> dict[str, Any]:
    return {
        "type": "image",
        "position": {"x": 0, "y": 0},
        "size": {"width": 1280, "height": 720},
        "data": PLACEHOLDER_IMAGE,
        "fit": "cover",
        "decorative": False,
        "name": "background_scene",
        "is_icon": False,
        "asset_role": "background",
        "asset_mode": "direct-background",
        "aspect_ratio": "16:9",
        "text_safe_area": safe,
        "required": True,
    }


def _cutout(name: str, x: int) -> dict[str, Any]:
    return {
        "type": "image",
        "position": {"x": x, "y": 245},
        "size": {"width": 205, "height": 205},
        "data": PLACEHOLDER_IMAGE,
        "fit": "contain",
        "decorative": False,
        "name": name,
        "is_icon": False,
        "asset_role": "cutout",
        "asset_mode": "sprite-sheet",
        "asset_group": "game_items",
        "aspect_ratio": "1:1",
        "text_safe_area": "none",
        "required": True,
    }


def _component(cid: str, description: str, elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": cid,
        "description": description,
        "position": {"x": 0, "y": 0},
        "elements": elements,
    }


def _metadata(
    capabilities: list[str],
    relationship: str,
    text_blocks: int,
    *,
    image_slots: int = 1,
    cutout_slots: int = 0,
    max_chars: int = 140,
) -> dict[str, Any]:
    return {
        "capabilities": capabilities,
        "contentShape": {
            "relationship": relationship,
            "minItems": 0,
            "maxItems": 6,
            "textBlocks": text_blocks,
            "imageSlots": image_slots,
        },
        "media": {
            "backgroundSlots": 1,
            "framedImageSlots": 0,
            "cutoutSlots": cutout_slots,
            "required": True,
        },
        "readability": {
            "minimumFontSize": 22,
            "maximumVisibleCharacters": max_chars,
        },
        "qualityStatus": "candidate",
    }


def _layouts() -> list[dict[str, Any]]:
    return [
        {
            "id": "ai_cover",
            "description": "AI自由视觉封面，中央标题和副标题叠加在统一生成背景上。",
            "components": [
                _component(
                    "background",
                    "全屏生成背景，中央区域保持低细节以承载标题。",
                    [_background(safe="center")],
                ),
                _component(
                    "content",
                    "中央标题卡，保证投影时标题清楚并保留呼吸感。",
                    [
                        _panel(230, 240, 820, 110, _text("title", 784, 86, 52, 28)),
                        _panel(
                            330,
                            370,
                            620,
                            70,
                            _text(
                                "subtitle",
                                584,
                                46,
                                26,
                                40,
                                color="#51636F",
                                bold=False,
                            ),
                        ),
                    ],
                ),
            ],
            "metadata": _metadata(["scene", "single-focus"], "single", 2, max_chars=80),
        },
        {
            "id": "ai_left",
            "description": "AI自由视觉左文右景页，左侧文字卡与右侧主题场景形成清楚分区。",
            "components": [
                _component(
                    "background",
                    "全屏生成背景，关键主体放在右侧并避开文字安全区。",
                    [_background(safe="left")],
                ),
                _component(
                    "content",
                    "左侧标题正文和互动提示，字号适合幼儿园课堂投影。",
                    [
                        _panel(
                            56,
                            90,
                            500,
                            86,
                            _text("title", 464, 62, 40, 28, align="left"),
                        ),
                        _panel(
                            56,
                            198,
                            500,
                            250,
                            _text(
                                "body",
                                464,
                                226,
                                27,
                                90,
                                color="#334A43",
                                bold=False,
                                align="left",
                            ),
                        ),
                        _panel(
                            56,
                            486,
                            500,
                            76,
                            _text(
                                "prompt",
                                464,
                                52,
                                27,
                                34,
                                color="#C06B32",
                                align="left",
                            ),
                        ),
                    ],
                ),
            ],
            "metadata": _metadata(
                ["scene", "image-text", "observation"],
                "single",
                3,
                max_chars=150,
            ),
        },
        {
            "id": "ai_right",
            "description": "AI自由视觉右文左景页，右侧文字卡与左侧主题场景形成清楚分区。",
            "components": [
                _component(
                    "background",
                    "全屏生成背景，关键主体放在左侧并避开文字安全区。",
                    [_background(safe="right")],
                ),
                _component(
                    "content",
                    "右侧标题正文和互动提示，适合故事讲述与知识认识。",
                    [
                        _panel(
                            724,
                            90,
                            500,
                            86,
                            _text("title", 464, 62, 40, 28, align="left"),
                        ),
                        _panel(
                            724,
                            198,
                            500,
                            250,
                            _text(
                                "body",
                                464,
                                226,
                                27,
                                90,
                                color="#334A43",
                                bold=False,
                                align="left",
                            ),
                        ),
                        _panel(
                            724,
                            486,
                            500,
                            76,
                            _text(
                                "prompt",
                                464,
                                52,
                                27,
                                34,
                                color="#C06B32",
                                align="left",
                            ),
                        ),
                    ],
                ),
            ],
            "metadata": _metadata(["scene", "image-text", "story"], "story", 3, max_chars=150),
        },
        {
            "id": "ai_question",
            "description": "AI自由视觉互动提问页，顶部问题卡和底部三项选择叠加在低细节背景上。",
            "components": [
                _component(
                    "background",
                    "全屏生成互动背景，严禁在背景中提前暴露正确答案。",
                    [_background(safe="center")],
                ),
                _component(
                    "content",
                    "大字号问题与三项选择，保证幼儿远距离能够快速辨认。",
                    [
                        _panel(120, 70, 1040, 110, _text("question", 1004, 86, 38, 42)),
                        _panel(110, 470, 300, 100, _text("choice_a", 264, 76, 29, 24, color="#355C7D")),
                        _panel(490, 470, 300, 100, _text("choice_b", 264, 76, 29, 24, color="#355C7D")),
                        _panel(870, 470, 300, 100, _text("choice_c", 264, 76, 29, 24, color="#355C7D")),
                    ],
                ),
            ],
            "metadata": _metadata(["scene", "question", "game", "reveal"], "question", 4, max_chars=110),
        },
        {
            "id": "ai_multi_item",
            "description": "AI自由视觉多物体互动页，一张背景加四个透明主体槽，适合分类配对找一找。",
            "components": [
                _component(
                    "background",
                    "全屏生成低细节互动背景，中央主体区域保持干净。",
                    [_background(safe="center")],
                ),
                _component(
                    "header",
                    "顶部任务标题与简短操作提示，保证课堂操作指令醒目。",
                    [
                        _panel(120, 50, 500, 82, _text("title", 464, 58, 34, 28, align="left")),
                        _panel(
                            660,
                            50,
                            500,
                            82,
                            _text(
                                "instruction",
                                464,
                                58,
                                27,
                                40,
                                color="#C06B32",
                                align="right",
                            ),
                        ),
                    ],
                ),
                _component(
                    "items",
                    "四个主体槽统一使用精灵图生成模式以降低图片调用次数。",
                    [
                        _cutout("item_1", 95),
                        _cutout("item_2", 390),
                        _cutout("item_3", 685),
                        _cutout("item_4", 980),
                    ],
                ),
            ],
            "metadata": _metadata(
                ["scene", "multi-item", "classification", "matching", "game"],
                "multi-item",
                2,
                image_slots=5,
                cutout_slots=4,
                max_chars=90,
            ),
        },
        {
            "id": "ai_recap",
            "description": "AI自由视觉总结收束页，中央回顾卡叠加在温暖统一的结束背景上。",
            "components": [
                _component(
                    "background",
                    "全屏生成温暖结束场景，氛围统一且不喧宾夺主。",
                    [_background(safe="center")],
                ),
                _component(
                    "content",
                    "中央总结标题与三条以内回顾重点，适合课堂收束。",
                    [
                        _panel(250, 145, 780, 86, _text("title", 744, 62, 40, 28)),
                        _panel(280, 275, 720, 68, _text("point_1", 684, 44, 27, 40, color="#2A6F62")),
                        _panel(280, 365, 720, 68, _text("point_2", 684, 44, 27, 40, color="#C06B32")),
                        _panel(280, 455, 720, 68, _text("point_3", 684, 44, 27, 40, color="#355C7D")),
                    ],
                ),
            ],
            "metadata": _metadata(["scene", "recap", "single-focus"], "single", 4, max_chars=130),
        },
    ]


def build_ai_visual_template() -> TemplateV2:
    layouts = SlideLayouts.model_validate({"layouts": _layouts()}).model_dump(
        mode="json",
        exclude_none=True,
    )
    return TemplateV2(
        id=AI_VISUAL_TEMPLATE_ID,
        name="AI 自由视觉",
        description=(
            "内部中性骨架模板：版式只负责可读性和文字安全区，"
            "每页背景由AI按统一视觉规范单独生成。"
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
            },
        },
        is_default=True,
    )
