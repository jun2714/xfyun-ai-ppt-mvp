import asyncio
import json

import pytest
from pydantic import ValidationError

from api.v1.ppt.endpoints.kindergarten import (
    KindergartenPresentationCreateRequest,
    _planning_source_context,
)
from models.research_plan_source import ResearchPlanSource


def test_async_request_roundtrip_preserves_shared_case_and_task():
    source = {
        "title": "孩子说话时要不要提醒？",
        "cases": [{"scene": "绘本活动", "source": "模拟案例", "observedBehavior": "转头两次", "childResponse": "待观察"}],
        "teacherStrategies": [{"action": "先听一听", "say": "你发现了什么？"}],
        "tool": {"name": "观察卡", "fields": ["行为", "回应", "变化"]},
        "actionTask": {"task": "下次活动观察一名幼儿"},
    }
    request = KindergartenPresentationCreateRequest(
        topic=source["title"], content_mode="training", research_plan=source,
        source_context="过期文档，不应覆盖同源方案",
    )
    # Async tasks persist the request as JSON and reconstruct it in a worker.
    restored = KindergartenPresentationCreateRequest.model_validate_json(request.model_dump_json())
    context = asyncio.run(_planning_source_context(restored))
    assert "过期文档" not in context
    received = json.loads(context[context.index("{"):])
    assert received["cases"][0]["childResponse"] == "待观察"
    assert received["cases"][0]["source"] == "模拟案例"
    assert received["teacherStrategies"][0]["say"] == "你发现了什么？"
    assert received["tool"]["fields"] == source["tool"]["fields"]
    assert received["actionTask"]["task"] == source["actionTask"]["task"]


def test_old_text_only_requests_and_old_structured_plans_remain_usable():
    request = KindergartenPresentationCreateRequest(topic="旧方案", content_mode="training", source_context="原有方案文本")
    assert asyncio.run(_planning_source_context(request)) == "原有方案文本"
    old = ResearchPlanSource(title="旧方案", goals=["观察儿童"])
    assert old.cases == []
    assert "观察儿童" in old.planning_context()


def test_research_source_cannot_silently_enter_child_classroom_mode():
    with pytest.raises(ValidationError, match="仅用于教师教研"):
        KindergartenPresentationCreateRequest(topic="方案", research_plan={"title": "方案"})


def test_oversized_source_is_rejected_instead_of_truncating_case_or_task():
    with pytest.raises(ValidationError, match="30000"):
        ResearchPlanSource(title="方案", goals=["观" * 6000] * 6)
