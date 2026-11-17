import copy

import pytest

from models.kindergarten_lesson_plan import KindergartenLessonPlan
from models.sql.slide import SlideModel
from services.asset_execution_service import _request_prompt
from services.asset_planning_service import build_asset_plan
from services.classroom_content_mapping import build_classroom_content
from services.kindergarten_plan_quality_service import validate_kindergarten_lesson_plan
from services.teaching_interaction_service import teaching_page_role
from templates.education_catalog import build_education_pack
from templates.v2.schema import get_template_schema
from api.v1.ppt.endpoints.presentation import _apply_template_content_to_ui


def plan(role="image-observation", interaction="observe", representation="auto"):
    return KindergartenLessonPlan.model_validate(dict(
        meta=dict(topic="海洋动物怎样动", age_group="4-5岁", domain="science"),
        lesson_goals=["观察动物身体怎样动"], lesson_arc=["观察", "模仿"],
        slides=[dict(slide_no=1, slide_type=role, visual_representation=representation,
                     teaching_goal="观察鱼尾摆动", screen_content=dict(title="看看谁在动", points=["鱼尾摆一摆", "螃蟹横着走"]),
                     interaction=dict(type=interaction), teacher_note="请幼儿指认身体的运动部位。",
                     assets=[dict(slot="fish", semantic_label="鱼尾摆一摆", description="一条鱼的尾鳍向一侧摆动", audience_text="鱼尾摆一摆"),
                             dict(slot="crab", semantic_label="螃蟹横着走", description="一只螃蟹沿沙地向侧面行走", audience_text="螃蟹横着走")])]))


def mapped(value, suffix="cards_compare_2"):
    template = build_education_pack("classroom-game")
    name = "classroom_" + suffix
    schema = next(x["schema"] for x in get_template_schema(template.layouts)["layouts"] if x["layout_id"] == name)
    outline = value.to_presentation_outline().slides[0]
    content = build_classroom_content(schema, outline)
    layout = next(x for x in template.layouts["layouts"] if x["id"] == name)
    ui = _apply_template_content_to_ui(copy.deepcopy(layout), content)
    slide = SlideModel(presentation="00000000-0000-0000-0000-000000000001", index=0,
                      layout_group=template.id, layout=name, content=content, ui=ui)
    return outline, content, build_asset_plan([slide])


def test_observation_is_realistic_through_template_and_provider_boundary():
    _, content, items = mapped(plan())
    assert content["__content_contract__"]["visual_representation"] == "realistic"
    assert len(items) == 2
    for item in items:
        prompt = _request_prompt(item)
        assert "AI生成的自然写实" in prompt
        assert "不是真实拍摄照片" in prompt
        assert "统一二维儿童绘本" not in prompt
        assert "never photography" not in prompt
    assert "螃蟹" not in _request_prompt(items[0])
    assert "鱼尾" not in _request_prompt(items[1])


def test_explicit_realistic_request_requires_identifiable_subject_before_images():
    value = plan(representation="realistic")
    report = validate_kindergarten_lesson_plan(value)
    assert "observation-identity-missing" in {error.code for error in report.errors}
    with pytest.raises(ValueError,match="缺少明确对象"):
        mapped(value)
    for asset in value.slides[0].assets:
        asset.role = "background"
    assert "observation-identity-missing" in {error.code for error in validate_kindergarten_lesson_plan(value).errors}


def test_named_species_environment_and_features_survive_mapping_and_visual_qa():
    from models.presentation_outline_model import ObservationSubject
    from services.asset_semantic_quality_service import _build_quality_prompt
    value = plan(representation="realistic")
    for asset in value.slides[0].assets:
        asset.observation_subjects = [ObservationSubject(
            name="小丑鱼（Amphiprion ocellaris）" if asset.slot == "fish" else "岸蟹",
            environment="浅海礁区" if asset.slot == "fish" else "海岸潮间带",
            distinguishing_features=["橙色身体，三条白色竖带" if asset.slot == "fish" else "甲壳、两只螯和八条步足"],
        )]
    _,_,items = mapped(value)
    fish = next(item for item in items if "小丑鱼" in item.slots[0].prompt)
    assert "Amphiprion ocellaris" in _request_prompt(fish)
    assert "三条白色竖带" in _build_quality_prompt(fish.slots[0].semantic_expectations)
    value.slides[0].assets[0].observation_subjects[0].name = "银色海鱼"
    with pytest.raises(ValueError,match="过于笼统"):
        mapped(value)


def test_activity_uses_cartoon_and_an_honest_activity_badge():
    outline, _, items = mapped(plan("other", "imitate"), "cards_imitate_2")
    assert teaching_page_role(outline) == "imitate"
    for item in items:
        assert "统一二维儿童绘本" in _request_prompt(item)
        assert "AI生成的自然写实" not in _request_prompt(item)


def test_same_description_for_different_cards_is_blocked_before_paid_images():
    value = plan("recap", "recall")
    for asset in value.slides[0].assets:
        asset.description = "鱼和螃蟹一起在舞台前合影。"
    report = validate_kindergarten_lesson_plan(value)
    assert "card-scenes-duplicated" in {e.code for e in report.errors}
    with pytest.raises(ValueError, match="重复使用同一段"):
        mapped(value)
    from services.kindergarten_presentation_planning_service import _repair_machine_contracts
    repaired = _repair_machine_contracts(value, report)
    assert repaired == value
    assert not validate_kindergarten_lesson_plan(repaired).passed


def test_deliberate_repeated_subject_is_allowed_for_counting_cards():
    from services.teaching_visual_policy import has_conflicting_card_scenes
    assets = plan().slides[0].assets
    for asset in assets:
        asset.semantic_label = "一个苹果"
        asset.description = "一个完整的红苹果。"
    assert not has_conflicting_card_scenes(assets)


def test_answered_matching_cards_cannot_pass_as_a_matching_task():
    value = plan("matching", "match")
    from models.kindergarten_lesson_plan import LessonGameSpec
    value.slides[0].game = LessonGameSpec(type="matching", activity_id="motion",
                                         answer_map={"鱼尾": "摆一摆", "螃蟹": "横着走"})
    errors = {e.code for e in validate_kindergarten_lesson_plan(value).errors}
    assert "matching-answer-already-visible" in errors
    value.slides[0].screen_content.points = ["鱼尾 / 螃蟹", "横着走 / 摆一摆"]
    assert "matching-answer-already-visible" not in {e.code for e in validate_kindergarten_lesson_plan(value).errors}


def test_explicit_page_direction_and_teacher_audience_are_preserved():
    from services.teaching_visual_policy import visual_representation
    value = plan(representation="illustration")
    assert visual_representation(value.to_presentation_outline().slides[0].content_contract) == "illustration"
    assert visual_representation(dict(visual_audience="teacher", visual_representation="realistic")) == "illustration"
    # A short imitation invitation does not change an observation page's purpose.
    assert visual_representation(plan("knowledge-single", "imitate").to_presentation_outline().slides[0].content_contract) == "realistic"


@pytest.mark.parametrize("mode", ["auto", "composite-image"])
def test_asset_reuse_never_crosses_realistic_and_cartoon_pages(mode):
    slides = [SlideModel(
        presentation="00000000-0000-0000-0000-000000000001", index=index,
        layout_group="classroom-game", layout="classroom_scene_observe_0",
        content={"scene": {"visual": {"image_prompt": "一条完整的银色海鱼"}},
                 "__content_contract__": {"visual_representation": style, "classroom_mapping_version": 1}},
        ui={"components": [{"id": "scene", "elements": [{"name": "scene.visual", "type": "image",
             "size": {"width": 600, "height": 400}, "asset_group": "shared", "asset_mode": mode}]}]},
    ) for index, style in enumerate(["realistic", "illustration"])]
    items = build_asset_plan(slides)
    assert len(items) == 2
    assert all(len(item.slots) == 1 for item in items)
    assert {item.slots[0].visual_representation for item in items} == {"realistic", "illustration"}


def test_identical_generic_prompt_cannot_reuse_different_species():
    slides = []
    for index,name in enumerate(["小丑鱼", "麦穗鱼"]):
        slides.append(SlideModel(
            presentation="00000000-0000-0000-0000-000000000001", index=index,layout_group="test",layout="test",
            content={"visual":{"image_prompt":"完整鱼体"},"__content_contract__":{
                "asset_contracts":[{"planning_slot":"fish","semantic_label":"完整鱼体","description":"完整侧面",
                    "observation_subjects":[{"name":name,"environment":"海水" if index==0 else "淡水",
                                              "distinguishing_features":["检查相应物种的识别特征"]}]}]}},ui={},
        ))
    items = build_asset_plan(slides)
    assert len(items) == 2
    assert "小丑鱼" in _request_prompt(items[0]) and "麦穗鱼" not in _request_prompt(items[0])
    assert "麦穗鱼" in _request_prompt(items[1]) and "小丑鱼" not in _request_prompt(items[1])
