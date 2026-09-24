import asyncio

from PIL import Image, ImageDraw
import pytest

from models.sql.image_asset import ImageAsset
from models.sql.slide import SlideModel
from services import asset_execution_service
from services.asset_semantic_quality_service import (
    AssetSemanticCheck,
    AssetSemanticQualityResult,
    _enforce_expectations,
)


@pytest.fixture(autouse=True)
def _local_asset_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSET_SEMANTIC_QA_ENABLED", "true")
    monkeypatch.setenv("APP_DATA_DIRECTORY", str(tmp_path / "app-data"))
    monkeypatch.setenv("ALIYUN_OSS_ENABLED", "false")


class FakeImageService:
    def __init__(self, output_directory, outputs):
        self.output_directory = str(output_directory)
        self.outputs = list(outputs)
        self.calls = 0
        self.prompts = []
        self.aspect_ratios = []

    async def generate_image(self, prompt):
        self.prompts.append(prompt.prompt)
        self.aspect_ratios.append(prompt.aspect_ratio)
        output = self.outputs[self.calls]
        self.calls += 1
        return ImageAsset(path=str(output), is_uploaded=False)

    def configured_model_name(self):
        return "fake-image-model"


def test_moderation_rejection_is_not_retried_through_an_unchecked_fallback(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from unittest.mock import AsyncMock
    class RejectedService(FakeImageService):
        async def generate_image(self, prompt):
            self.calls += 1
            raise HTTPException(400, 'moderation rejected the image request')
    monkeypatch.setattr(asset_execution_service, 'record_asset_generation_trace', AsyncMock())
    service = RejectedService(tmp_path, [])
    slide = _cutout_slide(with_semantic_contract=True)
    image = slide.ui['components'][0]['elements'][0]
    image.update(asset_mode='composite-image', asset_role='framed-image')
    quality = FakeSemanticQualityService([True])
    asyncio.run(asset_execution_service.process_presentation_assets(
        service, [slide], semantic_quality_service=quality))
    assert service.calls == 1
    assert quality.calls == []
    assert not slide.content['main']['subject'].get('image_url')
    assert 'moderation' in slide.content['main']['subject']['__repair_failed_reason__']


def test_teaching_image_without_quality_configuration_does_not_spend_a_generation(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr(asset_execution_service, 'record_asset_generation_trace', AsyncMock())
    monkeypatch.setattr(asset_execution_service, 'build_default_asset_semantic_quality_service', lambda: None)
    slide = _cutout_slide(with_semantic_contract=True)
    service = FakeImageService(tmp_path, [])
    asyncio.run(asset_execution_service.process_presentation_assets(service, [slide]))
    assert service.calls == 0
    assert not slide.content['main']['subject'].get('image_url')
    assert '质检服务未配置' in slide.content['main']['subject']['__repair_failed_reason__']


def test_sprite_sheet_requests_the_whole_grid_ratio_instead_of_one_cell():
    from dataclasses import replace
    from services.asset_planning_service import AssetPlanItem
    slot = asset_execution_service.build_asset_plan([_cutout_slide()])[0].slots[0]
    slot = replace(slot, width=300, height=400)
    item = AssetPlanItem(request_id='grid', generation_mode='sprite-sheet',
                         slots=(slot, slot), grid_columns=2, grid_rows=1)
    prompt = asset_execution_service._build_image_prompt(item, prompt_text='two complete subjects', forbid_latin_text=True)
    assert prompt.aspect_ratio == '3:2'  # Two portrait cells need a landscape sheet.


def test_visual_quality_rejects_visible_text_and_cropped_subject_without_contracts():
    result = _enforce_expectations(
        AssetSemanticQualityResult(
            passed=True,
            visible_text_detected=True,
            detected_text="Consensus Path",
            subject_cropped=True,
        ),
        (),
        0.70,
    )

    assert result.passed is False
    assert "可见文字" in result.overall_reason
    assert "主体被边缘截断" in result.overall_reason


def test_teacher_art_direction_survives_execution_and_is_not_reused_for_children():
    child = _cutout_slide(index=0, with_semantic_contract=True)
    teacher = _cutout_slide(index=1, with_semantic_contract=True)
    teacher.content["__content_contract__"]["visual_audience"] = "teacher"
    plan = asset_execution_service.build_asset_plan([child, teacher])
    assert len(plan) == 2
    prompts = {item.slots[0].visual_audience: asset_execution_service._request_prompt(item) for item in plan}
    assert "中国幼儿园教研插画" in prompts["teacher"]
    assert "禁止英文" in prompts["teacher"]
    assert "professional educational editorial" not in prompts["teacher"]
    assert "ages 3-6" not in prompts["teacher"]
    assert "ages 3-6" in prompts["child"]
    assert "完整入画" in prompts["teacher"]
    assert "do not crop heads" in prompts["child"]


def test_education_image_without_semantic_slots_still_runs_text_and_crop_qa():
    slide = _cutout_slide(with_semantic_contract=False)
    slide.content["__content_contract__"] = {
        "classroom_mapping_version": 1,
        "visual_audience": "teacher",
    }
    item = asset_execution_service.build_asset_plan([slide])[0]

    assert item.slots[0].education_visual is True


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


@pytest.mark.parametrize("require_quality", [False, True])
def test_qa_disabled_twelve_image_requests_make_twelve_calls(tmp_path, monkeypatch, require_quality):
    # Covers initial generation and repair's require_semantic_quality=True.
    monkeypatch.delenv("ASSET_SEMANTIC_QA_ENABLED")
    monkeypatch.setenv("ASSET_SEMANTIC_QA_PROVIDER", "dmx")
    from unittest.mock import Mock
    builder = Mock(side_effect=AssertionError("Disabled QA must not create a client"))
    monkeypatch.setattr(asset_execution_service, "build_default_asset_semantic_quality_service", builder)
    source = tmp_path / "scene.png"
    Image.new("RGB", (600, 600), "green").save(source)
    traces = []
    async def record(trace):
        traces.append(trace)
    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    slides = [_cutout_slide(index=i, prompt=f"Independent scene {i}",
                           semantic_label=f"Scene {i}", with_semantic_contract=True) for i in range(12)]
    for slide in slides:
        slide.ui['components'][0]['elements'][0].update(asset_role='framed-image', asset_mode='composite-image')
    provider = FakeImageService(tmp_path, [source] * 12)
    rejecting_quality = FakeSemanticQualityService([False] * 24)
    _, plan = asyncio.run(asset_execution_service.process_presentation_assets(
        provider, slides, semantic_quality_service=rejecting_quality,
        require_semantic_quality=require_quality))
    assert len(plan) == provider.calls == len(traces) == 12
    assert rejecting_quality.calls == []
    builder.assert_not_called()
    assert all(trace.status == 'succeeded' and not trace.retry_of for trace in traces)
    assert all(slide.content['main']['subject'].get('image_url') for slide in slides)


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
    assert "上次画面质检未通过" in service.prompts[1]
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
    first_traces = [trace for trace in traces if trace.request_id == plan[0].request_id]
    second_traces = [
        trace
        for trace in traces
        if trace.request_id == plan[1].request_id or trace.retry_of == plan[1].request_id
    ]
    assert [trace.status for trace in first_traces] == ["succeeded"]
    assert sorted(trace.status for trace in second_traces) == ["failed", "succeeded"]
    assert any(trace.retry_of == plan[1].request_id for trace in second_traces)
    assert "image_url" in slides[0].content["main"]["subject"]
    assert "image_url" in slides[1].content["main"]["subject"]


def test_oss_source_is_materialized_then_final_cutout_is_persisted(tmp_path, monkeypatch):
    source_url = "https://example-oss.aliyuncs.com/images/source.png"
    persisted_urls = []

    async def record(_trace):
        return None

    async def materialize(_url, dest):
        assert _url == source_url
        _valid_cutout_source(dest)
        return dest

    async def persist(path):
        assert path.endswith(".png")
        persisted = "https://example-oss.aliyuncs.com/images/final-cutout.png"
        persisted_urls.append(persisted)
        return persisted

    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    monkeypatch.setattr(asset_execution_service, "materialize_url_to_file", materialize)
    monkeypatch.setattr(asset_execution_service, "persist_generated_image", persist)

    service = FakeImageService(tmp_path, [source_url])
    quality = FakeSemanticQualityService([True])
    slide = _cutout_slide(with_semantic_contract=True)

    generated, _plan = asyncio.run(
        asset_execution_service.process_presentation_assets(
            service,
            [slide],
            semantic_quality_service=quality,
        )
    )

    assert service.calls == 1
    assert len(quality.calls) == 1
    assert quality.calls[0]["image"].endswith(".png")
    assert persisted_urls == [
        "https://example-oss.aliyuncs.com/images/final-cutout.png"
    ]
    assert generated[0].path == source_url
    assert generated[-1].path == persisted_urls[0]
    assert slide.content["main"]["subject"]["image_url"] == persisted_urls[0]


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


def test_independent_assets_use_bounded_concurrency(tmp_path, monkeypatch):
    outputs = [tmp_path / "first.png", tmp_path / "second.png"]
    for output in outputs:
        _valid_cutout_source(output)

    async def record(_trace):
        return None

    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    monkeypatch.setattr(
        asset_execution_service,
        "build_default_asset_semantic_quality_service",
        lambda: None,
    )
    monkeypatch.setenv("ASSET_GENERATION_CONCURRENCY", "2")

    class SlowImageService(FakeImageService):
        def __init__(self, output_directory, values):
            super().__init__(output_directory, values)
            self.active = 0
            self.max_active = 0

        async def generate_image(self, prompt):
            index = self.calls
            self.calls += 1
            self.prompts.append(prompt.prompt)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.02)
            self.active -= 1
            return ImageAsset(path=str(self.outputs[index]), is_uploaded=False)

    service = SlowImageService(tmp_path, outputs)
    slides = [
        _cutout_slide(index=0, prompt="A red apple"),
        _cutout_slide(index=1, prompt="A white rabbit"),
    ]
    asyncio.run(asset_execution_service.process_presentation_assets(service, slides))

    assert service.max_active == 2
    assert all("image_url" in slide.content["main"]["subject"] for slide in slides)


def test_visual_qa_timeout_keeps_the_generated_teaching_image(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source.png"
    _valid_cutout_source(source)
    traces = []

    async def record(trace):
        traces.append(trace)

    class TimedOutQualityService:
        async def validate(self, _image, _expectations):
            raise TimeoutError("vision check timed out")

    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    service = FakeImageService(tmp_path, [source])
    slide = _cutout_slide(with_semantic_contract=True)

    asyncio.run(
        asset_execution_service.process_presentation_assets(
            service,
            [slide],
            semantic_quality_service=TimedOutQualityService(),
        )
    )

    assert service.calls == 1
    assert slide.content["main"]["subject"].get("image_url")
    assert traces[-1].status == "succeeded_with_warning"
    assert traces[-1].error["visual_qa_warning"]["type"] == "TimeoutError"


def test_second_known_quality_failure_stays_missing_instead_of_using_bad_image(
    tmp_path,
    monkeypatch,
):
    first = tmp_path / "text-in-image.png"
    second = tmp_path / "cropped-subject.png"
    _valid_cutout_source(first)
    _valid_cutout_source(second)
    traces = []

    async def record(trace):
        traces.append(trace)

    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    service = FakeImageService(tmp_path, [first, second])
    quality = FakeSemanticQualityService([False, False])
    slide = _cutout_slide(with_semantic_contract=True)

    generated, _plan = asyncio.run(
        asset_execution_service.process_presentation_assets(
            service,
            [slide],
            semantic_quality_service=quality,
        )
    )

    assert service.calls == 2
    assert generated == []
    assert "image_url" not in slide.content["main"]["subject"]
    assert [trace.status for trace in traces] == ["failed", "failed"]


def test_education_visual_rejects_detected_text_even_without_semantic_contract(
    tmp_path,
    monkeypatch,
):
    outputs = [tmp_path / "english-1.png", tmp_path / "english-2.png"]
    for output in outputs:
        _valid_cutout_source(output)

    class TextDetectingQualityService:
        calls = 0

        async def validate(self, _image, expectations):
            assert expectations == ()
            self.calls += 1
            return AssetSemanticQualityResult(
                passed=False,
                visible_text_detected=True,
                detected_text="Consensus Path",
                overall_reason="图片含英文",
            )

    async def record(_trace):
        return None

    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    service = FakeImageService(tmp_path, outputs)
    quality = TextDetectingQualityService()
    slide = _cutout_slide(with_semantic_contract=False)
    slide.content["__content_contract__"] = {
        "classroom_mapping_version": 1,
        "visual_audience": "teacher",
    }

    generated, _plan = asyncio.run(
        asset_execution_service.process_presentation_assets(
            service, [slide], semantic_quality_service=quality
        )
    )

    assert quality.calls == 2
    assert generated == []
    assert "image_url" not in slide.content["main"]["subject"]


def test_contain_image_is_not_destructively_center_cropped(tmp_path, monkeypatch):
    source = tmp_path / "wide-complete-scene.png"
    Image.new("RGB", (1200, 500), "white").save(source)

    async def record(_trace):
        return None

    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    slide = SlideModel(
        presentation="00000000-0000-0000-0000-000000000001",
        layout_group="teacher-training",
        layout="scene",
        index=0,
        content={"main": {"visual": {"image_prompt": "完整教研沟通场景"}}},
        ui={"components": [{"id": "main", "elements": [{
            "type": "image", "name": "visual", "fit": "contain",
            "asset_role": "framed-image", "position": {"x": 0, "y": 0},
            "size": {"width": 320, "height": 480},
        }]}]},
    )
    service = FakeImageService(tmp_path, [source])

    generated, _plan = asyncio.run(
        asset_execution_service.process_presentation_assets(
            service, [slide], semantic_quality_service=None
        )
    )

    assert [asset.path for asset in generated] == [str(source)]
    assert slide.content["main"]["visual"]["image_url"]


def test_kindergarten_asset_prompt_requires_one_illustration_medium():
    slide = _cutout_slide(with_semantic_contract=True)
    item = asset_execution_service.build_asset_plan([slide])[0]
    prompt = asset_execution_service._request_prompt(item)
    assert "consistent 2D children's picture-book illustration style" in prompt
    assert "never photography" in prompt
    assert "photorealism" in prompt
    assert "mixed media" in prompt
    assert "do not crop heads" in prompt


def test_teacher_wide_banner_prompt_uses_real_frame_and_full_bodies():
    slide = SlideModel(
        presentation="00000000-0000-0000-0000-000000000001",
        layout_group="teacher-training",
        layout="scene_top",
        index=0,
        content={
            "main": {"visual": {"image_prompt": "教师围坐研讨观察记录"}},
            "__content_contract__": {
                "visual_audience": "teacher",
                "classroom_mapping_version": 1,
            },
        },
        ui={
            "components": [
                {
                    "id": "main",
                    "elements": [
                        {
                            "type": "image",
                            "name": "visual",
                            "fit": "cover",
                            "asset_role": "framed-image",
                            "position": {"x": 48, "y": 174},
                            "size": {"width": 1184, "height": 220},
                        }
                    ],
                }
            ]
        },
    )
    item = asset_execution_service.build_asset_plan([slide])[0]
    prompt = asset_execution_service._request_prompt(item)
    assert "1184:220" in prompt
    assert "完整入画" in prompt
    assert "半截身子" in prompt
    assert "横向宽画幅" in prompt
    assert asset_execution_service._provider_aspect_ratio(item.slots[0]) == "21:9"


def test_cover_framed_image_is_padded_instead_of_center_cropped(tmp_path, monkeypatch):
    source = Image.new("RGB", (100, 100), "white")
    source.putpixel((50, 2), (255, 0, 0))
    source.putpixel((50, 97), (0, 0, 255))
    path = tmp_path / "square.png"
    source.save(path)

    async def record(_trace):
        return None

    monkeypatch.setattr(asset_execution_service, "record_asset_generation_trace", record)
    slide = SlideModel(
        presentation="00000000-0000-0000-0000-000000000001",
        layout_group="teacher-training",
        layout="scene_top",
        index=0,
        content={
            "main": {"visual": {"image_prompt": "教师围坐研讨观察记录"}},
            "__content_contract__": {
                "visual_audience": "teacher",
                "classroom_mapping_version": 1,
            },
        },
        ui={
            "components": [
                {
                    "id": "main",
                    "elements": [
                        {
                            "type": "image",
                            "name": "visual",
                            "fit": "cover",
                            "asset_role": "framed-image",
                            "position": {"x": 48, "y": 174},
                            "size": {"width": 1184, "height": 220},
                        }
                    ],
                }
            ]
        },
    )
    service = FakeImageService(tmp_path, [path])
    quality = FakeSemanticQualityService([True])
    generated, _plan = asyncio.run(
        asset_execution_service.process_presentation_assets(
            service, [slide], semantic_quality_service=quality
        )
    )

    fitted = Image.open(generated[-1].path)
    assert quality.calls[0]['image'] == str(path)  # Inspect original edges before padding.
    pixels = set(fitted.getdata())
    assert abs(fitted.width / fitted.height - 1184 / 220) < 0.02
    assert (255, 0, 0, 255) in pixels
    assert (0, 0, 255, 255) in pixels
    assert service.aspect_ratios == ["21:9"]
    assert "完整入画" in service.prompts[0]
