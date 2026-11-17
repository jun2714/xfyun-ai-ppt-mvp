import asyncio
import copy

import pytest
from pydantic import ValidationError

from models.kindergarten_content_review import (
    REVIEW_CRITERIA,
    KindergartenContentReviewRequest,
    ModelReply,
    ProviderUsage,
)
from models.kindergarten_lesson_plan import KindergartenLessonPlan, LessonAssetSpec
from services import kindergarten_content_review_service as service
from services.kindergarten_plan_quality_service import validate_kindergarten_lesson_plan


def _plan():
    return KindergartenLessonPlan.model_validate({
        "meta": {"topic": "认识海洋动物", "age_group": "4-5岁", "domain": "science", "duration_minutes": 20},
        "lesson_goals": ["观察海龟和海豚的外形差异"],
        "lesson_arc": ["观察", "比较", "回顾"],
        "slides": [
            {"slide_no": 1, "slide_type": "cover-scene", "teaching_goal": "认识本次观察对象",
             "screen_content": {"title": "认识海洋动物", "points": []},
             "teacher_note": "邀请幼儿观察海龟和海豚的外形。", "assets": []},
            {"slide_no": 2, "slide_type": "other", "teaching_goal": "比较海龟和海豚的外形",
             "screen_content": {"title": "五大领域总复习", "points": ["唱歌、跑步、画画都学一下"]},
             "teacher_note": "教师请幼儿观察并说出两个对象的不同。", "assets": []},
            {"slide_no": 3, "slide_type": "recap", "teaching_goal": "回顾观察到的外形差异",
             "screen_content": {"title": "回顾我们的发现", "points": ["海龟有龟壳"]},
             "teacher_note": "请幼儿说出海龟与海豚的一个外形差异。", "assets": []},
        ],
    })


def _request(plan=None, **options):
    plan = plan or _plan()
    brief = {**plan.meta.model_dump(), "content_mode": "classroom", "n_slides": len(plan.slides)}
    brief.update(options.pop("brief", {}))
    return KindergartenContentReviewRequest(brief=brief, plan=plan, **options)


def _finding(issue_id="topic-1", slide_no=2, field_path="screen_content.title", evidence="五大领域总复习", **changes):
    result = {
        "issue_id": issue_id, "criterion": "topic_focus", "severity": "error",
        "slide_no": slide_no, "field_path": field_path, "evidence": evidence,
        "requirement": "围绕海洋动物外形比较展开", "explanation": "此处把目标扩展成多个无关领域",
        "suggestion": "改成观察和比较两种海洋动物的任务", "requires_source": False,
    }
    result.update(changes)
    return result


def _review(*findings, **changes):
    result = {
        "criteria_checked": list(REVIEW_CRITERIA), "findings": list(findings),
        "source_status": "not_required", "source_quotes": [],
        "needs_human": False, "human_questions": [],
    }
    result.update(changes)
    return result


def _revision(plan=None, title="观察海龟与海豚", slide_no=2, issue_ids=None, **changes):
    plan = plan or _plan()
    replacement = plan.slides[slide_no - 1].model_dump(mode="json")
    replacement["screen_content"]["title"] = title
    replacement.update(changes)
    return {"replacements": [{
        "slide_no": slide_no, "issue_ids": issue_ids or ["topic-1"], "replacement": replacement,
    }]}


class ScriptedCaller:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = []

    async def __call__(self, call):
        self.calls.append(call)
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step if isinstance(step, ModelReply) else ModelReply(payload=copy.deepcopy(step))


def _run(request, *steps):
    caller = ScriptedCaller(*steps)
    return asyncio.run(service.review_kindergarten_content(request, caller=caller)), caller


def test_located_topic_revision_is_independently_reviewed_and_preserves_other_pages():
    request = _request(max_revision_rounds=1)
    before = request.plan.model_dump()
    result, caller = _run(request, _review(_finding()), _revision(), _review())
    assert result.status == "passed"
    assert result.rounds_completed == 1
    assert result.call_attempts == 3
    assert [call.stage for call in caller.calls] == ["review", "revise", "review"]
    assert result.plan.slides[1].screen_content.title == "观察海龟与海豚"
    assert result.plan.slides[0] == request.plan.slides[0]
    assert result.plan.slides[2] == request.plan.slides[2]
    assert result.plan.meta == request.plan.meta
    assert result.plan.lesson_goals == request.plan.lesson_goals
    assert result.plan.lesson_arc == request.plan.lesson_arc
    assert request.plan.model_dump() == before == result.original_plan.model_dump()
    assert set(caller.calls[2].payload) == {"brief", "plan", "machine_quality"}
    assert result.visual_validation == "not_performed"


def test_default_review_does_not_revise_or_multiply_model_calls():
    result, caller = _run(_request(), _review(_finding()))
    assert result.status == "needs_revision"
    assert result.plan == result.original_plan
    assert len(caller.calls) == result.call_attempts == 1


@pytest.mark.parametrize("finding,code", [
    (_finding(evidence="不存在的原文"), "evidence_quote_mismatch"),
    (_finding(slide_no=4), "evidence_slide_missing"),
    (_finding(field_path="__class__.__name__"), "invalid_evidence_path"),
    (_finding(field_path="screen_content.points.999"), "invalid_evidence_path"),
])
def test_fabricated_evidence_or_page_is_rejected_without_revision(finding, code):
    result, caller = _run(_request(max_revision_rounds=2), _review(finding))
    assert result.status == "invalid_output"
    assert result.failure_code == code
    assert result.semantic_review is None
    assert result.calls[0].outcome == "invalid_output"
    assert len(caller.calls) == 1
    assert result.plan == result.original_plan


@pytest.mark.parametrize("payload", [
    {**_review(), "passed": True},
    {**_review(), "criteria_checked": ["topic_focus"]},
    {**_review(), "source_quotes": ["伪造来源"]},
])
def test_model_cannot_self_certify_or_skip_review_dimensions(payload):
    result, _ = _run(_request(), payload)
    assert result.status == "invalid_output"


@pytest.mark.parametrize("report", [
    _review(source_status="insufficient"),
    _review(source_status="sufficient", source_quotes=[]),
    _review(_finding(requires_source=True)),
])
def test_missing_source_forces_human_review_even_if_model_says_otherwise(report):
    result, caller = _run(_request(max_revision_rounds=2), report)
    assert result.status == "needs_human"
    assert result.semantic_review.needs_human
    assert result.semantic_review.human_questions
    assert result.semantic_review.source_status == "insufficient"
    assert len(caller.calls) == 1


def test_verifiable_supplied_source_is_retained_as_evidence():
    result, _ = _run(_request(brief={"source_context": "本次活动只比较海龟与海豚。"}),
                     _review(source_status="sufficient", source_quotes=["只比较海龟与海豚"]))
    assert result.status == "passed"
    assert result.semantic_review.source_quotes == ["只比较海龟与海豚"]


@pytest.mark.parametrize("brief", [{"topic": "森林动物"}, {"age_group": "5-6岁"},
                                    {"domain": "language"}, {"duration_minutes": 30}, {"n_slides": 4}])
def test_brief_plan_mismatch_never_spends_a_model_call(brief):
    result, caller = _run(_request(brief=brief))
    assert result.status == "needs_human"
    assert result.failure_code == "brief_plan_constraints_mismatch"
    assert result.call_attempts == 0
    assert caller.calls == []


def test_reviser_cannot_change_an_unreported_page():
    result, _ = _run(_request(max_revision_rounds=1), _review(_finding()), _revision(slide_no=3))
    assert result.status == "revision_rejected"
    assert result.failure_code == "revision_outside_target_pages"
    assert result.plan == result.original_plan


def test_whole_plan_override_is_not_a_valid_patch():
    patch = {**_revision(), "plan": _plan().model_dump()}
    patch["plan"]["meta"]["topic"] = "被擅自改成另一个主题"
    result, _ = _run(_request(max_revision_rounds=1), _review(_finding()), patch)
    assert result.status == "revision_rejected"
    assert result.failure_code == "revision_schema_invalid"
    assert result.plan == result.original_plan


def test_editing_unrelated_field_cannot_resolve_reported_evidence():
    patch = _revision(title="五大领域总复习", teacher_note="只改了备注，原来被引用的错误标题没有改。")
    result, _ = _run(_request(max_revision_rounds=1), _review(_finding()), patch)
    assert result.status == "revision_rejected"
    assert result.failure_code == "revision_evidence_field_unchanged"
    assert result.call_attempts == 2


def test_new_deterministic_error_rejects_revision_before_adoption():
    patch = _revision(slide_type="guess-partial", game=None)
    result, _ = _run(_request(max_revision_rounds=1), _review(_finding()), patch)
    assert result.status == "revision_rejected"
    assert result.failure_code == "revision_introduced_machine_errors"
    assert result.machine_quality.passed
    assert result.plan == result.original_plan


def test_reviser_cannot_delete_both_question_and_reveal_contracts_to_manufacture_pass():
    from test_kindergarten_plan_quality_service import _valid_plan

    plan = _valid_plan()
    findings, replacements = [], []
    for number in (2, 3):
        old = plan.slides[number - 1]
        issue_id = f"title-{number}"
        findings.append(_finding(issue_id=issue_id, slide_no=number, evidence=old.screen_content.title))
        new = old.model_dump(mode="json")
        new.update({"slide_type": "other", "game": None})
        new["screen_content"]["title"] = "修改后的标题"
        replacements.append({"slide_no": number, "issue_ids": [issue_id], "replacement": new})
    result, _ = _run(_request(plan, max_revision_rounds=1), _review(*findings),
                     {"replacements": replacements}, _review())
    assert result.status == "revision_rejected"
    assert result.failure_code == "revision_removed_teaching_role"
    assert result.plan == plan
    assert result.call_attempts == 2


@pytest.mark.parametrize("mode", ["remove", "disable_required", "disable_qa"])
def test_reviser_cannot_remove_required_visual_contract(mode):
    plan = _plan()
    plan.slides[1].assets = [LessonAssetSpec(
        slot="animal", semantic_label="海龟", description="一只完整海龟，龟壳清晰可见",
        required=True, qa_required=True,
    )]
    patch = _revision(plan)
    assets = patch["replacements"][0]["replacement"]["assets"]
    if mode == "remove":
        assets.clear()
    elif mode == "disable_required":
        assets[0]["required"] = False
    else:
        assets[0]["qa_required"] = False
    result, _ = _run(_request(plan, max_revision_rounds=1), _review(_finding()), patch)
    assert result.status == "revision_rejected"
    assert result.failure_code == "revision_removed_required_visual"
    assert result.plan == plan


def test_provider_error_is_not_a_pass_and_does_not_leak_exception_detail():
    result, caller = _run(_request(), RuntimeError("private-key-should-never-appear"))
    assert result.status == "model_error"
    assert result.semantic_review is None
    assert result.call_attempts == len(caller.calls) == 1
    assert "private-key" not in result.model_dump_json()


def test_provider_reported_usage_survives_invalid_json_error():
    class ReviewProviderError(RuntimeError):
        pass

    failure = ReviewProviderError("review_provider_invalid_json")
    failure.submitted = True
    failure.model = "actual-model"
    failure.usage = ProviderUsage(input_tokens=30, output_tokens=10, total_tokens=40)
    result, _ = _run(_request(), failure)
    assert result.status == "model_error"
    assert result.calls[0].submitted is True
    assert result.calls[0].usage.total_tokens == 40
    assert result.calls[0].model == "actual-model"
    assert result.calls[0].error_code == "review_provider_invalid_json"


def test_failure_during_rereview_retains_previously_reviewed_draft():
    result, _ = _run(_request(max_revision_rounds=1), _review(_finding()), _revision(), RuntimeError("failure"))
    assert result.status == "model_error"
    assert result.plan == result.original_plan
    assert result.rounds_completed == 0
    assert result.call_attempts == 3
    assert len(result.review_history) == 1


def test_no_reduction_in_errors_stops_loop_and_rejects_candidate():
    result, caller = _run(_request(max_revision_rounds=2), _review(_finding()), _revision(),
                          _review(_finding(evidence="观察海龟与海豚")))
    assert result.status == "no_progress"
    assert result.plan == result.original_plan
    assert result.rounds_completed == 1
    assert result.review_history[-1].adopted is False
    assert len(caller.calls) == 3


def test_two_revision_rounds_is_a_hard_limit_even_when_remaining_issues_improve():
    initial = _plan()
    issue1 = _finding()
    issue2 = _finding("point-1", field_path="screen_content.points.0", evidence="唱歌、跑步、画画都学一下")
    issue3 = _finding("recap-1", slide_no=3, evidence="回顾我们的发现")
    patch1 = _revision(initial)
    candidate1 = initial.model_copy(deep=True)
    candidate1.slides[1].screen_content.title = "观察海龟与海豚"
    patch2 = _revision(candidate1, issue_ids=["point-1"])
    patch2["replacements"][0]["replacement"]["screen_content"]["points"] = ["找一找海龟的龟壳"]
    result, caller = _run(_request(initial, max_revision_rounds=2),
                          _review(issue1, issue2, issue3), patch1, _review(issue2, issue3), patch2, _review(issue3))
    assert result.status == "max_rounds_reached"
    assert result.rounds_completed == 2
    assert result.call_attempts == len(caller.calls) == 5
    assert result.plan.slides[1].screen_content.points == ["找一找海龟的龟壳"]
    assert len(result.semantic_review.findings) == 1


def test_call_budget_reserves_independent_rereview_before_editing():
    result, caller = _run(_request(max_revision_rounds=2, max_model_calls=2), _review(_finding()))
    assert result.status == "budget_exhausted"
    assert result.plan == result.original_plan
    assert len(caller.calls) == 1


def test_unknown_provider_usage_stays_unknown_and_reported_usage_is_preserved():
    unknown, _ = _run(_request(), _review())
    assert unknown.calls[0].usage is None
    assert unknown.calls[0].submitted is None
    usage = ProviderUsage(input_tokens=123, output_tokens=45, total_tokens=168)
    known, _ = _run(_request(), ModelReply(payload=_review(), usage=usage, model="test-model", submitted=True))
    assert known.calls[0].usage == usage
    assert known.calls[0].usage.cached_input_tokens is None
    assert known.calls[0].submitted is True
    assert known.calls[0].elapsed_ms >= 0


def test_cancellation_before_submission_does_not_invoke_provider():
    async def disconnected():
        return True

    caller = ScriptedCaller()
    result = asyncio.run(service.review_kindergarten_content(_request(), caller=caller, disconnect_checker=disconnected))
    assert result.status == "cancelled"
    assert result.call_attempts == 0
    assert result.plan == result.original_plan


def test_client_cancellation_stops_inflight_caller_and_preserves_original():
    state = {"started": False, "cancelled": False}

    async def caller(call):
        state["started"] = True
        try:
            await asyncio.Event().wait()
        finally:
            state["cancelled"] = True

    async def disconnected():
        return state["started"]

    result = asyncio.run(service.review_kindergarten_content(_request(), caller=caller, disconnect_checker=disconnected))
    assert result.status == "cancelled"
    assert state["cancelled"] is True
    assert result.calls[0].outcome == "cancelled"
    assert result.plan == result.original_plan


def test_total_timeout_stops_waiting_and_preserves_original():
    state = {"cancelled": False}

    async def caller(call):
        try:
            await asyncio.Event().wait()
        finally:
            state["cancelled"] = True

    result = asyncio.run(service.review_kindergarten_content(_request(timeout_seconds=1), caller=caller))
    assert result.status == "timeout"
    assert result.calls[0].outcome == "timeout"
    assert result.plan == result.original_plan
    assert state["cancelled"] is True
    assert result.elapsed_ms < 2500


def test_task_cancellation_returns_preserved_draft():
    async def run():
        started = asyncio.Event()

        async def caller(call):
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(service.review_kindergarten_content(_request(), caller=caller))
        await started.wait()
        task.cancel()
        return await task

    result = asyncio.run(run())
    assert result.status == "cancelled"
    assert result.plan == result.original_plan


def test_training_mode_reaches_every_deterministic_check_and_each_model_context(monkeypatch):
    modes = []

    def validate(plan, *, content_mode):
        modes.append(content_mode)
        return validate_kindergarten_lesson_plan(plan, content_mode=content_mode)

    monkeypatch.setattr(service, "validate_kindergarten_lesson_plan", validate)
    result, caller = _run(_request(brief={"content_mode": "training"}, max_revision_rounds=1),
                          _review(_finding()), _revision(), _review())
    assert result.status == "passed"
    assert len(modes) >= 2 and set(modes) == {"training"}
    assert all(call.payload["brief"]["content_mode"] == "training" for call in caller.calls)


def test_request_rejects_unbounded_rounds_and_timeouts():
    for options in ({"max_revision_rounds": 3}, {"timeout_seconds": 0}, {"max_model_calls": 100}):
        with pytest.raises(ValidationError):
            _request(**options)
