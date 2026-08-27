from models.kindergarten_lesson_plan import KindergartenLessonPlan
from services.kindergarten_plan_quality_service import (
    validate_kindergarten_lesson_plan,
)


def _valid_plan() -> KindergartenLessonPlan:
    return KindergartenLessonPlan.model_validate(
        {
            "meta": {
                "topic": "认识森林动物",
                "age_group": "4-5岁",
                "domain": "science",
                "duration_minutes": 20,
            },
            "lesson_goals": ["观察动物外形特征", "通过猜测游戏巩固认知"],
            "lesson_arc": ["进入情境", "观察动物", "猜一猜", "回顾"],
            "slides": [
                {
                    "slide_no": 1,
                    "slide_type": "cover-scene",
                    "teaching_goal": "进入森林探索情境",
                    "screen_content": {
                        "title": "森林探索队",
                        "points": [],
                        "instruction": "准备出发啦！",
                    },
                    "interaction": {"type": "move", "instruction": "一起做出发动作"},
                    "teacher_note": "邀请幼儿背上想象中的小背包，一起进入森林情境。",
                    "assets": [
                        {
                            "slot": "background",
                            "semantic_label": "明亮的森林探索场景",
                            "description": "阳光下的森林小路，没有文字，适合幼儿课堂封面",
                            "required": True,
                            "expected_count": 1,
                            "role": "background",
                            "qa_required": True,
                        }
                    ],
                    "layout_capabilities": ["scene"],
                },
                {
                    "slide_no": 2,
                    "slide_type": "guess-partial",
                    "teaching_goal": "根据长耳朵特征识别小兔子",
                    "screen_content": {
                        "title": "猜猜是谁？",
                        "points": ["谁有长长的耳朵？"],
                    },
                    "interaction": {"type": "guess", "instruction": "先观察，再举手回答"},
                    "teacher_note": "先只展示耳朵，引导幼儿说出观察到的形状，再进行选择。",
                    "assets": [
                        {
                            "slot": "question-image",
                            "semantic_label": "小兔子的两只长耳朵",
                            "description": "只显示一只白色小兔子的两只长耳朵，不露出完整身体，不含文字",
                            "required": True,
                            "expected_count": 1,
                            "role": "framed-image",
                            "qa_required": True,
                        }
                    ],
                    "game": {
                        "type": "guess",
                        "activity_id": "animal-ears-1",
                        "question": "这是谁的耳朵？",
                        "answer_key": "B",
                        "options": {"A": "小猫", "B": "小兔子"},
                    },
                    "layout_capabilities": ["question", "image-text"],
                },
                {
                    "slide_no": 3,
                    "slide_type": "answer-reveal",
                    "teaching_goal": "确认长耳朵属于小兔子",
                    "screen_content": {
                        "title": "原来是小兔子！",
                        "points": ["长长的耳朵真明显"],
                    },
                    "interaction": {"type": "imitate", "instruction": "一起竖起兔耳朵"},
                    "teacher_note": "揭晓完整小兔子图片，带幼儿用双手模仿长耳朵。",
                    "assets": [
                        {
                            "slot": "answer-image",
                            "semantic_label": "完整白色小兔子",
                            "description": "一只完整白色小兔子，长耳朵清晰可见，不含文字",
                            "required": True,
                            "expected_count": 1,
                            "role": "framed-image",
                            "qa_required": True,
                        }
                    ],
                    "game": {
                        "type": "guess",
                        "activity_id": "animal-ears-1",
                        "answer_key": "B",
                        "options": {"A": "小猫", "B": "小兔子"},
                    },
                    "layout_capabilities": ["reveal", "image-text"],
                },
                {
                    "slide_no": 4,
                    "slide_type": "recap",
                    "teaching_goal": "回顾小兔子的典型特征",
                    "screen_content": {
                        "title": "今天记住了什么？",
                        "points": ["小兔子有长长的耳朵"],
                    },
                    "interaction": {"type": "recall", "instruction": "请一个小朋友说一说"},
                    "teacher_note": "请幼儿用自己的话说出小兔子的一个明显特征。",
                    "assets": [],
                    "layout_capabilities": ["recap"],
                },
            ],
        }
    )


def test_valid_kindergarten_plan_passes_hard_quality_gates():
    report = validate_kindergarten_lesson_plan(_valid_plan())

    assert report.passed is True
    assert report.errors == []


def test_reveal_answer_mismatch_is_blocked():
    plan = _valid_plan()
    assert plan.slides[2].game is not None
    plan.slides[2].game.answer_key = "A"

    report = validate_kindergarten_lesson_plan(plan)

    assert report.passed is False
    assert any(issue.code == "reveal-answer-mismatch" for issue in report.errors)


def test_plan_to_outline_preserves_teacher_and_asset_semantics():
    outline = _valid_plan().to_presentation_outline()
    contract = outline.slides[1].content_contract

    assert contract is not None
    assert contract.relationship == "question"
    assert contract.activity_id == "animal-ears-1"
    assert contract.answer_key == "B"
    assert contract.interaction_type == "guess"
    assert contract.required_asset_semantics == ["小兔子的两只长耳朵"]
    assert "先只展示耳朵" in (contract.teacher_note or "")
