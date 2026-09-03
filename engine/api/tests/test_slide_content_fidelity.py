from models.kindergarten_lesson_plan import KindergartenLessonPlan
from utils.llm_calls.generate_slide_content import (
    _apply_locked_visible_copy,
    _build_schema_fallback,
    _outline_visible_lines,
    get_messages,
)


def test_schema_fallback_keeps_reviewed_copy_and_asset_semantics():
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "visual": {
                "type": "object",
                "properties": {"image_prompt": {"type": "string", "minLength": 10}},
            },
            "__speaker_note__": {"type": "string"},
        },
    }
    contract = {
        "preserve_visible_copy": True,
        "teacher_note": "先让孩子猜一猜，再揭晓答案。",
        "required_asset_semantics": ["泥土下睡觉的小种子和春天来信"],
        "asset_contracts": [
            {
                "semantic_label": "泥土下睡觉的小种子和春天来信",
                "description": "一颗小种子睡在温暖泥土里，身旁放着浅绿色信封",
            }
        ],
    }

    result = _build_schema_fallback(
        schema,
        "谁给种子宝宝写信啦？\n- 我们一起拆开春天来信",
        contract,
    )

    assert result["title"] == "谁给种子宝宝写信啦？"
    assert result["body"] == "我们一起拆开春天来信"
    assert "泥土下睡觉的小种子和春天来信" in result["visual"]["image_prompt"]
    assert result["__speaker_note__"] == "先让孩子猜一猜，再揭晓答案。"


def test_kindergarten_outline_marks_visible_copy_as_locked():
    plan = KindergartenLessonPlan.model_validate(
        {
            "meta": {
                "topic": "小种子长大了",
                "age_group": "4-5岁",
                "domain": "science",
                "duration_minutes": 20,
            },
            "lesson_goals": ["观察种子的生长变化"],
            "lesson_arc": ["收到求助信", "寻找生长线索"],
            "slides": [
                {
                    "slide_no": 1,
                    "slide_type": "story-intro",
                    "teaching_goal": "进入种子求助情境",
                    "screen_content": {
                        "title": "嘘，泥土下面是谁在说话？",
                        "points": ["一封来自小种子的求助信"],
                    },
                    "interaction": {"type": "guess"},
                    "teacher_note": "压低声音，请孩子先猜一猜是谁在求助。",
                    "assets": [],
                }
            ],
        }
    )

    outline = plan.to_presentation_outline().slides[0]
    assert outline.content_contract is not None
    assert outline.content_contract.preserve_visible_copy is True


def test_locked_copy_replaces_rewritten_slide_text_but_keeps_image_prompt():
    generated = {
        "hero": {
            "title": "谁在叫我们？",
            "subtitle": "小种子的信",
            "image": {"image_prompt": "温暖绘本风格的小种子从泥土里探头"},
        },
        "__speaker_note__": "模型生成的备注",
    }
    outline = "## 嘘，泥土下面是谁在说话？\n• 一封来自小种子的求助信"

    result = _apply_locked_visible_copy(generated, outline)

    assert result["hero"]["title"] == "嘘，泥土下面是谁在说话？"
    assert result["hero"]["subtitle"] == "一封来自小种子的求助信"
    assert result["hero"]["image"]["image_prompt"] == "温暖绘本风格的小种子从泥土里探头"
    assert result["__speaker_note__"] == "模型生成的备注"


def test_locked_copy_never_discards_outline_lines_when_template_has_one_text_slot():
    generated = {
        "card": {"title": "普通标题"},
        "visual": {"image_prompt": "种子发芽绘本场景"},
    }
    result = _apply_locked_visible_copy(
        generated,
        "种子宝宝要闯三关！\n- 喝到水\n- 晒太阳\n- 从泥土里钻出来",
    )

    assert result["card"]["title"] == (
        "种子宝宝要闯三关！\n喝到水\n晒太阳\n从泥土里钻出来"
    )


def test_locked_copy_prompt_explicitly_forbids_paraphrasing():
    messages = get_messages(
        "嘘，泥土下面是谁在说话？",
        "Chinese",
        content_contract={"preserve_visible_copy": True},
    )
    system_prompt = messages[0].content
    assert isinstance(system_prompt, str)
    assert "schema mapper, not a copywriter" in system_prompt
    assert "Do not paraphrase" in system_prompt


def test_outline_visible_lines_strip_editor_markers_only():
    assert _outline_visible_lines(
        "## **谁藏在泥土里？**\n• 摸一摸：硬硬的吗？\n- 找一找：小芽在哪里？"
    ) == [
        "谁藏在泥土里？",
        "摸一摸：硬硬的吗？",
        "找一找：小芽在哪里？",
    ]
