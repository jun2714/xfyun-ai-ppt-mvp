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
    assert "忠于这些锚点、孩子愿意参与" in user_prompt
    assert "儿童惊喜钩子" in user_prompt


def test_classroom_prompt_uses_generic_topic_semantic_anchors():
    messages = build_kindergarten_lesson_messages(
        topic="我长大了",
        age_group="4-5岁",
        domain="comprehensive",
        duration_minutes=20,
        n_slides=6,
        instructions=None,
        source_context=None,
    )

    system_prompt = messages[0].content
    user_prompt = messages[1].content
    assert "用户原始主题是不可替换的语义锚点" in system_prompt
    assert "真实主角/对象、核心变化或认知任务、最终教学目标" in user_prompt
    assert "用户未提出的新角色不得进入 lesson_arc" in user_prompt
    assert "过去的我—看得见的变化" not in user_prompt


def test_training_prompt_stays_teacher_facing_and_problem_driven():
    messages = build_kindergarten_lesson_messages(
        topic="主题环境创设追随班本课程推进",
        age_group="教师教研",
        domain="comprehensive",
        duration_minutes=40,
        n_slides=10,
        instructions="分析环境一学期不变、区域创设指导性过强的问题",
        source_context=None,
        content_mode="training",
    )

    system_prompt = messages[0].content
    user_prompt = messages[1].content
    assert "园本教研" in system_prompt
    assert "不得擅自换成儿童知识主题" in system_prompt
    assert "问题呈现—原因分析" in system_prompt
    assert "不得写成幼儿课堂" in user_prompt
    assert "不得出现儿童口吻" in user_prompt
    assert "主观判断：" in system_prompt
    assert "客观证据：" in system_prompt
    assert "问题表现：" in system_prompt
    assert "解决动作：" in system_prompt


def test_training_normalization_forces_real_cover_slide():
    source = _plan().model_copy(
        update={
            "meta": _plan().meta.model_copy(
                update={"topic": "主题环境创设追随班本课程推进，解决环境长期不变"}
            )
        }
    )

    normalized = planning_service._normalize_training_contracts(source)
    first = normalized.slides[0]
    outline = normalized.to_presentation_outline()

    assert first.slide_type == "cover-scene"
    assert first.screen_content.title == "主题环境创设追随班本课程推进"
    assert first.screen_content.points[0].startswith("培训目的：")
    assert first.screen_content.points[1] == "幼儿园园本教研培训"
    assert first.screen_content.instruction is None
    assert first.interaction.type == "none"
    assert first.layout_capabilities == ["scene", "single-focus"]
    assert outline.slides[0].content_contract.relationship == "single"


def test_training_normalization_structures_evidence_and_problem_solution():
    def slide(no, title, points):
        return {
            "slide_no": no,
            "slide_type": "other",
            "teaching_goal": title,
            "screen_content": {"title": title, "points": points},
            "teacher_note": f"讲解{title}",
            "assets": [],
        }

    source = KindergartenLessonPlan.model_validate(
        {
            "meta": {
                "topic": "主题环境创设追随班本课程推进",
                "age_group": "教师教研",
                "domain": "comprehensive",
                "duration_minutes": 40,
            },
            "lesson_goals": ["形成环境调整方案"],
            "lesson_arc": ["问题", "证据", "行动", "验证"],
            "slides": [
                slide(1, "直接进入内容", ["培训说明"]),
                slide(
                    2,
                    "先看事实",
                    [
                        "客观证据：主题墙连续八周没有变化",
                        "主观判断：教师认为环境已经够丰富",
                        "补充解释",
                    ],
                ),
                slide(3, "环境为什么一学期不变", ["缺少调整触发机制"]),
                slide(4, "三阶段调整环境", ["识别事件", "小步调整", "记录反馈"]),
                slide(5, "用什么指标验证", ["每周记录一次环境变化"]),
                slide(6, "带回班级", ["确定下周行动"]),
            ],
        }
    )

    normalized = planning_service._normalize_training_contracts(source)
    evidence = normalized.slides[1]
    solution = normalized.slides[4]

    assert evidence.slide_type == "compare"
    assert evidence.screen_content.points[0].startswith("主观判断：")
    assert evidence.screen_content.points[1].startswith("客观证据：")
    assert solution.screen_content.title == "问题如何解决并验证"
    assert [point.split("：", 1)[0] for point in solution.screen_content.points] == [
        "问题表现",
        "解决动作",
        "验证指标",
    ]
    assert "problem-solution" in solution.layout_capabilities


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


def test_failed_outline_is_marked_for_dashboard_cleanup():
    presentation = SimpleNamespace(
        id=uuid.uuid4(),
        theme={"kindergarten_generation": {"outline_status": "pending"}},
    )

    class FakeSession:
        rolled_back = False
        committed = False

        async def rollback(self):
            self.rolled_back = True

        def add(self, _value):
            return None

        async def commit(self):
            self.committed = True

    session = FakeSession()
    asyncio.run(
        kindergarten_endpoint._persist_outline_failure(
            presentation,
            "模型生成失败",
            session,
        )
    )

    generation = presentation.theme["kindergarten_generation"]
    assert session.rolled_back is True
    assert session.committed is True
    assert generation["outline_status"] == "failed"
    assert generation["outline_error"] == "模型生成失败"


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


def test_classroom_without_cover_gets_cover_without_losing_opening_content():
    plan = _plan()
    original_content = plan.slides[1].screen_content.title
    source = plan.model_copy(
        update={
            "slides": [
                slide.model_copy(update={"slide_no": index})
                for index, slide in enumerate(plan.slides[1:], start=1)
            ]
        }
    )

    normalized = planning_service._ensure_cover_contract(source, "classroom")

    assert len(normalized.slides) == len(source.slides) + 1
    assert normalized.slides[0].slide_type == "cover-scene"
    assert normalized.slides[0].screen_content.title == "认识森林动物"
    assert normalized.slides[0].screen_content.points[0].startswith("活动目标：")
    assert normalized.slides[0].screen_content.points[1] == "幼儿园集体教学"
    assert normalized.slides[1].screen_content.title == original_content
    assert [slide.slide_no for slide in normalized.slides] == [1, 2, 3]


def test_cover_insert_never_discards_closing_to_keep_requested_page_count():
    import pytest
    plan = _plan()
    source = plan.model_copy(
        update={
            "slides": [
                slide.model_copy(update={"slide_no": index, "slide_type": "other"})
                for index, slide in enumerate(plan.slides, start=1)
            ]
        }
    )

    with pytest.raises(ValueError, match="不能自动删除末页正文"):
        planning_service._ensure_cover_contract(
            source, "classroom", target_count=len(source.slides)
        )


def test_generated_reveal_uses_answer_text_instead_of_option_id():
    plan = _plan()
    plan.slides = plan.slides[:2]
    repaired = planning_service._repair_classroom_activity_contracts(plan)
    reveal = repaired.slides[2]
    assert reveal.screen_content.points == ["正确答案：小兔子"]
    assert reveal.assets[0].semantic_label == "小兔子"
    assert reveal.game.answer_key == "B"


def test_training_template_mode_does_not_use_child_classroom_pack():
    from api.v1.ppt.endpoints.kindergarten import (
        KindergartenPresentationCreateRequest, _apply_visual_mode,
    )
    plan = _plan()
    result = planning_service.ValidatedKindergartenPlanningResult(
        plan=plan, outline=plan.to_presentation_outline(),
        quality=planning_service.validate_kindergarten_lesson_plan(plan), attempts=1,
    )
    payload = KindergartenPresentationCreateRequest(
        topic="教师观察记录培训", content_mode="training", template="auto",
    )
    _, routing, _ = _apply_visual_mode(payload, result)
    assert routing.template == "teacher-training"


def test_missing_reveal_does_not_expand_requested_deck_or_drop_closing():
    plan = _plan()
    plan.slides = plan.slides[:2]
    closing = plan.slides[-1].model_copy(update={
        "slide_no": 3, "slide_type": "recap", "game": None,
    })
    plan.slides.append(closing)
    repaired = planning_service._repair_classroom_activity_contracts(plan, max_slides=3)
    assert len(repaired.slides) == 3
    assert repaired.slides[-1] == closing
    report = planning_service.validate_kindergarten_lesson_plan(repaired)
    assert any(issue.code == "reveal-slide-missing" for issue in report.errors)


def test_forty_page_plan_without_cover_fails_instead_of_dropping_content():
    import pytest

    plan = _plan()
    source_slide = plan.slides[0].model_copy(
        update={"slide_type": "other"}
    )
    plan = plan.model_copy(
        update={
            "slides": [
                source_slide.model_copy(update={"slide_no": index})
                for index in range(1, 41)
            ]
        }
    )

    with pytest.raises(ValueError, match="无法在不丢失正文"):
        planning_service._ensure_cover_contract(plan, "classroom")


def test_training_sequence_without_game_keeps_sequence_layout_semantics():
    plan = _plan()
    sequence = plan.slides[1].model_copy(
        update={
            "slide_type": "sequence",
            "game": None,
            "layout_capabilities": ["scene", "sequence"],
        }
    )
    plan = plan.model_copy(
        update={"slides": [plan.slides[0], sequence, plan.slides[2]]}
    )

    normalized = planning_service._normalize_training_contracts(plan)

    assert normalized.slides[1].slide_type == "sequence"
    assert "sequence" in normalized.slides[1].layout_capabilities


def _training_steps_plan():
    plan = _plan()
    plan.meta.topic = "如何记录儿童游戏证据"
    plan.lesson_goals = ["区分主观判断与可观察的证据"]
    plan.lesson_arc = ["提出问题", "练习记录", "复盘验证"]
    for index, slide in enumerate(plan.slides):
        slide.slide_type = ["cover-scene", "sequence", "recap"][index]
        slide.screen_content.title = [plan.meta.topic, "三步记录证据", "复盘本周记录"][index]
        slide.screen_content.points = ["记录时间和儿童原话", "描述动作，再讨论支持策略"]
        slide.screen_content.instruction = None
        slide.game = None
        slide.teacher_note = "组织教师讨论真实记录。"
        slide.teaching_goal = "用可观察证据讨论支持策略"
        slide.assets = []
        slide.layout_capabilities = ["scene", "sequence"] if index == 1 else ["scene"]
    return plan


def test_training_steps_are_not_a_child_sorting_game():
    plan = _training_steps_plan()
    assert planning_service.validate_kindergarten_lesson_plan(plan, content_mode="training").passed
    classroom_report = planning_service.validate_kindergarten_lesson_plan(plan)
    assert "game-contract-missing" in {issue.code for issue in classroom_report.errors}


def test_training_still_validates_explicit_sorting_game_answers():
    from models.kindergarten_lesson_plan import LessonGameSpec
    plan = _training_steps_plan()
    plan.slides[1].game = LessonGameSpec(type="sequence", activity_id="record-steps")
    report = planning_service.validate_kindergarten_lesson_plan(plan, content_mode="training")
    assert "sequence-order-missing" in {issue.code for issue in report.errors}


def test_training_steps_and_stale_caption_are_repaired_without_regenerating(monkeypatch):
    from models.kindergarten_lesson_plan import LessonAssetSpec
    plan = _training_steps_plan()
    plan.slides[1].assets = [LessonAssetSpec(
        slot="evidence", semantic_label="教师观察记录",
        description="教师在游戏现场记录儿童原话与动作，不包含文字。",
        audience_text="这是正文整理前的旧句子",
    )]
    calls = []
    async def fake_generate(**kwargs):
        calls.append(kwargs)
        return plan
    monkeypatch.setattr(planning_service, "generate_kindergarten_lesson_plan", fake_generate)
    result = asyncio.run(planning_service.generate_validated_kindergarten_presentation_outline(
        topic=plan.meta.topic, age_group="教师", domain="comprehensive", duration_minutes=20,
        n_slides=3, instructions=None, source_context=None, content_mode="training",
    ))
    assert result.quality.passed
    assert len(calls) == 1
    assert result.plan.slides[1].slide_type == "sequence"
    assert result.plan.slides[1].screen_content.points == plan.slides[1].screen_content.points
    assert result.plan.slides[1].assets[0].audience_text is None
    assert result.plan.slides[1].assets[0].semantic_label == "教师观察记录"


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


def test_missing_reveal_and_unlisted_answer_are_completed_locally():
    from services.kindergarten_plan_quality_service import validate_kindergarten_lesson_plan

    plan = _plan()
    question = plan.slides[1]
    broken_question = question.model_copy(
        update={
            "game": question.game.model_copy(
                update={"answer_key": "小松鼠"}
            )
        }
    )
    plan = plan.model_copy(
        update={"slides": [plan.slides[0], broken_question]}
    )
    report = validate_kindergarten_lesson_plan(plan)

    assert {
        "answer-not-in-options",
        "reveal-slide-missing",
    }.issubset({issue.code for issue in report.errors})

    repaired = planning_service._repair_machine_contracts(plan, report)
    repaired_report = validate_kindergarten_lesson_plan(repaired)

    assert repaired_report.passed
    assert len(repaired.slides) == 3
    assert repaired.slides[1].game.options["答案"] == "小松鼠"
    assert repaired.slides[2].slide_type == "answer-reveal"
    assert repaired.slides[2].game.activity_id == repaired.slides[1].game.activity_id
    assert repaired.slides[2].screen_content.points == ["正确答案：小松鼠"]


def test_answer_in_question_cannot_be_hidden_by_removing_game_metadata():
    from services.kindergarten_plan_quality_service import validate_kindergarten_lesson_plan
    plan = _plan()
    plan.slides[1].screen_content.points.append("答案是小兔子")
    report = validate_kindergarten_lesson_plan(plan)
    assert "question-reveals-answer" in {issue.code for issue in report.errors}
    repaired = planning_service._repair_machine_contracts(plan, report)
    assert not validate_kindergarten_lesson_plan(repaired).passed
    assert repaired.slides[1].slide_type == "guess-partial"


def test_unproven_caption_binding_falls_back_to_scene_without_discarding_lesson():
    from services.kindergarten_plan_quality_service import validate_kindergarten_lesson_plan
    from services.classroom_content_mapping import preferred_classroom_layout
    plan = _plan(reveal_answer="A")
    plan.slides[1].assets[0].audience_text = "小兔子的耳朵真长呀"
    original = plan.to_presentation_outline().slides[1].content
    report = validate_kindergarten_lesson_plan(plan)
    repaired = planning_service._repair_machine_contracts(plan, report)
    assert validate_kindergarten_lesson_plan(repaired).passed
    outline = repaired.to_presentation_outline().slides[1]
    assert outline.content == original
    assert outline.content_contract.asset_contracts[0].audience_text is None
    assert preferred_classroom_layout(outline).startswith("classroom_scene_")
    assert repaired.slides[2].game.answer_key == "B"


def test_invalid_game_contract_cannot_be_hidden_by_downgrading_the_question(monkeypatch):
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

    import pytest
    with pytest.raises(planning_service.KindergartenPlanningQualityError):
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

    assert len(calls) == 1
    assert plan.slides[1].slide_type == "guess-partial"
