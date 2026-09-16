from fastapi import HTTPException

from api.v1.ppt.endpoints.kindergarten import (
    ASYNC_TASK_TYPE_KINDERGARTEN_COMPLETE,
    _is_slide_chunk,
    complete_task_progress_writable,
    friendly_complete_generation_detail,
    is_retryable_complete_generation_error,
    iter_sse_json_events,
    kindergarten_complete_task_data,
    slide_has_visible_content,
)
from enums.async_task_status import AsyncTaskStatus


def test_complete_task_type_is_dedicated_from_interactive_ppt():
    assert ASYNC_TASK_TYPE_KINDERGARTEN_COMPLETE == "kindergarten.generate_complete"


def test_generate_complete_async_route_exists():
    from api.v1.ppt.endpoints.kindergarten import KINDERGARTEN_ROUTER

    paths = [getattr(route, "path", "") for route in KINDERGARTEN_ROUTER.routes]
    assert "/kindergarten/presentation/generate-complete/async" in paths
    assert "/kindergarten/presentation/generate-complete/{task_id}/cancel" in paths


def test_complete_task_progress_stops_after_cancel_or_finish():
    assert complete_task_progress_writable(AsyncTaskStatus.PENDING)
    assert not complete_task_progress_writable(AsyncTaskStatus.ERROR)
    assert not complete_task_progress_writable(AsyncTaskStatus.COMPLETED)
    assert not complete_task_progress_writable("error")


def test_iter_sse_json_events_reads_complete_and_error_frames():
    raw = (
        'event: response\ndata: {"type": "chunk", "chunk": "{\\"index\\": 0}"}\n\n'
        'event: response\ndata: {"type": "complete"}\n\n'
        'event: response\ndata: {"type": "error", "detail": "boom"}\n\n'
        "not-json\n\n"
    )
    events = iter_sse_json_events(raw)
    assert [event["type"] for event in events] == ["chunk", "complete", "error"]
    assert events[2]["detail"] == "boom"


def test_complete_task_data_tracks_progress_and_presentation():
    data = kindergarten_complete_task_data(
        topic="园本教研",
        stage="slides",
        progress=40,
        presentation_id="abc",
        created_slides=3,
        n_slides=10,
    )
    assert data["topic"] == "园本教研"
    assert data["presentation_id"] == "abc"
    assert data["created_slides"] == 3
    assert data["remaining_slides"] == 7
    assert data["progress"] == 40
    warning = kindergarten_complete_task_data(
        topic="园本教研", stage="completed_with_warnings", progress=100,
        presentation_id="abc", created_slides=10, n_slides=10,
        warnings=["第 7 页配图待补充"], missing_image_pages=[7],
    )
    assert warning["has_warnings"] is True
    assert warning["missing_image_pages"] == [7]
    assert warning["presentation_id"] == "abc"


def test_is_slide_chunk_ignores_array_wrappers():
    assert _is_slide_chunk('{ "slides": [ ') is False
    assert _is_slide_chunk(" ] }") is False
    assert _is_slide_chunk('{"id": "s1", "index": 0}') is True


def test_rewrite_ppt_api_path_accepts_official_and_engine_urls():
    from api.main import rewrite_ppt_api_path

    assert rewrite_ppt_api_path(
        "/ppt-api/v1/ppt/kindergarten/presentation/generate-complete/async"
    ) == "/api/v1/ppt/kindergarten/presentation/generate-complete/async"
    assert rewrite_ppt_api_path(
        "/ppt-api/api/v1/ppt/kindergarten/presentation/generate-complete/async"
    ) == "/api/v1/ppt/kindergarten/presentation/generate-complete/async"
    assert rewrite_ppt_api_path(
        "/api/v1/ppt/kindergarten/presentation/generate-complete/async"
    ) == "/api/v1/ppt/kindergarten/presentation/generate-complete/async"


class _FakeSlide:
    def __init__(self, ui=None, content=None):
        self.ui = ui
        self.content = content or {}


def test_placeholder_ui_is_not_visible_content():
    slide = _FakeSlide(
        ui={
            "type": "text",
            "decorative": False,
            "runs": [{"text": "title"}],
        },
        content={"heading": {"title": "看起来有标题"}},
    )
    assert slide_has_visible_content(slide) is False


def test_applied_ui_text_counts_as_visible_content():
    slide = _FakeSlide(
        ui={
            "children": [
                {
                    "type": "text",
                    "decorative": False,
                    "runs": [{"text": "观察幼儿专注力的三种信号"}],
                }
            ]
        }
    )
    assert slide_has_visible_content(slide) is True


def test_provider_failures_are_retryable_but_layout_errors_are_not():
    assert is_retryable_complete_generation_error(
        HTTPException(status_code=500, detail="AI provider API request failed. Please try again.")
    )
    assert is_retryable_complete_generation_error(
        HTTPException(status_code=500, detail="课件页已创建但没有可见正文，请重新生成")
    )
    assert not is_retryable_complete_generation_error(
        HTTPException(
            status_code=400,
            detail="Slide 1 reviewed text does not fit any compatible layout; choose a roomier template",
        )
    )


def test_provider_error_is_shown_in_chinese():
    assert (
        friendly_complete_generation_detail(
            "AI provider API request failed. Please try again."
        )
        == "课件生成服务暂时失败，请重新生成"
    )
