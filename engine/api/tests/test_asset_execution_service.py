import asyncio

from PIL import Image, ImageDraw

from models.sql.image_asset import ImageAsset
from models.sql.slide import SlideModel
from services import asset_execution_service


class FakeImageService:
    def __init__(self, output_directory, outputs):
        self.output_directory = str(output_directory)
        self.outputs = list(outputs)
        self.calls = 0

    async def generate_image(self, _prompt):
        output = self.outputs[self.calls]
        self.calls += 1
        return ImageAsset(path=str(output), is_uploaded=False)

    def configured_model_name(self):
        return "fake-image-model"


def _cutout_slide() -> SlideModel:
    return SlideModel(
        presentation="00000000-0000-0000-0000-000000000001",
        layout_group="test",
        layout="test",
        index=0,
        content={"main": {"subject": {"image_prompt": "A red toy"}}},
        ui={
            "components": [
                {
                    "id": "main",
                    "elements": [
                        {
                            "type": "image",
                            "name": "subject",
                            "position": {"x": 200, "y": 100},
                            "size": {"width": 400, "height": 400},
                            "asset_role": "cutout",
                        }
                    ],
                }
            ]
        },
    )


def test_cutout_validation_retries_only_failed_asset(tmp_path, monkeypatch):
    invalid = tmp_path / "invalid.png"
    Image.new("RGB", (600, 600), "red").save(invalid)
    valid = tmp_path / "valid.png"
    image = Image.new("RGB", (600, 600), "white")
    ImageDraw.Draw(image).ellipse((160, 120, 440, 480), fill="red")
    image.save(valid)

    async def no_ocr(result, _output_directory, _ocr_service):
        return result

    traces = []

    async def record(trace):
        traces.append(trace)

    monkeypatch.setattr(
        asset_execution_service, "materialize_and_validate_no_text", no_ocr
    )
    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    service = FakeImageService(tmp_path, [invalid, valid])
    slide = _cutout_slide()

    generated, plan = asyncio.run(
        asset_execution_service.process_presentation_assets(service, [slide])
    )

    assert service.calls == 2
    assert [trace.status for trace in traces] == ["failed", "succeeded"]
    assert traces[1].retry_of == plan[0].request_id
    assert len(generated) == 2  # accepted source plus derived transparent cutout
    assert "image_url" in slide.content["main"]["subject"]
