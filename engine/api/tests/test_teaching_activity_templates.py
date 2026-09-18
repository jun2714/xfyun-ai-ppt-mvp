import copy

import pytest

from api.v1.ppt.endpoints.presentation import (
    _apply_template_content_to_ui, _collect_non_decorative_text_elements,
    _template_text_required_height,
)
from models.presentation_layout import PresentationLayoutModel, SlideLayoutModel
from models.presentation_outline_model import PresentationOutlineModel, SlideOutlineModel, SlideContentContract
from services.classroom_content_mapping import build_classroom_content
from services.teaching_interaction_service import teaching_page_role, interaction_speaker_notes
from templates.education_catalog import build_education_pack, INTERACTIVE_PACK_IDS
from templates.v2.schema import get_template_schema
from utils.layout_compatibility import get_allowed_layout_indices_for_outline


def outline(role="compare", interaction="observe", audience="child", points=None, **extra):
    contract = SlideContentContract(
        preserve_visible_copy=True, screen_title="发现海洋动物的不同",
        screen_points=points or ["观察海龟的外壳", "观察海豚的身体"],
        classroom_role=role, interaction_type=interaction, visual_audience=audience,
        **extra,
    )
    return SlideOutlineModel(content="\n".join([contract.screen_title, *contract.screen_points]),
                             content_contract=contract)


@pytest.mark.parametrize("pack", INTERACTIVE_PACK_IDS)
def test_activity_roles_choose_distinct_compositions_and_preserve_copy(pack):
    template = build_education_pack(pack)
    entries = get_template_schema(template.layouts)["layouts"]
    layouts = PresentationLayoutModel(name=pack, slides=[
        SlideLayoutModel(id=e["layout_id"], json_schema=e["schema"]) for e in entries])
    audience = "teacher" if pack.startswith("training") else "child"
    cases = [("observation", "observe", "observe"), ("compare", "observe", "compare"),
             ("interaction", "choose", "choice"), ("sequence", "sequence", "sequence"),
             ("guess-partial", "guess", "question"), ("answer-reveal", "guess", "reveal"),
             ("recap", "recall", "recap")]
    slides = [outline(role, interaction, audience) for role, interaction, _ in cases]
    choices = get_allowed_layout_indices_for_outline(PresentationOutlineModel(slides=slides), layouts)
    geometries = set()
    for slide, allowed, (_, _, expected) in zip(slides, choices, cases):
        selected = layouts.slides[allowed[0]]
        assert f"_scene_{expected}_2" in selected.id
        content = build_classroom_content(selected.json_schema, slide)
        assert [content[f"point_{i}"]["text"] for i in range(2)] == slide.content_contract.screen_points
        source = next(x for x in template.layouts["layouts"] if x["id"] == selected.id)
        ui = _apply_template_content_to_ui(copy.deepcopy(source), content)
        for box in _collect_non_decorative_text_elements(ui["components"]):
            assert box["font"]["size"] >= 32
            assert _template_text_required_height(box) <= box["size"]["height"] + 1
        images = [e for c in source["components"] for e in c["elements"] if e["type"] == "image"]
        geometries.add(tuple((e["position"]["x"], e["position"]["y"], e["size"]["width"], e["size"]["height"]) for e in images))
    assert len(geometries) >= 6
    assert template.assets["template_metadata"]["quality_status"] == "candidate"


def test_reference_answers_stay_in_notes_and_stale_contracts_are_ignored():
    slide = outline("sequence", "sequence", game_options={"a": "发芽", "b": "种子", "c": "长叶"},
                    game_sequence_order=["b", "a", "c"], answer_key="b")
    template = build_education_pack("classroom-game")
    schema = next(e["schema"] for e in get_template_schema(template.layouts)["layouts"]
                  if e["layout_id"] == "classroom_scene_sequence_2")
    content = build_classroom_content(schema, slide)
    assert "种子 → 发芽 → 长叶" in content["__speaker_note__"]
    assert "教师参考答案：种子" in content["__speaker_note__"]
    assert "种子" not in str({k: v for k, v in content.items() if not k.startswith("__")})
    slide.content = "老师重新编辑了题目和答案"
    assert teaching_page_role(slide) is None
    assert interaction_speaker_notes(slide) == ""


@pytest.mark.parametrize("pack", INTERACTIVE_PACK_IDS)
def test_cards_bind_assets_by_caption_not_input_order(pack):
    slide = outline(asset_contracts=[
        dict(planning_slot="dolphin", semantic_label="海豚", audience_text="观察海豚的身体"),
        dict(planning_slot="turtle", semantic_label="海龟", audience_text="观察海龟的外壳"),
    ])
    template = build_education_pack(pack)
    prefix = "classroom_training" if pack.startswith("training") else "classroom"
    schema = next(e["schema"] for e in get_template_schema(template.layouts)["layouts"]
                  if e["layout_id"] == f"{prefix}_cards_compare_2")
    content = build_classroom_content(schema, slide)
    assert content["card_0"]["text"] == "观察海龟的外壳"
    assert "海龟" in content["card_0"]["visual"]["image_prompt"]
    assert content["card_1"]["text"] == "观察海豚的身体"
    assert "海豚" in content["card_1"]["visual"]["image_prompt"]
    slide.content_contract.classroom_role = "answer-reveal"
    slide.content_contract.visual_audience = "teacher" if pack.startswith("training") else "child"
    entries = get_template_schema(template.layouts)["layouts"]
    layouts = PresentationLayoutModel(name=pack, slides=[
        SlideLayoutModel(id=e["layout_id"], json_schema=e["schema"]) for e in entries])
    selected = get_allowed_layout_indices_for_outline(PresentationOutlineModel(slides=[slide]), layouts)[0][0]
    assert layouts.slides[selected].id == f"{prefix}_cards_reveal_2"


def test_long_copy_uses_roomy_fallback_without_rewriting():
    template = build_education_pack("classroom-game")
    entries = get_template_schema(template.layouts)["layouts"]
    layouts = PresentationLayoutModel(name=template.id, slides=[
        SlideLayoutModel(id=e["layout_id"], json_schema=e["schema"]) for e in entries])
    points = ["记录看到的形状和动作，并与同伴交流发现。" * 3 for _ in range(3)]
    slide = outline("image-observation", points=points)
    selected = get_allowed_layout_indices_for_outline(PresentationOutlineModel(slides=[slide]), layouts)[0][0]
    assert layouts.slides[selected].id == "classroom_scene_roomy_3"
    result = build_classroom_content(layouts.slides[selected].json_schema, slide)
    assert [result[f"point_{i}"]["text"] for i in range(3)] == points
