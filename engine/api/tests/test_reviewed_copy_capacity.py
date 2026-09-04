import asyncio
import copy
import json
from pathlib import Path

import pytest

from api.v1.ppt.endpoints.presentation import (
    _apply_template_content_to_ui,
    _collect_non_decorative_text_elements,
    _template_element_text,
    _template_text_required_height,
)
from models.presentation_layout import PresentationLayoutModel, SlideLayoutModel
from models.presentation_outline_model import PresentationOutlineModel, SlideOutlineModel, SlideContentContract
from templates.v2.schema import get_template_schema, _component_merge_repeated_schemas
from utils.layout_compatibility import LayoutCompatibilityError, get_allowed_layout_indices_for_outline
from utils.llm_calls.generate_slide_content import (
    _apply_locked_visible_copy, _outline_visible_lines, _prepare_response_schema,
    _schema_fallback_value,
)
from utils.template_text_capacity import locked_text_fits_field, template_text_boxes


def _field(width=190, height=19, font_size=15, max_length=100):
    return {"type": "string", "maxLength": max_length, "x-text-boxes": template_text_boxes({
        "size": {"width": width, "height": height},
        "font": {"size": font_size, "line_height": 1},
    })}


def test_declared_character_limit_cannot_override_real_single_line_capacity():
    field = _field(max_length=30)
    assert locked_text_fits_field("小种子醒来啦", field)
    assert not locked_text_fits_field("先别拆开，猜一猜里面会有什么话。", field)
    assert not locked_text_fits_field("喝水\n晒太阳", field)


def test_long_action_moves_to_roomy_body_without_rewriting_or_smaller_font_floor():
    schema = {"properties": {
        "title": _field(600, 80, 48, 30),
        "body": _field(600, 140, 24, 200),
        "caption": _field(190, 19, 15, 40),
    }}
    generated = {"caption": "改写", "body": "改写", "title": "改写"}
    text = "小种子收到来信啦\n信封上有一朵迎春花\n先别拆开，猜一猜里面会有什么话。"
    result = _apply_locked_visible_copy(generated, text, schema)
    assert result["title"] == "小种子收到来信啦"
    assert result["body"] == "信封上有一朵迎春花\n先别拆开，猜一猜里面会有什么话。"
    assert result["caption"] == ""
    assert schema["properties"]["caption"]["x-text-boxes"][0]["minimum_font_size"] == 14


def test_repeated_fields_keep_the_strictest_instance_geometry():
    wide = {"type": "object", "properties": {"label": _field(300, 40)}}
    narrow = {"type": "object", "properties": {"label": _field(70, 19)}}
    result = _component_merge_repeated_schemas([wide, narrow])
    assert result is not None
    field = result["properties"]["label"]
    assert len(field["x-text-boxes"]) == 2
    assert not locked_text_fits_field("小种子喝到水啦", field)
    assert locked_text_fits_field("喝水", field)


def test_internal_geometry_is_removed_from_provider_response_schema():
    result = _prepare_response_schema({"type": "object", "properties": {"title": _field()}}, "Chinese")
    assert "x-text-boxes" not in json.dumps(result)


def test_all_incompatible_layouts_stop_before_any_paid_model_call(monkeypatch):
    from utils.llm_calls import generate_presentation_structure as module

    def unexpected_client(**kwargs):
        raise AssertionError("No paid client should be created for an incompatible outline")

    monkeypatch.setattr(module, "get_client", unexpected_client)
    outline = PresentationOutlineModel(slides=[SlideOutlineModel(
        content="先别拆开，猜一猜里面会有什么话。",
        content_contract=SlideContentContract(preserve_visible_copy=True),
    )])
    layout = PresentationLayoutModel(name="tiny", slides=[SlideLayoutModel(
        id="caption-only", json_schema={"properties": {"caption": _field()}},
    )])
    with pytest.raises(LayoutCompatibilityError, match="does not fit"):
        asyncio.run(module.generate_presentation_structure(outline, layout))


LONG_OUTLINES = [
    "嘘，谁给种子宝宝寄来了一封信？\n- 谁寄来的信？\n- 是写给谁的呢？\n先别拆开，猜一猜里面会有什么话。",
    "小种子还躲在棕色小外套里睡觉\n- 它小小的，硬硬的。\n- 还没有伸出小芽。\n小手指轻轻碰一碰它，别吵醒。",
    "种子宝宝喝到水啦！\n- 小雨点轻轻落下来。\n- 泥土变得湿湿的。\n一起做“咕咚咕咚”喝水的声音。",
    "暖暖的风抱了抱小种子\n- 泥土里暖暖的。\n- 种子宝宝伸了个懒腰。\n用手臂抱住自己，像暖暖的风。",
    "太阳公公来敲门，小芽钻出来啦！\n- 白白的根向下钻。\n- 绿绿的小芽向上长。\n我们一起看看新长出的小芽。",
    "谁在帮小种子？谁在捣乱？\n- 小雨点带来了水。\n- 阳光送来了温暖。\n- 石头挡住了小芽。\n像春天小帮手一样，帮小种子选一选。",
    "从睡觉到醒来，小种子怎么变？\n- 先喝水，再伸懒腰。\n- 根钻下去，小芽冒出来。\n帮种子宝宝的照片排一排顺序。",
    "小种子谢谢你们叫醒它！\n- 种子宝宝喝水、取暖、晒太阳。\n- 破开小外套，钻出小绿芽。\n- 我们都是春天小帮手。\n把自己变成一颗正在发芽的小种子。",
]


def test_long_outline_replay_filters_or_fits_every_allowed_standard_layout():
    template = json.loads((Path(__file__).resolve().parents[3] / "templates/standard/template.json").read_text(encoding="utf-8"))
    schemas = get_template_schema(template)["layouts"]
    source_ui = {item["id"]: item for item in template["layouts"]}
    layout = PresentationLayoutModel(name="standard", slides=[
        SlideLayoutModel(id=item["layout_id"], json_schema=item["schema"]) for item in schemas
    ])
    outline = PresentationOutlineModel(slides=[SlideOutlineModel(
        content=text,
        content_contract=SlideContentContract(preserve_visible_copy=True, requires_images=True),
    ) for text in LONG_OUTLINES])
    allowed = get_allowed_layout_indices_for_outline(outline, layout)
    assert allowed is not None and all(allowed)
    for text, indices in zip(LONG_OUTLINES, allowed):
        for index in indices:
            selected = layout.slides[index]
            generated = _schema_fallback_value(selected.json_schema)
            content = _apply_locked_visible_copy(generated, text, selected.json_schema)
            ui = _apply_template_content_to_ui(copy.deepcopy(source_ui[selected.id]), content)
            elements = _collect_non_decorative_text_elements(ui["components"])
            visible = "\n".join(_template_element_text(element) for element in elements)
            assert all(line in visible for line in _outline_visible_lines(text))
            for element in elements:
                height = (element.get("size") or {}).get("height")
                if isinstance(height, (int, float)):
                    assert _template_text_required_height(element) <= height * 1.02, (selected.id, _template_element_text(element))
