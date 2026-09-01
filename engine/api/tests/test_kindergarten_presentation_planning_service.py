import asyncio
from types import SimpleNamespace
import uuid

from models.kindergarten_lesson_plan import KindergartenLessonPlan
from services import kindergarten_presentation_planning_service as planning_service
from services.kindergarten_lesson_planning_service import (
    build_kindergarten_lesson_messages,
    resolve_kindergarten_slide_count,
)
from api.v1.ppt.endpoints import kindergarten as kindergarten_endpoint


def test_auto_slide_count_is_classroom_sized_and_explicit_choice_wins():
    assert resolve_kindergarten_slide_count(None, 15) == 8
    assert resolve_kindergarten_slide_count(None, 20) == 10
    assert resolve_kindergarten_slide_count(None, 35) == 12
    assert resolve_kindergarten_slide_count(None, 50) == 15
    assert resolve_kindergarten_slide_count(7, 20) == 7


def test_lesson_prompt_requires_cross_slide_coherence():
    messages = build_kindergarten_lesson_messages(
        topic="认识春天的小动物",
        age_group="4-5岁",
        domain="science",
        duration_minutes=20,
        n_slides=10,
        instructions=None,
        source_context=None,
    )

    system_prompt = messages[0].content
    user_prompt = messages[1].content
    assert isinstance(system_prompt, str)
    assert isinstance(user_prompt, str)
    assert "全局连贯性硬约束" in system_prompt
    assert "先教后练" in system_prompt
    assert "前面提出的问题必须在后面得到明确回应" in system_prompt
    assert "结尾回顾必须回扣 lesson_goals" in system_prompt
    assert "幼儿惊喜感与幻想表达" in system_prompt
    assert "小小冒险/秘密任务" in user_prompt
    assert "儿童惊喜钩子" in user_prompt


def test_start_endpoint_persists_project_before_planning(monkeypatch):
    presentation = SimpleNamespace(
        id=uuid.uuid4(),
        title=None,
        theme=None,
    )
    create_calls = []

    async def fake_create_presentation(**kwargs):
        create_calls.append(kwargs)
        return presentation

    class FakeSession:
        def add(self, _value):
            return None

        async def commit(self):
            return None

    monkeypatch.setattr(
        kindergarten_endpoint,
        "create_presentation",
        fake_create_presentation,
    )
    payload = kindergarten_endpoint.KindergartenPresentationCreateRequest(
        topic="小种子长大了",
        duration_minutes=20,
        n_slides=None,
    )

    response = asyncio.run(
        kindergarten_endpoint.start_kindergarten_presentation(
            payload,
            sql_session=FakeSession(),
        )
    )

    assert response.presentation_id == presentation.id
    assert response.n_slides == 10
    assert create_calls[0]["n_slides"] == 10
    assert presentation.theme["kindergarten_generation"]["outline_status"] == "pending"
    assert presentation.theme["kindergarten_generation"]["request"]["n_slides"] == 10


def _plan(*, reveal_answer: str = "B") -> KindergartenLessonPlan:
    return KindergartenLessonPlan.model_validate(
        {
            "meta": {
                "topic": "认识森林动物",
                "age_group": "4-5岁",
                "domain": "science",
                "duration_minutes": 20,
            },
            "lesson_goals": ["观察小兔子的外形特征"],
            "lesson_arc": ["进入森林", "猜耳朵", "揭晓答案"],
            "slides": [
                {
                    "slide_no": 1,
                    "slide_type": "cover-scene",
                    "teaching_goal": "进入森林情境",
                    "screen_content": {"title": "森林探索队", "points": []},
                    "interaction": {"type": "move"},
                    "teacher_note": "邀请幼儿一起做出发动作进入森林探索情境。",
                    "assets": [],
                },
                {
                    "slide_no": 2,
                    "slide_type": "guess-partial",
                    "teaching_goal": "根据长耳朵识别小兔子",
                    "screen_content": {
                        "title": "猜猜是谁？",
                        "points": ["谁有长长的耳朵？"],
                    },
                    "interaction": {"type": "guess"},
                    "teacher_note": "先观察耳朵，再让幼儿从两个选项中猜一猜。",
                    "assets": [
                        {
                            "slot": "question-image",
                            "semantic_label": "小兔子的两只长耳朵",
                            "description": "一只白色小兔子的两只长耳朵，不出现文字",
                            "expected_count": 1,
                            "role": "framed-image",
                        }
                    ],
                    "game": {
                        "type": "guess",
                        "activity_id": "forest-rabbit-1",
                        "answer_key": "B",
                        "options": {"A": "小猫", "B": "小兔子"},
                    },
                },
                {
                    "slide_no": 3,
                    "slide_type": "answer-reveal",
                    "teaching_goal": "确认答案并观察完整小兔子",
                    "screen_content": {
                        "title": "原来是小兔子！",
                        "points": ["它有长长的耳朵"],
                    },
                    "interaction": {"type": "imitate"},
                    "teacher_note": "揭晓完整小兔子后，请幼儿用双手模仿长耳朵。",
                    "assets": [
                        {
                            "slot": "answer-image",
                            "semantic_label": "完整白色小兔子",
                            "description": "一只完整白色小兔子，长耳朵清楚，不出现文字",
                            "expected_count": 1,
                            "role": "framed-image",
                        }
                    ],
                    "game": {
                        "type": "guess",
                        "activity_id": "forest-rabbit-1",
                        "answer_key": reveal_answer,
                        "options": {"A": "小猫", "B": "小兔子"},
                    },
                },
            ],
        }
    )


def test_answer_mismatch_is_repaired_without_second_model_call(monkeypatch):
    calls = []

    async def fake_generate(**kwargs):
        calls.append(kwargs)
        return _plan(reveal_answer="A")

    monkeypatch.setattr(
        planning_service,
        "generate_kindergarten_lesson_plan",
        fake_generate,
    )

    result = asyncio.run(
        planning_service.generate_validated_kindergarten_presentation_outline(
            topic="认识森林动物",
            age_group="4-5岁",
            domain="science",
            duration_minutes=20,
            n_slides=3,
            instructions="课堂要有猜一猜",
            source_context=None,
        )
    )

    assert result.attempts == 1
    assert result.quality.passed is True
    assert len(calls) == 1
    question = result.outline.slides[1].content_contract
    reveal = result.outline.slides[2].content_contract
    assert question is not None
    assert reveal is not None
    assert question.activity_id == "forest-rabbit-1"
    assert question.answer_key == "B"
    assert reveal.answer_key == "B"


def test_invalid_game_contract_is_downgraded_without_discarding_visible_page(monkeypatch):
    calls = []
    plan = _plan(reveal_answer="B")
    bad_question = plan.slides[1].model_copy(update={"game": None})
    plan = plan.model_copy(
        update={"slides": [plan.slides[0], bad_question, plan.slides[2]]}
    )

    async def fake_generate(**kwargs):
        calls.append(kwargs)
        return plan

    monkeypatch.setattr(
        planning_service,
        "generate_kindergarten_lesson_plan",
        fake_generate,
    )

    result = asyncio.run(
        planning_service.generate_validated_kindergarten_presentation_outline(
            topic="认识森林动物",
            age_group="4-5岁",
            domain="science",
            duration_minutes=20,
            n_slides=3,
            instructions=None,
            source_context=None,
        )
    )

    assert len(calls) == 1
    assert result.attempts == 1
    assert result.quality.passed is True
    assert "猜猜是谁？" in result.outline.slides[1].content
    assert result.plan.slides[1].slide_type == "other"
    assert result.plan.slides[1].game is None