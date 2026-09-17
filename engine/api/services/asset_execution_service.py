from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
import os

from models.image_prompt import ImageAspectRatio, ImagePrompt
from models.sql.image_asset import ImageAsset
from models.sql.asset_generation_trace import AssetGenerationTrace
from models.sql.slide import SlideModel
from services.asset_planning_service import (
    AssetPlanItem,
    AssetSemanticExpectation,
    AssetSlotRequest,
    REPAIR_FAILED_PROMPT_KEY,
    REPAIR_FAILED_REASON_KEY,
    build_asset_plan,
)
from services.asset_semantic_quality_service import (
    AssetSemanticQualityError,
    AssetSemanticQualityService,
    build_default_asset_semantic_quality_service,
)
from services.image_generation_service import ImageGenerationService
from services.research_ppt_generation_context import research_ppt_image_options
from services.sprite_sheet_service import (
    create_transparent_cutout,
    crop_sprite_sheet,
    fit_to_aspect_ratio,
)
from services.asset_trace_service import record_asset_generation_trace
# Kept as a module export for compatibility with existing validation tests and
# optional callers. The interactive generation path no longer blocks on OCR.
from services.image_quality_service import materialize_and_validate_no_text
from utils.asset_directory_utils import (
    filesystem_image_path_to_app_data_url,
    normalize_slide_asset_url,
)
from utils.dict_utils import get_dict_at_path, set_dict_at_path
from utils.oss_storage import materialize_url_to_file, persist_generated_image
from utils.process_slides import _set_asset_url, _uses_template_asset_fields


LOGGER = logging.getLogger(__name__)


def _is_teacher_visual(item: AssetPlanItem) -> bool:
    return bool(item.slots) and all(slot.visual_audience == "teacher" for slot in item.slots)


def _kindergarten_visual_direction(item: AssetPlanItem) -> str:
    if item.slots and all(slot.classroom_role == "cover-scene" for slot in item.slots):
        # Cover typography is native even for English lessons. Do not override
        # the chosen template palette with the generic classroom/research style.
        return " 保持上述模板配色与无字构图；禁止任何语言的文字、伪文字、标签和水印。"
    if _is_teacher_visual(item):
        from services.research_ppt_generation_context import research_ppt_image_options

        no_latin = (
            "禁止英文、拉丁字母、数字标签和水印；"
            if research_ppt_image_options.get().forbid_latin_text
            else "本课为英语教学，图内文字可以使用英文。"
        )
        return (
            " 画成专业清晰的中国幼儿园教研插画：浅米白、松石绿、雾蓝；"
            "真实教研现场里的教师观察、研讨与介入；"
            "用具体人物动作和场景表达概念，不要画信息图、思维导图、循环图或对照表上的文字标签；"
            f"{no_latin}不要儿童童话拟人、商务海报、3D、摄影或黑色抽象纹理。"
        )
    if not any(slot.semantic_expectations for slot in item.slots):
        return ""
    return (
        " Use one consistent 2D children's picture-book illustration style across the "
        "whole deck: preserve the selected template medium and palette, while keeping "
        "the subject's natural colors. Make it bright and imaginative for ages 3-6, "
        "with clearly recognizable teaching subjects. Include people only when the "
        "asset requests them. Never merge human bodies with animal parts; classroom "
        "imitation means normal children making gestures, not physical transformation. "
        "This must be an illustration, never photography, "
        "photorealism, a camera image, 3D render, corporate stock art or mixed media. "
        "Keep factual features accurate. Avoid black abstract textures, horror, dense "
        "background clutter, text, letters, numbers, logos, watermarks or pseudo-text."
    )


def _slot_frame_ratio(slot: AssetSlotRequest) -> str:
    if slot.width > 0 and slot.height > 0:
        return f"{int(slot.width)}:{int(slot.height)}"
    return slot.aspect_ratio or "16:9"


def _frame_value(slot: AssetSlotRequest) -> float:
    text = _slot_frame_ratio(slot)
    parts = text.split(":", 1)
    try:
        return float(parts[0]) / float(parts[1])
    except (ValueError, ZeroDivisionError, IndexError):
        return 1.0


_PROVIDER_RATIOS: tuple[tuple[int, int], ...] = (
    (21, 9),
    (16, 9),
    (4, 3),
    (3, 2),
    (1, 1),
    (3, 4),
    (2, 3),
    (9, 16),
)


def _provider_aspect_ratio(slot: AssetSlotRequest) -> ImageAspectRatio:
    value = _frame_value(slot)
    numerator, denominator = min(
        _PROVIDER_RATIOS,
        key=lambda pair: abs(value - pair[0] / pair[1]),
    )
    return f"{numerator}:{denominator}"  # type: ignore[return-value]


def _build_image_prompt(
    item: AssetPlanItem,
    *,
    prompt_text: str,
    forbid_latin_text: bool,
) -> ImagePrompt:
    return ImagePrompt(
        prompt=prompt_text,
        forbid_latin_text=forbid_latin_text,
        aspect_ratio=_provider_aspect_ratio(item.slots[0]) if item.slots else None,
    )


def _framing_direction(slot: AssetSlotRequest) -> str:
    ratio = _frame_value(slot)
    frame = _slot_frame_ratio(slot)
    if slot.visual_audience == "teacher":
        direction = (
            f" 目标画面比例 {frame}。人物、教具和关键动作必须完整入画，"
            "头顶、手和躯干不要贴边或被截断；不要大头特写或只画半截身子。"
        )
        if ratio >= 2.2:
            return direction + " 使用横向宽画幅构图，人物并排或围坐，大半身可见。"
        if ratio >= 1.4:
            return direction + " 使用横向中景构图，人物站立或围坐完整可见。"
        return direction
    direction = (
        f" Compose for a {frame} frame. Keep the full teaching subject inside the "
        "image with margin; do not crop heads, hands, feet or key body parts."
    )
    if ratio >= 2.2:
        return direction + " Use a wide landscape arrangement so people stand side by side."
    return direction


def _request_prompt(item: AssetPlanItem) -> str:
    kindergarten_direction = _kindergarten_visual_direction(item)
    teacher = _is_teacher_visual(item)
    if item.generation_mode == "sprite-sheet":
        if teacher:
            cells = "；".join(
                f"第{index + 1}格：{slot.prompt}"
                for index, slot in enumerate(item.slots)
            )
            return (
                f"生成一张干净的{item.grid_columns}列{item.grid_rows}行分镜拼图。"
                f"{cells}。每格一个完整居中主体，风格统一，大留白，纯色背景，"
                f"不要网格线和任何文字。{kindergarten_direction}"
            )
        cells = "; ".join(
            f"cell {index + 1}: {slot.prompt}"
            for index, slot in enumerate(item.slots)
        )
        return (
            f"Create a clean {item.grid_columns} by {item.grid_rows} sprite sheet. "
            f"{cells}. One complete centered subject per cell, consistent style and "
            f"scale, large empty margin, solid plain background, no grid lines."
            f"{kindergarten_direction}"
        )
    if item.generation_mode == "composite-image":
        subjects = "；".join(slot.prompt for slot in item.slots) if teacher else "; ".join(
            slot.prompt for slot in item.slots
        )
        clue = (
            "明确要求局部猜谜时，按契约展示线索，不提前揭示答案。"
            if teacher
            else " When a local guessing cue is required, show the clue only and do not reveal the answer."
        )
        framing = _framing_direction(item.slots[0]) + clue
        if teacher:
            return f"生成一个连贯场景，画面中包含：{subjects}。{framing}{kindergarten_direction}"
        return (
            f"Create one coherent scene containing: {subjects}."
            f"{framing}{kindergarten_direction}"
        )

    slot = item.slots[0]
    framing = _framing_direction(slot)
    if item.generation_mode == "direct-background":
        if teacher:
            safe_area = (
                f" 在{slot.text_safe_area}侧保留安静的文字安全区。"
                if slot.text_safe_area != "none"
                else ""
            )
            return (
                f"{slot.prompt}。铺满16:9课件背景，人物若出现须完整入画。{safe_area}"
                f"{framing}{kindergarten_direction}"
            )
        safe_area = (
            f" Keep a quiet text-safe area on the {slot.text_safe_area}."
            if slot.text_safe_area != "none"
            else ""
        )
        return (
            f"{slot.prompt}. Full-bleed presentation background, aspect ratio "
            f"{slot.aspect_ratio}, no border.{safe_area}{framing}{kindergarten_direction}"
        )
    if item.generation_mode == "single-cutout":
        if teacher:
            return (
                f"{slot.prompt}。一个完整居中主体，四周留白，纯色对比背景，便于抠图。"
                f"{framing}{kindergarten_direction}"
            )
        return (
            f"{slot.prompt}. One complete centered subject, generous margin, solid "
            f"plain contrasting background suitable for local background removal."
            f"{framing}{kindergarten_direction}"
        )
    return f"{slot.prompt}{framing}{kindergarten_direction}"


def _asset_url(result: str | ImageAsset) -> str:
    if isinstance(result, ImageAsset):
        return filesystem_image_path_to_app_data_url(result.path)
    return normalize_slide_asset_url(result)


def _assign_url(slide: SlideModel, slot: AssetSlotRequest, url: str) -> None:
    target = get_dict_at_path(slide.content, slot.content_path)
    target.pop(REPAIR_FAILED_PROMPT_KEY, None)
    target.pop(REPAIR_FAILED_REASON_KEY, None)
    _set_asset_url(
        target,
        "image",
        url,
        template=_uses_template_asset_fields(slide),
    )
    set_dict_at_path(slide.content, slot.content_path, target)


def _mark_repair_failure(slide: SlideModel, slot: AssetSlotRequest, error: Exception) -> None:
    try:
        target = get_dict_at_path(slide.content, slot.content_path)
    except (KeyError, IndexError, TypeError, AttributeError):
        return
    if not isinstance(target, dict):
        return
    target[REPAIR_FAILED_PROMPT_KEY] = slot.prompt
    target[REPAIR_FAILED_REASON_KEY] = str(getattr(error, "detail", error) or error)[:180]
    set_dict_at_path(slide.content, slot.content_path, target)


def _is_moderation_error(error: Exception) -> bool:
    text = str(getattr(error, "detail", "") or error)
    folded = text.casefold()
    return "审核" in text or "moderation" in folded or "safety system" in folded


def _safer_kindergarten_prompt(prompt: str) -> str:
    return (
        f"{prompt}。适合3到6岁幼儿园的温馨绘本插画，画面干净明亮，"
        "人物和主体完整入画，不要文字、伤口、恐怖、写实皮肤特写或黑色抽象纹理。"
    )


def _quality_expectations(
    slots: tuple[AssetSlotRequest, ...],
) -> tuple[AssetSemanticExpectation, ...]:
    """Return unique QA-required contracts for images shared by several slots."""
    unique: dict[
        tuple[str, str, str, int, str], AssetSemanticExpectation
    ] = {}
    for slot in slots:
        for expectation in slot.semantic_expectations:
            if not expectation.qa_required:
                continue
            key = (
                expectation.planning_slot.strip().casefold(),
                expectation.semantic_label.strip().casefold(),
                (expectation.description or "").strip().casefold(),
                expectation.expected_count,
                expectation.role,
            )
            unique.setdefault(key, expectation)
    return tuple(unique.values())


async def _validate_semantic_quality(
    quality_service: AssetSemanticQualityService | None,
    item: AssetPlanItem,
    result: str | ImageAsset,
    derived_outputs: list[str],
) -> None:
    """Validate the final consumer image, not merely the provider source image."""
    if quality_service is None:
        return

    if item.generation_mode == "sprite-sheet":
        if len(derived_outputs) != len(item.slots):
            raise ValueError("Sprite sheet did not produce one image for every slot")
        for slot, output in zip(item.slots, derived_outputs):
            expectations = _quality_expectations((slot,))
            if not expectations and not slot.education_visual:
                continue
            quality = await quality_service.validate(output, expectations)
            if not quality.passed:
                raise AssetSemanticQualityError(quality)
        return

    if item.generation_mode == "single-cutout":
        if not derived_outputs:
            raise ValueError("Cutout processing produced no consumer image")
        expectations = _quality_expectations((item.slots[0],))
        if not expectations and not item.slots[0].education_visual:
            return
        quality = await quality_service.validate(derived_outputs[0], expectations)
        if not quality.passed:
            raise AssetSemanticQualityError(quality)
        return

    expectations = _quality_expectations(item.slots)
    if not expectations and not all(slot.education_visual for slot in item.slots):
        return
    quality = await quality_service.validate(result, expectations)
    if not quality.passed:
        raise AssetSemanticQualityError(quality)


def _trace_error_payload(exc: Exception) -> dict:
    payload: dict = {
        "type": type(exc).__name__,
        "message": str(exc)[:500],
    }
    if getattr(exc, "provider_code", None):
        payload["code"] = exc.provider_code
    if getattr(exc, "status_code", None):
        payload["status_code"] = exc.status_code
    if isinstance(exc, AssetSemanticQualityError):
        # Keep the structured failure in the existing trace table. This becomes
        # the per-asset quality report without introducing another persistence
        # write in the retry path.
        payload["semantic_quality"] = exc.result.model_dump(mode="json")
    return payload


async def _materialize_transform_source(
    asset: ImageAsset,
    output_directory: str,
    request_id: str,
) -> tuple[str, bool]:
    """Give PIL a local path even when generation already persisted to OSS."""
    if os.path.isfile(asset.path):
        return asset.path, False

    os.makedirs(output_directory, exist_ok=True)
    local_path = os.path.join(output_directory, f"{request_id}-source.png")
    await materialize_url_to_file(asset.path, local_path)
    return local_path, True


def _remove_materialized_source(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError:
        # Scratch cleanup must not turn a successfully accepted PPT image into a
        # generation failure. The server's normal temp cleanup can collect it.
        pass


async def _persist_derived_outputs(outputs: list[str]) -> list[str]:
    persisted: list[str] = []
    for output in outputs:
        persisted.append(await persist_generated_image(output))
    return persisted


async def process_presentation_assets(
    image_generation_service: ImageGenerationService,
    slides: list[SlideModel],
    presentation_id=None,
    on_item_completed: Callable[[list[ImageAsset]], Awaitable[None]] | None = None,
    semantic_quality_service: AssetSemanticQualityService | None = None,
    on_item_finished: Callable[[], Awaitable[None]] | None = None,
    quality_retries: int = 1,
    skip_semantic_quality: bool = False,
) -> tuple[list[ImageAsset], list[AssetPlanItem]]:
    """Generate independent asset-plan items concurrently with bounded cost.

    A semantic mismatch gets one scoped retry. A visual-QA outage does not discard
    an image that the provider already generated successfully. A provider failure
    for one optional visual also no longer destroys the entire deck: that slot keeps
    its placeholder, the failure stays in the asset trace, and the remaining slides
    and images continue to completion so the teacher can still edit the PPT.
    """
    plan = build_asset_plan(slides)
    slides_by_index = {slide.index: slide for slide in slides}
    quality_service = (
        None
        if skip_semantic_quality
        else (semantic_quality_service or build_default_asset_semantic_quality_service())
    )
    try:
        concurrency = max(
            1,
            min(6, int(os.getenv("ASSET_GENERATION_CONCURRENCY", "4"))),
        )
    except ValueError:
        concurrency = 4
    semaphore = asyncio.Semaphore(concurrency)
    checkpoint_lock = asyncio.Lock()
    image_options = research_ppt_image_options.get()
    max_attempts = 1 + max(0, int(quality_retries))

    async def process_item(item: AssetPlanItem) -> list[ImageAsset]:
        async with semaphore:
            last_error: Exception | None = None
            result: str | ImageAsset | None = None
            source_asset: ImageAsset | None = None
            derived_outputs: list[str] = []
            quality_warning: Exception | None = None

            for attempt in range(max_attempts):
                trace_id = (
                    item.request_id
                    if attempt == 0
                    else f"{item.request_id}_retry{attempt}"
                )
                materialized_source_to_cleanup: str | None = None
                quality_warning = None
                try:
                    result = await image_generation_service.generate_image(
                        _build_image_prompt(
                            item,
                            prompt_text=_request_prompt(item),
                            forbid_latin_text=(
                                image_options.forbid_latin_text
                                if image_options.enabled
                                else True
                            ),
                        )
                    )
                    source_asset = result if isinstance(result, ImageAsset) else None

                    if item.generation_mode == "sprite-sheet":
                        if not isinstance(result, ImageAsset):
                            raise ValueError(
                                "Sprite sheet processing requires a generated image asset"
                            )
                        local_source, materialized = await _materialize_transform_source(
                            result,
                            image_generation_service.output_directory,
                            trace_id,
                        )
                        if materialized:
                            materialized_source_to_cleanup = local_source
                        derived_outputs = crop_sprite_sheet(
                            local_source,
                            image_generation_service.output_directory,
                            item.grid_columns or 0,
                            item.grid_rows or 0,
                            len(item.slots),
                        )
                    elif item.generation_mode == "single-cutout":
                        if not isinstance(result, ImageAsset):
                            raise ValueError(
                                "Cutout processing requires a generated image asset"
                            )
                        local_source, materialized = await _materialize_transform_source(
                            result,
                            image_generation_service.output_directory,
                            trace_id,
                        )
                        if materialized:
                            materialized_source_to_cleanup = local_source
                        derived_outputs = [
                            create_transparent_cutout(
                                local_source,
                                image_generation_service.output_directory,
                            )
                        ]
                    elif (
                        isinstance(result, ImageAsset)
                        and item.slots
                        and (
                            item.slots[0].fit == "cover"
                            or item.slots[0].role == "background"
                        )
                    ):
                        local_source, materialized = await _materialize_transform_source(
                            result,
                            image_generation_service.output_directory,
                            trace_id,
                        )
                        if materialized:
                            materialized_source_to_cleanup = local_source
                        crop_fill = (
                            item.slots[0].role == "background"
                            or item.generation_mode == "direct-background"
                        )
                        normalized_path = fit_to_aspect_ratio(
                            local_source,
                            image_generation_service.output_directory,
                            _slot_frame_ratio(item.slots[0]),
                            crop=crop_fill,
                        )
                        if normalized_path != local_source:
                            result = ImageAsset(
                                path=normalized_path,
                                is_uploaded=False,
                                extras={
                                    "source_asset_request_id": item.request_id,
                                    "generation_mode": item.generation_mode,
                                    "aspect_ratio": _slot_frame_ratio(item.slots[0]),
                                },
                            )

                    try:
                        await _validate_semantic_quality(
                            quality_service,
                            item,
                            result,
                            derived_outputs,
                        )
                    except AssetSemanticQualityError as exc:
                        # A second bad result stays missing and can be repaired
                        # explicitly. Never place known text/cropped/wrong imagery
                        # into an otherwise usable deck.
                        raise
                    except Exception as exc:  # visual-QA timeout or provider outage
                        quality_warning = exc

                    if item.generation_mode in {"sprite-sheet", "single-cutout"}:
                        derived_outputs = await _persist_derived_outputs(derived_outputs)
                    elif (
                        isinstance(result, ImageAsset)
                        and source_asset is not None
                        and result.path != source_asset.path
                    ):
                        result = ImageAsset(
                            path=await persist_generated_image(result.path),
                            is_uploaded=False,
                            extras=result.extras,
                        )

                    await record_asset_generation_trace(
                        AssetGenerationTrace(
                            request_id=trace_id,
                            presentation_id=presentation_id,
                            generation_mode=item.generation_mode,
                            model=image_generation_service.configured_model_name(),
                            output_count=1,
                            consumer_slot_count=item.consumer_slot_count,
                            reused_consumer_slot_count=(
                                item.consumer_slot_count - 1
                                if item.generation_mode == "reuse-or-search"
                                else 0
                            ),
                            retry_of=item.request_id if attempt else None,
                            status=(
                                "succeeded_with_warning"
                                if quality_warning is not None
                                else "succeeded"
                            ),
                            cost=None,
                            error=(
                                {"visual_qa_warning": _trace_error_payload(quality_warning)}
                                if quality_warning is not None
                                else None
                            ),
                        )
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    result = None
                    source_asset = None
                    derived_outputs = []
                    await record_asset_generation_trace(
                        AssetGenerationTrace(
                            request_id=trace_id,
                            presentation_id=presentation_id,
                            generation_mode=item.generation_mode,
                            model=image_generation_service.configured_model_name(),
                            output_count=0,
                            consumer_slot_count=item.consumer_slot_count,
                            reused_consumer_slot_count=0,
                            retry_of=item.request_id if attempt else None,
                            status="failed",
                            cost=None,
                            error=_trace_error_payload(exc),
                        )
                    )
                    # A DMX timeout does not prove its remote job was cancelled.
                    # Repeating it immediately can duplicate work and charges.
                    if isinstance(exc, AssetSemanticQualityError) and attempt < max_attempts - 1:
                        continue
                    break
                finally:
                    _remove_materialized_source(materialized_source_to_cleanup)

            if (
                result is None
                and last_error is not None
                and _is_moderation_error(last_error)
                and item.generation_mode not in {"sprite-sheet", "single-cutout"}
            ):
                try:
                    result = await image_generation_service.generate_image(
                        _build_image_prompt(
                            item,
                            prompt_text=_safer_kindergarten_prompt(_request_prompt(item)),
                            forbid_latin_text=(
                                image_options.forbid_latin_text
                                if image_options.enabled
                                else True
                            ),
                        )
                    )
                    source_asset = result if isinstance(result, ImageAsset) else None
                    last_error = None
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    result = None

            if result is None:
                assert last_error is not None
                affected_pages = sorted({slot.slide_index + 1 for slot in item.slots})
                LOGGER.warning(
                    "Asset generation failed but deck generation will continue: "
                    "presentation_id=%s request_id=%s pages=%s error=%s",
                    presentation_id,
                    item.request_id,
                    affected_pages,
                    last_error,
                )
                for slot in item.slots:
                    slide = slides_by_index.get(slot.slide_index)
                    if slide is not None:
                        _mark_repair_failure(slide, slot, last_error)
                if on_item_completed is not None:
                    async with checkpoint_lock:
                        await on_item_completed([])
                return []

            item_assets: list[ImageAsset] = []
            if source_asset is not None:
                item_assets.append(source_asset)
            if (
                isinstance(result, ImageAsset)
                and result.path != getattr(source_asset, "path", None)
            ):
                item_assets.append(result)

            if item.generation_mode == "sprite-sheet":
                for slot, output in zip(item.slots, derived_outputs):
                    derived_asset = ImageAsset(
                        path=output,
                        is_uploaded=False,
                        extras={
                            "source_asset_request_id": item.request_id,
                            "generation_mode": item.generation_mode,
                        },
                    )
                    item_assets.append(derived_asset)
                    _assign_url(
                        slides_by_index[slot.slide_index],
                        slot,
                        filesystem_image_path_to_app_data_url(output),
                    )
            elif item.generation_mode == "single-cutout":
                output = derived_outputs[0]
                derived_asset = ImageAsset(
                    path=output,
                    is_uploaded=False,
                    extras={
                        "source_asset_request_id": item.request_id,
                        "generation_mode": item.generation_mode,
                    },
                )
                item_assets.append(derived_asset)
                _assign_url(
                    slides_by_index[item.slots[0].slide_index],
                    item.slots[0],
                    filesystem_image_path_to_app_data_url(output),
                )
            else:
                url = _asset_url(result)
                for slot in item.slots:
                    _assign_url(slides_by_index[slot.slide_index], slot, url)

            if on_item_completed is not None:
                async with checkpoint_lock:
                    await on_item_completed(item_assets)
            return item_assets

    async def tracked_item(item):
        result = await process_item(item)
        if on_item_finished is not None:
            async with checkpoint_lock:
                await on_item_finished()
        return result

    item_results = await asyncio.gather(*(tracked_item(item) for item in plan))
    return [asset for assets in item_results for asset in assets], plan
