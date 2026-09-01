from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import os

from models.image_prompt import ImagePrompt
from models.sql.image_asset import ImageAsset
from models.sql.asset_generation_trace import AssetGenerationTrace
from models.sql.slide import SlideModel
from services.asset_planning_service import (
    AssetPlanItem,
    AssetSemanticExpectation,
    AssetSlotRequest,
    build_asset_plan,
)
from services.asset_semantic_quality_service import (
    AssetSemanticQualityError,
    AssetSemanticQualityService,
    build_default_asset_semantic_quality_service,
)
from services.image_generation_service import ImageGenerationService
from services.sprite_sheet_service import (
    create_transparent_cutout,
    crop_sprite_sheet,
    crop_to_aspect_ratio,
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


def _request_prompt(item: AssetPlanItem) -> str:
    if item.generation_mode == "sprite-sheet":
        cells = "; ".join(
            f"cell {index + 1}: {slot.prompt}"
            for index, slot in enumerate(item.slots)
        )
        return (
            f"Create a clean {item.grid_columns} by {item.grid_rows} sprite sheet. "
            f"{cells}. One complete centered subject per cell, consistent style and "
            "scale, large empty margin, solid plain background, no grid lines."
        )
    if item.generation_mode == "composite-image":
        subjects = "; ".join(slot.prompt for slot in item.slots)
        return f"Create one coherent scene containing: {subjects}."

    slot = item.slots[0]
    if item.generation_mode == "direct-background":
        safe_area = (
            f" Keep a quiet text-safe area on the {slot.text_safe_area}."
            if slot.text_safe_area != "none"
            else ""
        )
        return (
            f"{slot.prompt}. Full-bleed presentation background, aspect ratio "
            f"{slot.aspect_ratio}, no border.{safe_area}"
        )
    if item.generation_mode == "single-cutout":
        return (
            f"{slot.prompt}. One complete centered subject, generous margin, solid "
            "plain contrasting background suitable for local background removal."
        )
    return slot.prompt


def _asset_url(result: str | ImageAsset) -> str:
    if isinstance(result, ImageAsset):
        return filesystem_image_path_to_app_data_url(result.path)
    return normalize_slide_asset_url(result)


def _assign_url(slide: SlideModel, slot: AssetSlotRequest, url: str) -> None:
    target = get_dict_at_path(slide.content, slot.content_path)
    _set_asset_url(
        target,
        "image",
        url,
        template=_uses_template_asset_fields(slide),
    )
    set_dict_at_path(slide.content, slot.content_path, target)


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
            if not expectations:
                continue
            quality = await quality_service.validate(output, expectations)
            if not quality.passed:
                raise AssetSemanticQualityError(quality)
        return

    if item.generation_mode == "single-cutout":
        if not derived_outputs:
            raise ValueError("Cutout processing produced no consumer image")
        expectations = _quality_expectations((item.slots[0],))
        if not expectations:
            return
        quality = await quality_service.validate(derived_outputs[0], expectations)
        if not quality.passed:
            raise AssetSemanticQualityError(quality)
        return

    expectations = _quality_expectations(item.slots)
    if not expectations:
        return
    quality = await quality_service.validate(result, expectations)
    if not quality.passed:
        raise AssetSemanticQualityError(quality)


def _trace_error_payload(exc: Exception) -> dict:
    payload: dict = {
        "type": type(exc).__name__,
        "message": str(exc)[:500],
    }
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
) -> tuple[list[ImageAsset], list[AssetPlanItem]]:
    """Generate independent asset-plan items concurrently with bounded cost.

    A semantic mismatch gets one scoped retry. A visual-QA outage does not discard
    an image that the provider already generated successfully, because leaving a
    permanent blank frame is worse than surfacing a trace warning for later review.
    """
    plan = build_asset_plan(slides)
    slides_by_index = {slide.index: slide for slide in slides}
    quality_service = (
        semantic_quality_service or build_default_asset_semantic_quality_service()
    )
    try:
        concurrency = max(
            1,
            min(6, int(os.getenv("ASSET_GENERATION_CONCURRENCY", "3"))),
        )
    except ValueError:
        concurrency = 3
    semaphore = asyncio.Semaphore(concurrency)
    checkpoint_lock = asyncio.Lock()

    async def process_item(item: AssetPlanItem) -> list[ImageAsset]:
        async with semaphore:
            last_error: Exception | None = None
            result: str | ImageAsset | None = None
            source_asset: ImageAsset | None = None
            derived_outputs: list[str] = []
            quality_warning: Exception | None = None

            for attempt in range(2):
                trace_id = (
                    item.request_id
                    if attempt == 0
                    else f"{item.request_id}_retry1"
                )
                materialized_source_to_cleanup: str | None = None
                quality_warning = None
                try:
                    result = await image_generation_service.generate_image(
                        ImagePrompt(prompt=_request_prompt(item))
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
                    elif isinstance(result, ImageAsset) and item.slots:
                        local_source, materialized = await _materialize_transform_source(
                            result,
                            image_generation_service.output_directory,
                            trace_id,
                        )
                        if materialized:
                            materialized_source_to_cleanup = local_source
                        normalized_path = crop_to_aspect_ratio(
                            local_source,
                            image_generation_service.output_directory,
                            item.slots[0].aspect_ratio,
                        )
                        if normalized_path != local_source:
                            result = ImageAsset(
                                path=normalized_path,
                                is_uploaded=False,
                                extras={
                                    "source_asset_request_id": item.request_id,
                                    "generation_mode": item.generation_mode,
                                    "aspect_ratio": item.slots[0].aspect_ratio,
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
                        if attempt == 0:
                            raise
                        quality_warning = exc
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
                    if not isinstance(exc, AssetSemanticQualityError):
                        break
                finally:
                    _remove_materialized_source(materialized_source_to_cleanup)

            if result is None:
                assert last_error is not None
                raise last_error

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

    item_results = await asyncio.gather(*(process_item(item) for item in plan))
    return [asset for assets in item_results for asset in assets], plan
