from models.kindergarten_lesson_plan import KindergartenLessonPlan
import copy
from utils.llm_calls.generate_slide_content import (
    _apply_locked_visible_copy,
    _build_schema_fallback,
    _ensure_required_asset_semantics,
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


def test_required_asset_semantics_are_appended_without_rewriting_prompts():
    generated = {
        "visual": {"image_prompt": "温暖泥土里的小种子"},
        "second": {"image_prompt": "春天菜园的明亮场景"},
    }
    result = _ensure_required_asset_semantics(
        generated,
        {
            "required_asset_semantics": [
                "一封装饰叶子的淡黄色春天信封",
                "泥土下睡觉的小种子",
            ]
        },
    )

    prompts = "\n".join(
        [result["visual"]["image_prompt"], result["second"]["image_prompt"]]
    )
    assert "温暖泥土里的小种子" in prompts
    assert "一封装饰叶子的淡黄色春天信封" in prompts
    assert "泥土下睡觉的小种子" in prompts


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


def test_locked_copy_uses_template_order_and_skips_tiny_badge():
    schema = {
        "properties": {
            "heading": {"properties": {
                "title": {"type": "string", "maxLength": 26},
                "body": {"type": "string", "maxLength": 190},
            }},
            "metadata": {"properties": {
                "badge": {"type": "string", "maxLength": 3},
                "question": {"type": "string", "maxLength": 15},
                "action": {"type": "string", "maxLength": 17},
            }},
        }
    }
    # Actual run 21 failure: provider put metadata before the heading object.
    generated = {
        "metadata": {"badge": "春天", "question": "改写", "action": "改写"},
        "heading": {"body": "改写", "title": "改写"},
    }
    lines = ["嘘，这里有一封春天的信！", "谁寄来的信？", "送给泥土下面的谁？", "先别拆开，猜一猜。"]
    result = _apply_locked_visible_copy(generated, "\n".join(lines), schema)
    assert result["heading"] == {"body": lines[1], "title": lines[0]}
    assert result["metadata"] == {"badge": "", "question": lines[2], "action": lines[3]}
    # Mapping is repeatable when the checkpoint is hydrated again.
    assert _apply_locked_visible_copy(copy.deepcopy(result), "\n".join(lines), schema) == result


def test_locked_copy_combines_only_where_capacity_allows():
    generated = {"badge": "改写", "body": "改写", "caption": "改写"}
    schema = {"properties": {
        "badge": {"type": "string", "maxLength": 2},
        "body": {"type": "string", "maxLength": 100},
        "caption": {"type": "string", "maxLength": 4},
    }}
    result = _apply_locked_visible_copy(generated, "小种子去旅行\n太阳公公来敲门\n小雨点来帮忙", schema)
    assert result["badge"] == result["caption"] == ""
    assert result["body"] == "小种子去旅行\n太阳公公来敲门\n小雨点来帮忙"


def test_recorded_eight_page_outline_fits_bundled_standard_layouts():
    """Replay run 21's layouts/copy without provider requests or image fees."""
    import json
    from pathlib import Path
    from templates.v2.schema import get_template_schema
    from api.v1.ppt.endpoints.presentation import (
        _apply_template_content_to_ui,
        _collect_non_decorative_text_elements,
        _template_text_required_height,
        _template_element_text,
    )
    from utils.llm_calls.generate_slide_content import _schema_fallback_value

    template = json.loads((Path(__file__).resolve().parents[3] / "templates/standard/template.json").read_text(encoding="utf-8"))
    schemas = {item["layout_id"]: item["schema"] for item in get_template_schema(template)["layouts"]}
    layouts = {item["id"]: item for item in template["layouts"]}
    cases = [
    {
        "layout": "left_image_right_cover_text_7212",
        "outline": "嘘，这里有一封春天的信！\n- 谁寄来的信？\n- 送给泥土下面的谁？\n先别拆开，猜一猜。"
    },
    {
        "layout": "left_image_right_details_2189",
        "outline": "收信人：泥土下面的小种子\n- 信上说：小种子还在泥土里睡觉。\n- 春天想请小朋友当小小送信员。\n轻轻说：小种子，快醒醒。"
    },
    {
        "layout": "center_title_cards_2395",
        "outline": "贴在泥土上听一听\n- 小种子一点声音也没有。\n- 它还在黑黑的泥土里睡觉。\n小耳朵靠近一点，听。"
    },
    {
        "layout": "left_image_right_cover_text_7212",
        "outline": "小雨点，来帮小种子喝水\n- 春天请小雨点轻轻落下。\n- 泥土变得湿湿的。\n学雨点，手指轻轻点泥士。"
    },
    {
        "layout": "center_title_cards_2395",
        "outline": "太阳公公来敲门啦\n- 阳光照在泥土上，暖暖的。\n- 小种子觉得好舒服。\n用手臂变太阳，给泥士送温暖。"
    },
    {
        "layout": "title_description_metric_cards_2015",
        "outline": "小种子现在会做什么？\n- 它喝过水，晒过太阳。\n- 它还在泥土下面。\n别着急，先想一想。"
    },
    {
        "layout": "left_timeline_center_image_right_title_6170",
        "outline": "快看，小种子发芽啦！\n- 白白的根钻下去。\n- 绿绿的小芽钻上来。\n一起数：一、二、三。"
    },
    {
        "layout": "left_image_right_title_strategy_cards_6875",
        "outline": "我们都变成小芽啦\n- 先喝水，再晒太阳。\n- 小种子慢慢长大。\n一起从泥土里长出来。"
    }
]

    def reverse_keys(value):
        if isinstance(value, dict):
            return {key: reverse_keys(child) for key, child in reversed(list(value.items()))}
        if isinstance(value, list):
            return [reverse_keys(child) for child in value]
        return value

    for case in cases:
        schema = schemas[case["layout"]]
        generated = reverse_keys(_schema_fallback_value(schema))
        content = _apply_locked_visible_copy(generated, case["outline"], schema)
        ui = _apply_template_content_to_ui(layouts[case["layout"]], content)
        elements = _collect_non_decorative_text_elements(ui["components"])
        visible = "\n".join(_template_element_text(element) for element in elements)
        for line in _outline_visible_lines(case["outline"]):
            assert line in visible, (case["layout"], line)
        for element in elements:
            height = (element.get("size") or {}).get("height")
            if isinstance(height, (int, float)):
                assert _template_text_required_height(element) <= height * 1.02, (case["layout"], _template_element_text(element))
