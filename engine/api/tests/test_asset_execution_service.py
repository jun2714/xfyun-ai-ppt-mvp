import asyncio

from PIL import Image, ImageDraw

from models.sql.image_asset import ImageAsset
from models.sql.slide import SlideModel
from services import asset_execution_service
from services.asset_semantic_quality_service import (
    AssetSemanticCheck,
    AssetSemanticQualityResult,
)


class FakeImageService:
    def __init__(self, output_directory, outputs):
        self.output_directory = str(output_directory)
        self.outputs = list(outputs)
        self.calls = 0
        self.prompts = []

    async def generate_image(self, prompt):
        self.prompts.append(prompt.prompt)
        output = self.outputs[self.calls]
        self.calls += 1
        return ImageAsset(path=str(output), is_uploaded=False)

    def configured_model_name(self):
        return "fake-image-model"


class FakeSemanticQualityService:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def validate(self, image, expectations):
        passed = self.outcomes[len(self.calls)]
        self.calls.append(
            {
                "image": image.path if isinstance(image, ImageAsset) else image,
                "expectations": expectations,
            }
        )
        checks = [
            AssetSemanticCheck(
                planning_slot=expectation.planning_slot,
                semantic_label=expectation.semantic_label,
                present=passed,
                detected_count=expectation.expected_count if passed else 0,
                features_match=passed,
                confidence=0.99,
                reason="符合资产契约" if passed else "检测到的主体与资产契约不符",
            )
            for expectation in expectations
        ]
        return AssetSemanticQualityResult(
            passed=passed,
            checks=checks,
            overall_reason="通过" if passed else "主体语义错误",
            provider="fake",
            model="fake-vision-model",
        )


def _cutout_slide(
    *,
    index: int = 0,
    prompt: str = "A red toy",
    semantic_label: str = "red toy",
    with_semantic_contract: bool = False,
    description: str | None = "One complete subject, clearly recognizable",
) -> SlideModel:
    content = {"main": {"subject": {"image_prompt": prompt}}}
    if with_semantic_contract:
        content["__content_contract__"] = {
            "required_asset_semantics": [semantic_label],
            "asset_contracts": [
                {
                    "planning_slot": "subject",
                    "semantic_label": semantic_label,
                    "description": description,
                    "expected_count": 1,
                    "role": "cutout",
                    "qa_required": True,
                }
            ],
        }
    return SlideModel(
        presentation="00000000-0000-0000-0000-000000000001",
        layout_group="test",
        layout="test",
        index=index,
        content=content,
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


def _valid_cutout_source(path):
    image = Image.new("RGB", (600, 600), "white")
    ImageDraw.Draw(image).ellipse((160, 120, 440, 480), fill="red")
    image.save(path)


def test_semantic_qa_retries_only_failed_asset_and_accepts_null_description(
    tmp_path, monkeypatch
):
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _valid_cutout_source(first)
    _valid_cutout_source(second)

    traces = []

    async def record(trace):
        traces.append(trace)

    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    service = FakeImageService(tmp_path, [first, second])
    quality = FakeSemanticQualityService([False, True])
    slide = _cutout_slide(
        with_semantic_contract=True,
        description=None,
    )

    generated, plan = asyncio.run(
        asset_execution_service.process_presentation_assets(
            service,
            [slide],
            semantic_quality_service=quality,
        )
    )

    assert service.calls == 2
    assert len(quality.calls) == 2
    assert quality.calls[0]["expectations"][0].semantic_label == "red toy"
    assert quality.calls[0]["expectations"][0].description is None
    assert [trace.status for trace in traces] == ["failed", "succeeded"]
    assert traces[0].error["type"] == "AssetSemanticQualityError"
    assert traces[0].error["semantic_quality"]["passed"] is False
    assert traces[1].retry_of == plan[0].request_id
    assert len(generated) == 2  # accepted source plus derived transparent cutout
    assert "image_url" in slide.content["main"]["subject"]


def test_later_semantic_failure_does_not_regenerate_prior_success(tmp_path, monkeypatch):
    first_ok = tmp_path / "apple-ok.png"
    second_bad = tmp_path / "rabbit-bad.png"
    second_ok = tmp_path / "rabbit-ok.png"
    for path in (first_ok, second_bad, second_ok):
        _valid_cutout_source(path)

    traces = []

    async def record(trace):
        traces.append(trace)

    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    service = FakeImageService(tmp_path, [first_ok, second_bad, second_ok])
    # First asset passes; the second asset fails once then passes its retry.
    quality = FakeSemanticQualityService([True, False, True])
    slides = [
        _cutout_slide(
            index=0,
            prompt="A red apple",
            semantic_label="red apple",
            with_semantic_contract=True,
        ),
        _cutout_slide(
            index=1,
            prompt="A white rabbit",
            semantic_label="white rabbit",
            with_semantic_contract=True,
        ),
    ]

    _generated, plan = asyncio.run(
        asset_execution_service.process_presentation_assets(
            service,
            slides,
            semantic_quality_service=quality,
        )
    )

    assert len(plan) == 2
    assert service.calls == 3
    assert service.prompts[0].count("A red apple") == 1
    assert sum("A red apple" in prompt for prompt in service.prompts) == 1
    assert sum("A white rabbit" in prompt for prompt in service.prompts) == 2
    assert [trace.status for trace in traces] == ["succeeded", "failed", "succeeded"]
    assert traces[2].retry_of == plan[1].request_id
    assert "image_url" in slides[0].content["main"]["subject"]
    assert "image_url" in slides[1].content["main"]["subject"]


def test_completed_asset_is_exposed_to_checkpoint_before_return(tmp_path, monkeypatch):
    source = tmp_path / "source.png"
    _valid_cutout_source(source)

    async def record(_trace):
        return None

    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    monkeypatch.setattr(
        asset_execution_service,
        "build_default_asset_semantic_quality_service",
        lambda: None,
    )
    service = FakeImageService(tmp_path, [source])
    slide = _cutout_slide()
    checkpoints = []

    async def checkpoint(assets):
        checkpoints.append(
            {
                "paths": [asset.path for asset in assets],
                "url": slide.content["main"]["subject"].get("image_url"),
            }
        )

    asyncio.run(
        asset_execution_service.process_presentation_assets(
            service,
            [slide],
            on_item_completed=checkpoint,
        )
    )

    assert len(checkpoints) == 1
    assert len(checkpoints[0]["paths"]) == 2
    assert checkpoints[0]["url"]
