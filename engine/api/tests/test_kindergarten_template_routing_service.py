from models.kindergarten_lesson_plan import KindergartenLessonPlan, LessonAssetSpec
from services.kindergarten_template_routing_service import (
    resolve_kindergarten_template,
)


def _plan(
    *,
    topic: str,
    domain: str,
    slide_types: list[str],
) -> KindergartenLessonPlan:
    slides = []
    for index, slide_type in enumerate(slide_types, start=1):
        slides.append(
            {
                "slide_no": index,
                "slide_type": slide_type,
                "teaching_goal": f"完成第 {index} 个课堂目标",
                "screen_content": {
                    "title": topic if index == 1 else f"活动 {index}",
                    "points": [],
                },
                "interaction": {"type": "observe"},
                "teacher_note": "请教师结合图片进行观察、提问和追问。",
                "assets": [],
                "layout_capabilities": ["single"],
            }
        )
    return KindergartenLessonPlan.model_validate(
        {
            "meta": {
                "topic": topic,
                "age_group": "4-5岁",
                "domain": domain,
                "duration_minutes": 20,
            },
            "lesson_goals": ["理解主题并参与课堂互动"],
            "lesson_arc": ["观察", "互动", "回顾"],
            "slides": slides,
        }
    )


def test_science_exploration_avoids_dark_dynamic_auto_template():
    decision = resolve_kindergarten_template(
        _plan(
            topic="春天里的种子",
            domain="science",
            slide_types=["cover-scene", "image-observation", "knowledge-single"],
        ),
        "auto",
    )

    assert decision.template == "standard"
    assert decision.scores["dynamic"] > decision.scores["standard"]


def test_asset_free_cover_does_not_disable_semantic_classroom_template():
    plan = _plan(
        topic="春天里的种子",
        domain="science",
        slide_types=["cover-scene", "image-observation", "knowledge-single"],
    )
    plan.slides[0].screen_content.points = ["活动目标：观察种子的变化", "使用类型：集体教学"]
    for slide in plan.slides[1:]:
        slide.assets = [
            LessonAssetSpec(
                slot="scene",
                semantic_label=slide.screen_content.title,
                description="与本页教学目标直接对应的完整课堂观察画面",
            )
        ]

    decision = resolve_kindergarten_template(plan, "auto")

    assert decision.template == "classroom-nature"


def test_game_heavy_lesson_routes_to_swift():
    decision = resolve_kindergarten_template(
        _plan(
            topic="动物猜猜乐互动游戏",
            domain="comprehensive",
            slide_types=[
                "cover-scene",
                "guess-partial",
                "answer-reveal",
                "matching",
                "memory-missing",
            ],
        ),
        "auto",
    )

    assert decision.template == "swift"


def test_story_lesson_routes_to_modern():
    decision = resolve_kindergarten_template(
        _plan(
            topic="小兔子的成长故事",
            domain="language",
            slide_types=["cover-scene", "story-intro", "ending-scene"],
        ),
        "auto",
    )

    assert decision.template == "modern"


def test_art_or_parent_child_activity_routes_to_momentum():
    decision = resolve_kindergarten_template(
        _plan(
            topic="端午亲子手工活动",
            domain="art",
            slide_types=["cover-scene", "knowledge-single", "ending-scene"],
        ),
        "auto",
    )

    assert decision.template == "momentum"


def test_health_and_rules_route_to_standard():
    decision = resolve_kindergarten_template(
        _plan(
            topic="洗手卫生和生活规则",
            domain="health",
            slide_types=["cover-scene", "knowledge-single", "recap"],
        ),
        "auto",
    )

    assert decision.template == "standard"


def test_manual_template_selection_is_never_rewritten():
    decision = resolve_kindergarten_template(
        _plan(
            topic="春天里的种子",
            domain="science",
            slide_types=["cover-scene", "image-observation"],
        ),
        "general",
    )

    assert decision.template == "general"
    assert decision.reason == "manual-selection"
    assert decision.scores == {}


def test_manual_dynamic_template_selection_remains_available():
    decision = resolve_kindergarten_template(
        _plan(
            topic="春天里的种子",
            domain="science",
            slide_types=["cover-scene", "image-observation"],
        ),
        "dynamic",
    )

    assert decision.template == "dynamic"
    assert decision.reason == "manual-selection"


def _visual_plan(topic='春天的种子', domain='science'):
    plan = _plan(topic=topic, domain=domain, slide_types=['cover-scene', 'image-observation', 'recap'])
    plan.slides[0].screen_content.points = ['活动目标：观察变化并交流发现', '使用类型：集体教学']
    for slide in plan.slides[1:]:
        slide.screen_content.points = ['观察变化', '交流发现']
        slide.assets = [LessonAssetSpec(slot='scene', semantic_label=topic, description='清楚呈现观察对象与具体活动')]
    return plan


def test_same_topic_uses_different_audience_templates():
    plan = _visual_plan('幼儿种植活动的观察记录与案例研讨')
    assert resolve_kindergarten_template(plan, 'auto', content_mode='classroom').template == 'classroom-nature'
    teacher = resolve_kindergarten_template(plan, 'auto', content_mode='training')
    assert teacher.template == 'training-case'
    assert set(teacher.scores) == {'training-case', 'training-action', 'teacher-training'}


def test_story_and_action_keywords_select_distinct_packs():
    story = _visual_plan('小熊分享的故事', 'language')
    assert resolve_kindergarten_template(story, 'auto').template == 'classroom-story'
    action = resolve_kindergarten_template(story, 'auto', content_mode='training',
                                           topic='班本课程改进计划与实施复盘', instructions='明确负责人和跟进步骤')
    assert action.template == 'training-action'
    assert '路线图' in action.reason


def test_manual_pack_selection_survives_conflicting_keywords_and_long_copy():
    plan = _visual_plan('植物观察记录与教研复盘')
    plan.slides[1].screen_content.points = ['长文' * 200]
    decision = resolve_kindergarten_template(plan, 'classroom-story', content_mode='training')
    assert decision.template == 'classroom-story'
    assert decision.reason == 'manual-selection'


def test_automatic_routing_is_deterministic_and_does_not_mutate_page_budget():
    plan = _visual_plan()
    before = plan.model_dump()
    first = resolve_kindergarten_template(plan, 'auto')
    assert first == resolve_kindergarten_template(plan, 'auto')
    assert plan.model_dump() == before
    assert '观察' in first.reason


def test_image_disabled_path_does_not_choose_image_required_variants():
    result = resolve_kindergarten_template(_visual_plan(), 'auto', allow_classroom=False)
    assert result.template not in {'classroom-nature', 'classroom-story', 'training-case', 'training-action'}


def test_all_overflow_retains_outline_for_review_but_prepare_still_rejects():
    plan = _visual_plan()
    plan.slides[1].screen_content.points = ['不能删除' * 100]
    before = plan.model_dump()
    result = resolve_kindergarten_template(plan, 'auto')
    assert '请先调整大纲' in result.reason
    assert '第 2 页' in result.reason
    assert plan.model_dump() == before


def test_capacity_fallback_selects_same_audience_and_explains_reason():
    plan = _visual_plan('交流分享', 'comprehensive')
    plan.slides[1].screen_content.points = [f'{i}：' + '保留儿童语言和动作' * 4 for i in range(6)]
    result = resolve_kindergarten_template(plan, 'auto', content_mode='training')
    assert result.template in {'training-case', 'training-action'}
    assert '正文容量不足' in result.reason
    assert '请先调整大纲' not in result.reason
