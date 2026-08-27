from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Literal
import uuid

from models.json_path_guide import DictGuide, JsonPathGuide
from models.sql.slide import SlideModel
from utils.dict_utils import get_dict_at_path
from utils.process_slides import IMAGE_PROMPT_KEYS, _asset_dicts_with_prompt


AssetRole = Literal["background", "framed-image", "cutout"]
GenerationMode = Literal[
    "direct-background",
    "composite-image",
    "sprite-sheet",
    "single-cutout",
    "reuse-or-search",
]


class AssetSemanticCoverageError(ValueError):
    """Raised before paid generation when image prompts violate a slide contract."""


@dataclass(frozen=True)
class AssetSlotRequest:
    slide_index: int
    content_path: JsonPathGuide
    slot_name: str
    prompt: str
    role: AssetRole
    fit: str
    aspect_ratio: str
    required: bool
    asset_group: str | None
    requested_mode: str
    text_safe_area: str
    width: float
    height: float

    @property
    def consumer_id(self) -> str:
        return f"slide-{self.slide_index + 1}.{self.slot_name}"


@dataclass(frozen=True)
class AssetPlanItem:
    request_id: str
    generation_mode: GenerationMode
    slots: tuple[AssetSlotRequest, ...]
    grid_columns: int | None = None
    grid_rows: int | None = None

    @property
    def consumer_slot_count(self) -> int:
        return len(self.slots)


def _walk_image_elements(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("type") == "image" and isinstance(value.get("name"), str):
            found.append(value)
        for child in value.values():
            found.extend(_walk_image_elements(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_image_elements(child))
    return found


def _slot_name(path: JsonPathGuide) -> str:
    for guide in reversed(path.guides):
        if isinstance(guide, DictGuide):
            return guide.key
    raise ValueError("Image asset path has no named slot")


def _normalized_prompt(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt.strip().casefold())


def _normalized_semantic_text(value: str) -> str:
    # Semantic labels are authored by the planner and are intentionally short.
    # Removing punctuation/spacing makes the gate insensitive to harmless prompt
    # formatting while still requiring the same noun/feature phrase verbatim.
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def _required_asset_semantics(slide: SlideModel) -> list[str]:
    if not isinstance(slide.content, dict):
        return []
    contract = slide.content.get("__content_contract__")
    if not isinstance(contract, dict):
        return []
    raw = contract.get("required_asset_semantics")
    if not isinstance(raw, list):
        return []

    semantics: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        label = " ".join(item.strip().split())
        normalized = _normalized_semantic_text(label)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        semantics.append(label)
    return semantics


def validate_asset_semantic_coverage(
    slides: list[SlideModel],
    slots: list[AssetSlotRequest] | None = None,
) -> None:
    """Require planned visual semantics to survive slide-content generation.

    This is deliberately a pre-generation gate: if a lesson contract says a slide
    must show an apple, carrot, flower and leaf, but the generated image prompts
    describe a lamp, flashlight, television and cloud, the request fails here and
    no image provider call is made. Slides without a hidden contract keep the
    existing generic behavior.

    Only slides with unresolved image slots are checked. A completed deck may still
    carry its original prompts and contract, but reopening it must never be treated
    as a new paid generation request.
    """
    slots = slots if slots is not None else extract_asset_slots(slides)
    pending_slide_indices = {slot.slide_index for slot in slots}
    if not pending_slide_indices:
        return

    for slide in slides:
        if slide.index not in pending_slide_indices:
            continue
        required = _required_asset_semantics(slide)
        if not required:
            continue

        all_prompts = [
            prompt
            for _path, _parent, prompt in _asset_dicts_with_prompt(
                slide.content, IMAGE_PROMPT_KEYS
            )
        ]
        prompt_text = " ".join(all_prompts)
        normalized_prompt = _normalized_semantic_text(prompt_text)
        missing = [
            semantic
            for semantic in required
            if _normalized_semantic_text(semantic) not in normalized_prompt
        ]
        if not missing:
            continue

        if not prompt_text.strip():
            detail = "没有生成任何 image_prompt"
        else:
            detail = f"image_prompt 未覆盖：{', '.join(missing)}"
        raise AssetSemanticCoverageError(
            f"第 {slide.index + 1} 页图片语义预检失败：{detail}。"
            "已在调用图片模型前阻断，请重新生成该页内容。"
        )


def _ratio(width: float, height: float) -> str:
    if width <= 0 or height <= 0:
        return "auto"
    common = [(16, 9), (4, 3), (3, 2), (1, 1), (3, 4), (2, 3), (9, 16)]
    value = width / height
    numerator, denominator = min(
        common, key=lambda pair: abs(value - pair[0] / pair[1])
    )
    return f"{numerator}:{denominator}"


def _infer_role(element: dict[str, Any], width: float, height: float) -> AssetRole:
    explicit = element.get("asset_role")
    if explicit in {"background", "framed-image", "cutout"}:
        return explicit
    position = element.get("position") if isinstance(element.get("position"), dict) else {}
    # This fallback only recognizes an actual full-canvas frame. Transparent
    # cutouts are never guessed; they require explicit template metadata.
    if (
        width >= 1200
        and height >= 675
        and float(position.get("x", 0) or 0) <= 8
        and float(position.get("y", 0) or 0) <= 8
    ):
        return "background"
    return "framed-image"


def extract_asset_slots(slides: list[SlideModel]) -> list[AssetSlotRequest]:
    slots: list[AssetSlotRequest] = []
    for slide in slides:
        elements = {
            element["name"]: element
            for element in _walk_image_elements(slide.ui)
            if isinstance(element.get("name"), str)
        }
        for path, parent, prompt in _asset_dicts_with_prompt(
            slide.content, IMAGE_PROMPT_KEYS
        ):
            existing_url = parent.get("image_url") or parent.get("__image_url__")
            if (
                isinstance(existing_url, str)
                and existing_url.strip()
                and "placeholder" not in existing_url.casefold()
            ):
                continue
            name = _slot_name(path)
            element = elements.get(name, {})
            size = element.get("size") if isinstance(element.get("size"), dict) else {}
            width = float(size.get("width", 0) or 0)
            height = float(size.get("height", 0) or 0)
            role = _infer_role(element, width, height)
            requested_mode = str(element.get("asset_mode") or "auto")
            slots.append(
                AssetSlotRequest(
                    slide_index=slide.index,
                    content_path=path,
                    slot_name=name,
                    prompt=prompt,
                    role=role,
                    fit=str(element.get("fit") or "cover"),
                    aspect_ratio=str(element.get("aspect_ratio") or _ratio(width, height)),
                    required=bool(element.get("required", True)),
                    asset_group=(
                        str(element["asset_group"])
                        if element.get("asset_group")
                        else None
                    ),
                    requested_mode=requested_mode,
                    text_safe_area=str(element.get("text_safe_area") or "none"),
                    width=width,
                    height=height,
                )
            )
    return slots


def _grid_for(count: int) -> tuple[int, int]:
    if count <= 4:
        return 2, 2
    if count <= 6:
        return 3, 2
    raise ValueError("A sprite sheet supports at most 6 slots")


def build_asset_plan(slides: list[SlideModel]) -> list[AssetPlanItem]:
    slots = extract_asset_slots(slides)
    validate_asset_semantic_coverage(slides, slots)
    plan: list[AssetPlanItem] = []
    consumed: set[str] = set()

    # Identical prompts are generated once and mapped to every compatible slot.
    reuse_groups: dict[tuple[str, AssetRole, str], list[AssetSlotRequest]] = {}
    for slot in slots:
        reuse_groups.setdefault(
            (_normalized_prompt(slot.prompt), slot.role, slot.aspect_ratio), []
        ).append(slot)
    for group in reuse_groups.values():
        if len(group) < 2:
            continue
        plan.append(
            AssetPlanItem(
                request_id=f"img_{uuid.uuid4().hex}",
                generation_mode="reuse-or-search",
                slots=tuple(group),
            )
        )
        consumed.update(slot.consumer_id for slot in group)

    explicit_groups: dict[tuple[str, str], list[AssetSlotRequest]] = {}
    for slot in slots:
        if slot.consumer_id in consumed or not slot.asset_group:
            continue
        explicit_groups.setdefault((slot.requested_mode, slot.asset_group), []).append(slot)

    for (requested_mode, _group_name), group in explicit_groups.items():
        if requested_mode == "sprite-sheet":
            if not all(slot.role == "cutout" for slot in group):
                raise ValueError("sprite-sheet groups may contain cutout slots only")
            columns, rows = _grid_for(len(group))
            plan.append(
                AssetPlanItem(
                    request_id=f"img_{uuid.uuid4().hex}",
                    generation_mode="sprite-sheet",
                    slots=tuple(group),
                    grid_columns=columns,
                    grid_rows=rows,
                )
            )
        elif requested_mode == "composite-image":
            plan.append(
                AssetPlanItem(
                    request_id=f"img_{uuid.uuid4().hex}",
                    generation_mode="composite-image",
                    slots=tuple(group),
                )
            )
        else:
            continue
        consumed.update(slot.consumer_id for slot in group)

    for slot in slots:
        if slot.consumer_id in consumed:
            continue
        mode: GenerationMode
        if slot.role == "background":
            mode = "direct-background"
        elif slot.role == "cutout":
            mode = "single-cutout"
        else:
            mode = "reuse-or-search"
        plan.append(
            AssetPlanItem(
                request_id=f"img_{uuid.uuid4().hex}",
                generation_mode=mode,
                slots=(slot,),
            )
        )

    return plan
