from models.kindergarten_lesson_plan import KindergartenLessonPlan
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


def test_science_exploration_routes_to_dynamic():
    decision = resolve_kindergarten_template(
        _plan(
            topic="春天里的种子",
            domain="science",
            slide_types=["cover-scene", "image-observation", "knowledge-single"],
        ),
        "auto",
    )

    assert decision.template == "dynamic"
    assert decision.scores["dynamic"] > decision.scores["standard"]


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
