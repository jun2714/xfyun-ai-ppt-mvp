from api.v1.ppt.endpoints.presentation import _presentation_task_progress_data


def test_generation_progress_preserves_paid_outline_checkpoint():
    checkpoint = _presentation_task_progress_data(
        0,
        5,
        stage="selecting_layouts",
        outlines={"slides": [{"content": "已生成的大纲"}]},
    )

    updated = _presentation_task_progress_data(
        2,
        3,
        previous=checkpoint,
        stage="generating_slide_content",
    )

    assert updated["outlines"] == checkpoint["outlines"]
    assert updated["stage"] == "generating_slide_content"
    assert updated["created_slides"] == 2
