import asyncio
import copy
import json

import jsonschema
import pytest

from models.kindergarten_lesson_plan import KindergartenLessonPlan
from models.presentation_outline_model import SlideContentContract, SlideOutlineModel, PresentationOutlineModel
from models.presentation_layout import PresentationLayoutModel, SlideLayoutModel
from services.classroom_content_mapping import build_classroom_content, preferred_classroom_layout
from templates.kindergarten_classroom import build_classroom_template
from templates.v2.schema import get_template_schema
from utils.layout_compatibility import get_allowed_layout_indices_for_outline, LayoutCompatibilityError
from utils.llm_calls import generate_slide_content
from api.v1.ppt.endpoints.presentation import (
    _apply_template_content_to_ui, _collect_non_decorative_text_elements,
    _template_element_text, _template_text_required_height,
)


def _outline(points=None, *, bound=True):
    points = points or ["水来喂饱小种子", "太阳来暖暖抱一抱", "和小种子挥手说再见"]
    return SlideOutlineModel(
        content="\n".join(["春风的信，我们听懂啦", *points, "一起说谢谢"]),
        content_contract=SlideContentContract(
            preserve_visible_copy=True, screen_title="春风的信，我们听懂啦",
            screen_points=points, screen_instruction="一起说谢谢",
            teacher_note="等幼儿回答后，再回顾本节课的发现。",
            interaction_instruction="邀请三位幼儿分别说出自己的发现。",
            asset_contracts=[{
                "planning_slot": f"object-{index}", "semantic_label": f"对应画面{index}",
                "description": point, "audience_text": point if bound else None,
            } for index, point in reversed(list(enumerate(points)))],
        ),
    )


def _pack():
    template = build_classroom_template()
    entries = get_template_schema(template.layouts)["layouts"]
    schemas = {entry["layout_id"]: entry["schema"] for entry in entries}
    return template, schemas


def test_reversed_image_assets_still_match_their_exact_captions():
    _, schemas = _pack()
    outline = _outline()
    result = build_classroom_content(schemas["classroom_cards_3"], outline)
    for index, point in enumerate(outline.content_contract.screen_points):
        card = result[f"card_{index}"]
        assert card["text"] == point
        assert f"对应画面{index}" in card["visual"]["image_prompt"]
        assert all(f"对应画面{other}" not in card["visual"]["image_prompt"]
                   for other in range(3) if other != index)
    assert result["heading"]["title"] == outline.content_contract.screen_title
    assert result["invitation"]["cue"] == "一起说谢谢"
    visible = {key: value for key, value in result.items() if not key.startswith("__")}
    jsonschema.validate(visible, schemas["classroom_cards_3"])
    assert "邀请三位幼儿" not in json.dumps(visible, ensure_ascii=False)
    assert "邀请三位幼儿" in result["__speaker_note__"]


def test_no_binding_uses_scene_instead_of_guessing_image_pairing():
    _, schemas = _pack()
    outline = _outline(bound=False)
    assert preferred_classroom_layout(outline) == "classroom_scene_left_3"
    with pytest.raises(ValueError, match="语义绑定"):
        build_classroom_content(schemas["classroom_cards_3"], outline)


def test_newly_edited_outline_never_restores_stale_copy_or_visuals():
    _, schemas = _pack()
    outline = _outline()
    outline.content = "老师改的新标题\n观察新叶子"
    result = build_classroom_content(schemas[preferred_classroom_layout(outline)], outline)
    assert result["heading"]["title"] == "老师改的新标题"
    assert result["point_0"]["text"] == "观察新叶子"
    assert result["invitation"]["cue"] == ""
    assert "对应画面" not in result["scene"]["visual"]["image_prompt"]
    visible = {key: value for key, value in result.items() if not key.startswith("__")}
    jsonschema.validate(visible, schemas[preferred_classroom_layout(outline)])


def test_classroom_mapping_bypasses_paid_content_model(monkeypatch):
    _, schemas = _pack()
    def forbidden(**_):
        raise AssertionError("Reviewed classroom text must not call a second model")
    monkeypatch.setattr(generate_slide_content, "get_client", forbidden)
    result = asyncio.run(generate_slide_content.get_slide_content_from_type_and_outline(
        SlideLayoutModel(id="classroom_cards_3", json_schema=schemas["classroom_cards_3"]),
        _outline(), "Chinese",
    ))
    assert result["__content_contract__"]["classroom_mapping_version"] == 1


def test_hydrated_cards_have_exact_copy_and_classroom_sized_text():
    template, schemas = _pack()
    outline = _outline()
    content = build_classroom_content(schemas["classroom_cards_3"], outline)
    layout = next(x for x in template.layouts["layouts"] if x["id"] == "classroom_cards_3")
    ui = _apply_template_content_to_ui(copy.deepcopy(layout), content)
    texts = _collect_non_decorative_text_elements(ui["components"])
    actual = [_template_element_text(element) for element in texts]
    assert outline.content_contract.screen_title in actual
    for point in outline.content_contract.screen_points:
        assert point in actual
    for element in texts:
        if not _template_element_text(element):
            continue
        assert element["font"]["size"] >= 32
        assert _template_text_required_height(element) <= element["size"]["height"] * .94


def test_every_choice_is_preflighted_without_any_llm():
    _, schemas = _pack()
    layout = PresentationLayoutModel(name="kindergarten-classroom", slides=[
        SlideLayoutModel(id=key, json_schema=schema) for key, schema in schemas.items()
    ])
    outline = _outline()
    choices = get_allowed_layout_indices_for_outline(PresentationOutlineModel(slides=[outline]), layout)
    assert len(choices[0]) == 1
    assert layout.slides[choices[0][0]].id == "classroom_cards_3"
    outline.content = "标题\n" + "不能把长篇教案塞进儿童投影画面" * 30
    with pytest.raises(LayoutCompatibilityError, match="大字号"):
        get_allowed_layout_indices_for_outline(PresentationOutlineModel(slides=[outline]), layout)


def test_all_template_elements_stay_inside_slide_bounds():
    template, _ = _pack()
    for layout in template.layouts["layouts"]:
        for component in layout["components"]:
            for element in component["elements"]:
                if element["type"] not in {"image", "text"}:
                    continue
                position, size = element["position"], element["size"]
                assert 0 <= position["x"] <= 1280 - size["width"]
                assert 0 <= position["y"] <= 720 - size["height"]


def test_lesson_conversion_retains_screen_and_interaction_roles():
    plan = KindergartenLessonPlan.model_validate({
        "meta": {"topic": "小种子", "age_group": "4-5岁"},
        "lesson_goals": ["观察变化"], "lesson_arc": ["观察"],
        "slides": [{"slide_no": 1, "slide_type": "image-observation", "teaching_goal": "观察变化",
                    "screen_content": {"title": "种子变胖了吗", "points": ["比一比大小"]},
                    "teacher_note": "教师出示两颗不同状态的种子。",
                    "interaction": {"type": "observe", "instruction": "请幼儿指出变化。"},
                    "assets": [{"slot": "comparison", "semantic_label": "种子吸水前后",
                                "description": "同一视角展示大小变化", "audience_text": "比一比大小"}]}],
    })
    contract = plan.to_presentation_outline().slides[0].content_contract
    assert contract.screen_points == ["比一比大小"]
    assert contract.asset_contracts[0].audience_text == "比一比大小"
    assert contract.interaction_instruction == "请幼儿指出变化。"
    from services.kindergarten_template_routing_service import resolve_kindergarten_template
    from services.kindergarten_plan_quality_service import validate_kindergarten_lesson_plan
    assert resolve_kindergarten_template(plan, "auto").template == "kindergarten-classroom"
    assert resolve_kindergarten_template(plan, "standard").template == "standard"
    assert resolve_kindergarten_template(plan, "auto", allow_classroom=False).template != "kindergarten-classroom"
    plan.slides[0].assets[0].audience_text = "另一个页面的内容"
    assert "asset-caption-mismatch" in {e.code for e in validate_kindergarten_lesson_plan(plan).errors}

