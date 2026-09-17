"""Topic grounding survives cover planning, image generation and UI binding."""
import copy

import pytest

from api.v1.ppt.endpoints.presentation import _apply_template_content_to_ui
from models.kindergarten_lesson_plan import KindergartenLessonPlan
from models.presentation_outline_model import SlideContentContract, SlideOutlineModel
from models.sql.slide import SlideModel
from services.asset_execution_service import _request_prompt
from services.asset_planning_service import build_asset_plan
from services.asset_semantic_quality_service import _build_quality_prompt
from services.chat.slide_ui_helpers import _apply_image_element_value
from services.classroom_content_mapping import build_classroom_content
from services.kindergarten_lesson_planning_service import build_kindergarten_lesson_messages
from services.kindergarten_presentation_planning_service import (
    _ensure_cover_contract, _normalize_training_contracts,
)
from templates.education_variants import EDUCATION_VARIANTS, build_education_variant
from templates.kindergarten_classroom import build_classroom_template
from templates.teacher_training import build_training_template
from templates.v2.schema import get_template_schema


def _pack(key):
    if key == "kindergarten-classroom":
        return build_classroom_template()
    if key == "teacher-training":
        return build_training_template()
    return build_education_variant(key)


def _schema(template, layout_id):
    return next(entry["schema"] for entry in get_template_schema(template.layouts)["layouts"]
                if entry["layout_id"] == layout_id)


def _ocean_plan():
    return KindergartenLessonPlan.model_validate({
        "meta": {"topic": "蓝色礼物袋里藏着谁？", "age_group": "4-5岁", "domain": "science"},
        "lesson_goals": ["认识章鱼、螃蟹、河豚的明显外形特征。"],
        "lesson_arc": ["发现海洋朋友", "观察外形", "模仿动作"],
        "slides": [{
            "slide_no": 1, "slide_type": "image-observation",
            "teaching_goal": "观察海洋动物的完整身体和特征",
            "screen_content": {"title": "海洋朋友有哪些本领？", "points": ["观察身体特征"]},
            "teacher_note": "引导幼儿观察后再模仿动作。",
            "assets": [{"slot": str(i), "semantic_label": name,
                        "description": f"完整的{name}，在适宜生活环境中展示身体特征"}
                       for i, name in enumerate(["章鱼", "螃蟹", "河豚"])],
        }],
    })


@pytest.mark.parametrize("training", [False, True])
def test_playful_cover_keeps_actual_subjects_through_final_request(training):
    mode = "training" if training else "classroom"
    plan = _ensure_cover_contract(_ocean_plan(), mode)
    if training:
        plan = _normalize_training_contracts(plan)
    # Re-normalization is idempotent and retains grounding, not just the title.
    assert _ensure_cover_contract(plan, mode).slides[0].assets == plan.slides[0].assets
    key = "training-action" if training else "classroom-nature"
    template = _pack(key)
    layout = next(item for item in template.layouts["layouts"] if item["id"].endswith("_cover"))
    content = build_classroom_content(_schema(template, layout["id"]), plan.to_presentation_outline().slides[0])
    ui = _apply_template_content_to_ui(copy.deepcopy(layout), content)
    slide = SlideModel(presentation="00000000-0000-0000-0000-000000000001", index=0,
                       layout_group=key, layout=layout["id"], content=content, ui=ui)
    assets = build_asset_plan([slide])
    assert len(assets) == 1
    request = _request_prompt(assets[0])
    for name in ["章鱼", "螃蟹", "河豚"]:
        assert name in request
        assert name in plan.slides[0].assets[0].description
    assert "叶脉" not in request
    assert "种子" not in request
    assert "标题中的悬念道具不能替代实际教学对象" in request
    assert "只生成无字背景" in request


def _comparison():
    points = ["软软朋友：章鱼", "硬壳朋友：螃蟹"]
    title = "章鱼和螃蟹，一个软软，一个硬硬"
    return SlideOutlineModel(
        content="\n".join([title, *points]),
        content_contract=SlideContentContract(
            preserve_visible_copy=True, screen_title=title, screen_points=points,
            asset_contracts=[dict(planning_slot=str(i), semantic_label=name,
                                 description=f"完整的{name}，清楚显示身体特征", audience_text=points[i])
                             for i, name in reversed(list(enumerate(["章鱼", "螃蟹"])))],
        ),
    )


@pytest.mark.parametrize("key,suffix", [
    (key, suffix)
    for key in ["kindergarten-classroom", "teacher-training", *EDUCATION_VARIANTS]
    for suffix in ["cards_2", "scene_left_2", "scene_right_2", *(
        ["cards_roomy_2"] if key in EDUCATION_VARIANTS else []
    )]
])
def test_real_image_binding_preserves_contain_and_individual_card_subjects(key, suffix):
    template = _pack(key)
    layout = next(item for item in template.layouts["layouts"] if item["id"].endswith("_" + suffix))
    original = copy.deepcopy(layout)
    outline = _comparison()
    content = build_classroom_content(_schema(template, layout["id"]), outline)
    if suffix.startswith("cards"):
        for i, (own, other) in enumerate([("章鱼", "螃蟹"), ("螃蟹", "章鱼")]):
            prompt = content[f"card_{i}"]["visual"]["image_prompt"]
            assert own in prompt
            assert other not in prompt
            assert content[f"card_{i}"]["text"] == outline.content_contract.screen_points[i]
    for value in content.values():
        if isinstance(value, dict) and "visual" in value:
            value["visual"]["image_url"] = "/app_data/images/ocean.png"
    ui = _apply_template_content_to_ui(layout, content)
    images = [element for component in ui["components"] for element in component["elements"]
              if element["type"] == "image"]
    assert len(images) == (2 if suffix.startswith("cards") else 1)
    assert all(image["fit"] == "contain" for image in images)
    assert all(image["data"] == "/app_data/images/ocean.png" for image in images)
    assert layout == original
    slide = SlideModel(presentation="00000000-0000-0000-0000-000000000001", index=0,
                       layout_group=key, layout=layout["id"], content=content, ui=ui)
    assert build_asset_plan([slide]) == []  # Reopening must not charge for these again.


@pytest.mark.parametrize("fit", ["contain", "cover", "fill"])
def test_chat_image_replacement_keeps_teacher_selected_fit(fit):
    element = {"type": "image", "fit": fit, "asset_role": "framed-image"}
    _apply_image_element_value(element, {"image_url": "/app_data/images/replaced.png"})
    assert element["fit"] == fit
    assert element["data"] == "/app_data/images/replaced.png"


@pytest.mark.parametrize("topic", ["认识海洋生物", "动植物研究"])
def test_common_planning_instructions_do_not_plant_an_unrelated_seed_topic(topic):
    messages = build_kindergarten_lesson_messages(
        topic=topic, age_group="4-5岁", domain="science", duration_minutes=20,
        n_slides=9, instructions=None, source_context=None,
    )
    prompt = "\n".join(message.content for message in messages)
    assert topic in prompt
    assert all(word not in prompt for word in ["种子", "叶脉", "小芽"])
    assert "人兽混合" in prompt


def test_seed_topic_is_not_censored_when_requested_by_teacher():
    outline = _comparison()
    outline.content = "观察种子\n种子长出了根"
    template = _pack("classroom-nature")
    content = build_classroom_content(_schema(template, "classroom_scene_left_1"), outline)
    prompt = content["scene"]["visual"]["image_prompt"]
    assert "种子长出了根" in prompt
    assert "章鱼" not in prompt
    assert "螃蟹" not in prompt


def test_visual_review_checks_anatomy_without_rejecting_intentional_guessing():
    prompt = _build_quality_prompt(())
    assert "人兽融合" in prompt
    assert "身体部件归属" in prompt
    assert "局部猜谜" in prompt
    assert "有意遮挡" in prompt
