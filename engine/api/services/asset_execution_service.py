from __future__ import annotations

from collections.abc import Awaitable, Callable

from models.image_prompt import ImagePrompt
from models.sql.image_asset import ImageAsset
from models.sql.asset_generation_trace import AssetGenerationTrace
from models.sql.slide import SlideModel
from services.asset_planning_service import AssetPlanItem, AssetSlotRequest, build_asset_plan
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
from utils.asset_directory_utils import filesystem_image_path_to_app_data_url, normalize_slide_asset_url
from utils.dict_utils import get_dict_at_path, set_dict_at_path
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


async def process_presentation_assets(
    image_generation_service: ImageGenerationService,
    slides: list[SlideModel],
    presentation_id=None,
    on_item_completed: Callable[[list[ImageAsset]], Awaitable[None]] | None = None,
) -> tuple[list[ImageAsset], list[AssetPlanItem]]:
    plan = build_asset_plan(slides)
    slides_by_index = {slide.index: slide for slide in slides}
    generated_assets: list[ImageAsset] = []

    for item in plan:
        item_asset_start = len(generated_assets)
        last_error: Exception | None = None
        result: str | ImageAsset | None = None
        source_asset: ImageAsset | None = None
        derived_outputs: list[str] = []
        # A paid retry is scoped to the failed asset request. Successful assets
        # and slide content are never regenerated.
        for attempt in range(2):
            trace_id = item.request_id if attempt == 0 else f"{item.request_id}_retry1"
            try:
                result = await image_generation_service.generate_image(
                    ImagePrompt(prompt=_request_prompt(item))
                )
                source_asset = result if isinstance(result, ImageAsset) else None
                if item.generation_mode == "sprite-sheet":
                    if not isinstance(result, ImageAsset):
                        raise ValueError(
                            "Sprite sheet processing requires a local generated image"
                        )
                    derived_outputs = crop_sprite_sheet(
                        result.path,
                        image_generation_service.output_directory,
                        item.grid_columns or 0,
                        item.grid_rows or 0,
                        len(item.slots),
                    )
                elif item.generation_mode == "single-cutout":
                    if not isinstance(result, ImageAsset):
                        raise ValueError(
                            "Cutout processing requires a local generated image"
                        )
                    derived_outputs = [
                        create_transparent_cutout(
                            result.path, image_generation_service.output_directory
                        )
                    ]
                elif isinstance(result, ImageAsset) and item.slots:
                    normalized_path = crop_to_aspect_ratio(
                        result.path,
                        image_generation_service.output_directory,
                        item.slots[0].aspect_ratio,
                    )
                    if normalized_path != result.path:
                        result = ImageAsset(
                            path=normalized_path,
                            is_uploaded=False,
                            extras={
                                "source_asset_request_id": item.request_id,
                                "generation_mode": item.generation_mode,
                                "aspect_ratio": item.slots[0].aspect_ratio,
                            },
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
                        status="succeeded",
                        # Provider responses currently expose no authoritative cost.
                        # Null is deliberate; recording zero would under-report spend.
                        cost=None,
                    )
                )
                break
            except Exception as exc:  # noqa: BLE001 - provider errors are normalized upstream
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
                        error={"type": type(exc).__name__, "message": str(exc)[:500]},
                    )
                )
        if result is None:
            assert last_error is not None
            raise last_error
        if source_asset is not None:
            generated_assets.append(source_asset)
        if isinstance(result, ImageAsset) and result.path != getattr(source_asset, "path", None):
            generated_assets.append(result)

        if item.generation_mode == "sprite-sheet":
            for slot, output in zip(item.slots, derived_outputs):
                cutout_asset = ImageAsset(
                    path=output,
                    is_uploaded=False,
                    extras={
                        "source_asset_request_id": item.request_id,
                        "generation_mode": item.generation_mode,
                    },
                )
                generated_assets.append(cutout_asset)
                _assign_url(
                    slides_by_index[slot.slide_index],
                    slot,
                    filesystem_image_path_to_app_data_url(output),
                )
            if on_item_completed is not None:
                await on_item_completed(generated_assets[item_asset_start:])
            continue

        if item.generation_mode == "single-cutout":
            output = derived_outputs[0]
            cutout_asset = ImageAsset(
                path=output,
                is_uploaded=False,
                extras={
                    "source_asset_request_id": item.request_id,
                    "generation_mode": item.generation_mode,
                },
            )
            generated_assets.append(cutout_asset)
            _assign_url(
                slides_by_index[item.slots[0].slide_index],
                item.slots[0],
                filesystem_image_path_to_app_data_url(output),
            )
            if on_item_completed is not None:
                await on_item_completed(generated_assets[item_asset_start:])
            continue

        url = _asset_url(result)
        for slot in item.slots:
            _assign_url(slides_by_index[slot.slide_index], slot, url)
        if on_item_completed is not None:
            await on_item_completed(generated_assets[item_asset_start:])

    return generated_assets, plan
