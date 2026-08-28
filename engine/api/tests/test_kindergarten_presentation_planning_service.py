import asyncio

import pytest

from models.kindergarten_lesson_plan import KindergartenLessonPlan
from services import kindergarten_presentation_planning_service as planning_service


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


def test_invalid_first_plan_is_repaired_once_before_outline_generation(monkeypatch):
    calls = []
    plans = [_plan(reveal_answer="A"), _plan(reveal_answer="B")]

    async def fake_generate(**kwargs):
        calls.append(kwargs)
        return plans[len(calls) - 1]

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

    assert result.attempts == 2
    assert result.quality.passed is True
    assert len(calls) == 2
    assert "reveal-answer-mismatch" in calls[1]["instructions"]
    contract = result.outline.slides[1].content_contract
    assert contract is not None
    assert contract.activity_id == "forest-rabbit-1"
    assert contract.answer_key == "B"
    assert contract.required_asset_semantics == ["小兔子的两只长耳朵"]


def test_persistently_invalid_plan_stops_before_downstream_generation(monkeypatch):
    calls = []

    async def fake_generate(**kwargs):
        calls.append(kwargs)
        return _plan(reveal_answer="A")

    monkeypatch.setattr(
        planning_service,
        "generate_kindergarten_lesson_plan",
        fake_generate,
    )

    with pytest.raises(planning_service.KindergartenPlanningQualityError) as error:
        asyncio.run(
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

    assert len(calls) == 2
    assert error.value.attempts == 2
    assert error.value.report.passed is False
    assert any(
        issue.code == "reveal-answer-mismatch"
        for issue in error.value.report.errors
    )
