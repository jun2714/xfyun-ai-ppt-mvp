import asyncio
from types import SimpleNamespace

from services import kindergarten_lesson_planning_service as lesson_service


def _minimal_plan_content():
    return {
        "meta": {
            "topic": "认识森林动物",
            "age_group": "4-5岁",
            "domain": "science",
            "duration_minutes": 20,
        },
        "lesson_goals": ["观察森林动物的外形"],
        "lesson_arc": ["进入森林"],
        "slides": [
            {
                "slide_no": 1,
                "slide_type": "cover-scene",
                "teaching_goal": "进入森林情境",
                "screen_content": {
                    "title": "森林动物大冒险",
                    "points": [],
                },
                "interaction": {"type": "move"},
                "teacher_note": "请幼儿模仿小动物，一起走进森林。",
                "assets": [],
            }
        ],
    }


def test_lesson_planner_forwards_fast_model_request_settings(monkeypatch):
    captured = {}
    runtime = SimpleNamespace(
        config=object(),
        model="kimi-k2.6",
        request_extra_body={"thinking": {"type": "disabled"}},
        max_tokens=8192,
        timeout_seconds=55.0,
    )

    monkeypatch.setattr(
        lesson_service,
        "get_kindergarten_planner_runtime",
        lambda: runtime,
    )
    monkeypatch.setattr(lesson_service, "get_client", lambda config: object())

    async def fake_generate_structured(client, model, **kwargs):
        captured.update(kwargs)
        captured["model"] = model
        return _minimal_plan_content()

    monkeypatch.setattr(
        lesson_service,
        "generate_structured_with_schema_retries",
        fake_generate_structured,
    )

    plan = asyncio.run(
        lesson_service.generate_kindergarten_lesson_plan(
            topic="认识森林动物",
            age_group="4-5岁",
            domain="science",
            duration_minutes=20,
        )
    )

    assert plan.meta.topic == "认识森林动物"
    assert captured["model"] == "kimi-k2.6"
    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}
    assert captured["max_tokens"] == 8192
    assert captured["call_timeout_seconds"] == 55.0
    assert captured["use_provider_extra_body"] is False
