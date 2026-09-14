import copy
from pathlib import Path
import xml.etree.ElementTree as ET

import jsonschema
import pytest

from api.v1.ppt.endpoints.presentation import (
    _apply_template_content_to_ui, _collect_non_decorative_text_elements,
    _template_text_required_height,
)
from models.presentation_layout import PresentationLayoutModel, SlideLayoutModel
from models.presentation_outline_model import (
    PresentationOutlineModel, SlideContentContract, SlideOutlineModel,
)
from services.classroom_content_mapping import build_classroom_content
from templates.education_variants import EDUCATION_VARIANTS, build_education_variant
from templates.v2.schema import get_template_schema
from utils.layout_compatibility import (
    LayoutCompatibilityError, get_allowed_layout_indices_for_outline,
)


def _outline(template_id, count, cards=False):
    teacher = EDUCATION_VARIANTS[template_id]["audience"] == "teacher"
    points = [
        f"观察证据{i + 1}：记录孩子原话和具体动作，再讨论支持策略。"
        if teacher else f"发现{i + 1}：小种子长出了新叶子。"
        for i in range(count)
    ]
    title = "从观察记录找到支持策略" if teacher else "小种子的新发现"
    cue = "讨论：下一次可以怎样支持？" if teacher else "说一说：你发现了什么？"
    assets = [dict(planning_slot=str(i), semantic_label=f"观察画面{i}",
                   description="花园里的观察活动", audience_text=point)
              for i, point in reversed(list(enumerate(points)))] if cards else []
    contract = SlideContentContract(
        preserve_visible_copy=True, screen_title=title, screen_points=points,
        screen_instruction=cue, asset_contracts=assets,
    )
    return SlideOutlineModel(content="\n".join([title, *points, cue]), content_contract=contract)


def _pack(template_id):
    template = build_education_variant(template_id)
    schemas = {entry["layout_id"]: entry["schema"]
               for entry in get_template_schema(template.layouts)["layouts"]}
    return template, schemas


@pytest.mark.parametrize("template_id", EDUCATION_VARIANTS)
@pytest.mark.parametrize("suffix", [*(f"scene_{side}_{n}" for side in ("left", "right")
                                    for n in range(7)), "cards_2", "cards_3", "cards_4",
                                    *(f"scene_roomy_{n}" for n in range(1, 7)),
                                    *(f"cards_roomy_{n}" for n in range(2, 5))])
def test_variant_copy_images_and_projectable_geometry(template_id, suffix):
    template, schemas = _pack(template_id)
    teacher = EDUCATION_VARIANTS[template_id]["audience"] == "teacher"
    layout_id = ("classroom_training_" if teacher else "classroom_") + suffix
    count = int(suffix.rsplit("_", 1)[-1])
    cards = suffix.startswith("cards_")
    outline = _outline(template_id, count, cards)
    content = build_classroom_content(schemas[layout_id], outline)
    jsonschema.validate({k: v for k, v in content.items() if not k.startswith("__")}, schemas[layout_id])
    layout = next(x for x in template.layouts["layouts"] if x["id"] == layout_id)
    ui = _apply_template_content_to_ui(copy.deepcopy(layout), content)
    for i, point in enumerate(outline.content_contract.screen_points):
        assert content[f"card_{i}" if cards else f"point_{i}"]["text"] == point
        if cards:
            assert f"观察画面{i}" in content[f"card_{i}"]["visual"]["image_prompt"]
    images = [value["visual"] for value in content.values()
              if isinstance(value, dict) and "visual" in value]
    assert len(images) == (count if cards else 1)
    for visual in images:
        assert ("专业清晰的教育编辑插画" in visual["image_prompt"]) == teacher
        assert ("统一二维儿童绘本" in visual["image_prompt"]) != teacher
    boxes = _collect_non_decorative_text_elements(ui["components"])
    for box in boxes:
        assert box["font"]["size"] >= 32
        assert _template_text_required_height(box) <= box["size"]["height"] + 1
    boxes += [element for component in ui["components"] for element in component["elements"]
              if element["type"] == "image"]
    for box in boxes:
        assert 0 <= box["position"]["x"] <= 1280 - box["size"]["width"]
        assert 0 <= box["position"]["y"] <= 720 - box["size"]["height"]
    for index, box in enumerate(boxes):
        for other in boxes[index + 1:]:
            a, b = box["position"], other["position"]
            assert (a["x"] + box["size"]["width"] <= b["x"] or
                    b["x"] + other["size"]["width"] <= a["x"] or
                    a["y"] + box["size"]["height"] <= b["y"] or
                    b["y"] + other["size"]["height"] <= a["y"])


@pytest.mark.parametrize("template_id", EDUCATION_VARIANTS)
def test_manual_variant_preflights_confirmed_copy_and_rejects_overflow(template_id):
    template, schemas = _pack(template_id)
    assert len(schemas) == 27
    assert template.assets["template_metadata"]["auto_match"] is True
    assert template.assets["template_metadata"]["audiences"] == [EDUCATION_VARIANTS[template_id]["audience"]]
    thumbnail = Path(__file__).parents[1] / template.assets["thumbnail"].lstrip("/")
    assert ET.parse(thumbnail).getroot().attrib["viewBox"] == "0 0 1280 720"
    layout = PresentationLayoutModel(name=template_id, slides=[
        SlideLayoutModel(id=key, json_schema=schema) for key, schema in schemas.items()
    ])
    outline = _outline(template_id, 3, cards=True)
    choices = get_allowed_layout_indices_for_outline(PresentationOutlineModel(slides=[outline]), layout)
    assert len(choices[0]) == 1
    assert layout.slides[choices[0][0]].id.endswith("cards_3")
    outline.content = "标题\n" + "必须完整保留已确认的观察记录" * 100
    with pytest.raises(LayoutCompatibilityError, match="大字号"):
        get_allowed_layout_indices_for_outline(PresentationOutlineModel(slides=[outline]), layout)


@pytest.mark.parametrize("template_id", EDUCATION_VARIANTS)
def test_variant_cover_preserves_goal_and_usage(template_id):
    template, schemas = _pack(template_id)
    layout_id = next(key for key in schemas if key.endswith("_cover"))
    title = "在真实游戏中观察儿童的探索与合作"
    points = ["活动目标：观察儿童在游戏中的具体动作与语言，记录可验证的证据，结合真实情境讨论教师可以采取的支持策略。", "使用类型：课堂活动与教师研讨"]
    outline = SlideOutlineModel(content="\n".join([title, *points]), content_contract=SlideContentContract(
        preserve_visible_copy=True, classroom_role="cover-scene", screen_title=title, screen_points=points,
    ))
    content = build_classroom_content(schemas[layout_id], outline)
    assert [content[f"point_{i}"]["text"] for i in range(2)] == points
    layout = next(x for x in template.layouts["layouts"] if x["id"] == layout_id)
    ui = _apply_template_content_to_ui(copy.deepcopy(layout), content)
    for box in _collect_non_decorative_text_elements(ui["components"]):
        assert box["font"]["size"] >= 32
        assert _template_text_required_height(box) <= box["size"]["height"] + 1


@pytest.mark.parametrize('template_id', EDUCATION_VARIANTS)
def test_long_captions_use_roomier_cards_without_losing_images(template_id):
    template, schemas = _pack(template_id)
    outline = _outline(template_id, 4, cards=True)
    points = [f'证据{i}：' + '记录孩子原话和具体动作，再讨论支持策略。' * 2 + '保留原始证据。' for i in range(4)]
    contract = outline.content_contract
    for asset in contract.asset_contracts:
        index = int(asset.planning_slot)
        asset.audience_text = points[index]
    contract.screen_points = points
    outline.content = '\n'.join([contract.screen_title, *points, contract.screen_instruction])
    before = outline.model_dump()
    layout = PresentationLayoutModel(name=template_id, slides=[
        SlideLayoutModel(id=key, json_schema=schema) for key, schema in schemas.items()
    ])
    choices = get_allowed_layout_indices_for_outline(PresentationOutlineModel(slides=[outline]), layout)
    chosen = layout.slides[choices[0][0]]
    assert chosen.id.endswith('cards_roomy_4')
    result = build_classroom_content(chosen.json_schema, outline)
    assert [result[f'card_{i}']['text'] for i in range(4)] == points
    assert all(f'观察画面{i}' in result[f'card_{i}']['visual']['image_prompt'] for i in range(4))
    assert outline.model_dump() == before
    assert len(choices) == 1


def test_long_story_scene_uses_roomier_geometry_without_rewriting():
    template_id = 'classroom-story'
    _, schemas = _pack(template_id)
    outline = _outline(template_id, 4)
    points = [f'情节{i}：小熊看见朋友遇到困难，停下来想一想自己可以怎样帮助它。' for i in range(4)]
    outline.content_contract.screen_points = points
    outline.content = '\n'.join([outline.content_contract.screen_title, *points, outline.content_contract.screen_instruction])
    layout = PresentationLayoutModel(name=template_id, slides=[
        SlideLayoutModel(id=key, json_schema=schema) for key, schema in schemas.items()
    ])
    choices = get_allowed_layout_indices_for_outline(PresentationOutlineModel(slides=[outline]), layout)
    assert layout.slides[choices[0][0]].id == 'classroom_scene_roomy_4'


@pytest.mark.parametrize('template_id', EDUCATION_VARIANTS)
def test_template_image_style_reaches_generation_prompt(template_id):
    template, schemas = _pack(template_id)
    key = next(key for key in schemas if key.endswith('scene_left_3'))
    result = build_classroom_content(schemas[key], _outline(template_id, 3))
    style = next(element['prompt'] for layout in template.layouts['layouts']
                 for component in layout['components'] for element in component['elements']
                 if element['type'] == 'image')
    assert style in result['scene']['visual']['image_prompt']
