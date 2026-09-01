import asyncio

from models.sql.slide import SlideModel
from services import asset_execution_service


class FailingImageService:
    def __init__(self, output_directory):
        self.output_directory = str(output_directory)
        self.calls = 0

    async def generate_image(self, _prompt):
        self.calls += 1
        raise TimeoutError("image provider timed out")

    def configured_model_name(self):
        return "failing-image-model"


def test_image_provider_failure_keeps_slide_and_returns_empty_assets(tmp_path, monkeypatch):
    traces = []

    async def record(trace):
        traces.append(trace)

    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    monkeypatch.setattr(
        asset_execution_service,
        "build_default_asset_semantic_quality_service",
        lambda: None,
    )

    slide = SlideModel(
        presentation="00000000-0000-0000-0000-000000000001",
        layout_group="test",
        layout="test",
        index=0,
        content={"main": {"picture": {"image_prompt": "a friendly little seed"}}},
        ui={
            "components": [
                {
                    "id": "main",
                    "elements": [
                        {
                            "type": "image",
                            "name": "picture",
                            "position": {"x": 100, "y": 100},
                            "size": {"width": 500, "height": 320},
                        }
                    ],
                }
            ]
        },
    )
    service = FailingImageService(tmp_path)

    generated, plan = asyncio.run(
        asset_execution_service.process_presentation_assets(service, [slide])
    )

    assert service.calls == 1
    assert len(plan) == 1
    assert generated == []
    assert "image_url" not in slide.content["main"]["picture"]
    assert len(traces) == 1
    assert traces[0].status == "failed"
    assert traces[0].error["type"] == "TimeoutError"
