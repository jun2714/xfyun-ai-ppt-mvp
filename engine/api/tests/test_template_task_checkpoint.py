import os
from pathlib import Path
import tempfile

_test_db_path = (Path(tempfile.gettempdir()) / "presenton-template-checkpoint.db").as_posix()
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_path}"

from api.v1.ppt.endpoints.template import (
    CreateTemplateRequest,
    _checkpointed_template_layouts,
    _template_task_progress_data,
)
from enums.async_task_status import AsyncTaskStatus
from models.sql.async_task import AsyncTaskModel
from templates.v2.models.layouts import SlideLayout


def test_template_task_progress_persists_request_and_generated_layouts():
    request = CreateTemplateRequest(
        pptx_url="/app_data/source.pptx",
        slide_image_urls=["/app_data/slide-1.png", "/app_data/slide-2.png"],
        fonts={"ZCOOL Kuai Le": "/app_data/fonts/zcool.ttf"},
        name="幼儿园模板",
    )
    layout = SlideLayout(
        id="opening",
        description="A reusable opening layout for a kindergarten presentation.",
        components=[],
    )
    data = _template_task_progress_data(
        created_layouts=1,
        remaining_layouts=1,
        completed_layout_indices={0},
        request=request,
        generated_layouts_by_index={0: layout},
    )

    task = AsyncTaskModel(
        type="template.create",
        status=AsyncTaskStatus.PENDING,
        data=data,
    )
    restored = _checkpointed_template_layouts(task)

    assert data["request"]["pptx_url"] == request.pptx_url
    assert data["slide_layout_statuses"] == [
        {"index": 0, "status": "completed"},
        {"index": 1, "status": "pending"},
    ]
    assert restored[0] == layout
