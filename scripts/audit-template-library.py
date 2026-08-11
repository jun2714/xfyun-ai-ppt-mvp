import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "engine" / "api"))

from templates.v2.models.layouts import MergedComponents, SlideLayouts  # noqa: E402
from templates.v2.schema import get_template_schema  # noqa: E402


SLIDE_WIDTH = 1280.0
SLIDE_HEIGHT = 720.0
IMAGE_PROMPT_KEYS = {"image_prompt", "__image_prompt__"}
INDEXED_FIELD_PATTERN = re.compile(r"^(.*?)(\d+)(.*)$")


def walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def schema_image_count(value: Any) -> int:
    if isinstance(value, dict):
        count = sum(key in value for key in IMAGE_PROMPT_KEYS)
        return count + sum(schema_image_count(child) for child in value.values())
    if isinstance(value, list):
        return sum(schema_image_count(child) for child in value)
    return 0


def global_bounds(component: dict[str, Any], element: dict[str, Any]):
    position = element.get("position") or {}
    size = element.get("size") or {}
    if not all(isinstance(value, (int, float)) for value in size.values()):
        return None
    return (
        float(position.get("x", 0)),
        float(position.get("y", 0)),
        float(size.get("width", 0)),
        float(size.get("height", 0)),
    )


def infer_fixed_item_capacity(layout: dict[str, Any]) -> int | None:
    """Infer exact capacity for layouts with separately named numbered fields.

    A fixed collection such as item_1..item_8 cannot honestly advertise a
    variable 4..8 capacity: hydration requires every named field. Dynamic
    flex/grid collections are excluded because their child count is genuinely
    variable and is enforced by their own schema.
    """
    elements = list(walk(layout.get("components") or []))
    if any(
        element.get("type") in {"flex", "grid"}
        and isinstance(element.get("min_children"), int)
        and isinstance(element.get("max_children"), int)
        for element in elements
    ):
        return None

    groups: dict[tuple[str, str], set[int]] = {}
    for element in elements:
        if element.get("decorative") is not False:
            continue
        name = element.get("name")
        if not isinstance(name, str):
            continue
        match = INDEXED_FIELD_PATTERN.match(name)
        if not match:
            continue
        key = (match.group(1), match.group(3))
        groups.setdefault(key, set()).add(int(match.group(2)))

    contiguous_capacities = [
        max(indices)
        for indices in groups.values()
        if len(indices) >= 2 and indices == set(range(1, max(indices) + 1))
    ]
    return max(contiguous_capacities) if contiguous_capacities else None


def audit_layout(layout: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    layout_id = str(layout.get("id") or "")
    metadata = layout.get("metadata")
    quality_status = (
        (metadata.get("qualityStatus") or metadata.get("quality_status"))
        if isinstance(metadata, dict)
        else None
    )
    passed = quality_status == "passed"
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    names: set[str] = set()
    editable_images = 0
    editable_text = 0

    for component in layout.get("components") or []:
        if not isinstance(component, dict):
            continue
        for element in walk(component.get("elements") or []):
            if element.get("decorative") is not False:
                continue
            element_type = element.get("type")
            name = element.get("name")
            if not isinstance(name, str) or not name.strip():
                errors.append({"code": "EDITABLE_ELEMENT_NAME_MISSING"})
            elif name in names:
                errors.append({"code": "EDITABLE_ELEMENT_NAME_DUPLICATE", "name": name})
            else:
                names.add(name)

            bounds = global_bounds(component, element)
            if bounds:
                x, y, width, height = bounds
                if width <= 0 or height <= 0:
                    errors.append({"code": "EDITABLE_ELEMENT_EMPTY_BOUNDS", "name": name})
                elif x < -1 or y < -1 or x + width > SLIDE_WIDTH + 1 or y + height > SLIDE_HEIGHT + 1:
                    errors.append({"code": "EDITABLE_ELEMENT_OUT_OF_BOUNDS", "name": name})

            if element_type == "text":
                editable_text += 1
                font = element.get("font") or {}
                font_size = font.get("size")
                if not isinstance(font_size, (int, float)) or font_size < 16:
                    errors.append({"code": "TEXT_BELOW_ABSOLUTE_MINIMUM", "name": name})
                if not element.get("runs"):
                    errors.append({"code": "TEXT_RUNS_MISSING", "name": name})
            elif element_type == "image":
                editable_images += 1
                if element.get("asset_role") not in {"background", "framed-image", "cutout"}:
                    errors.append({"code": "IMAGE_ROLE_MISSING", "name": name})
                if element.get("asset_mode") not in {
                    "auto",
                    "direct-background",
                    "composite-image",
                    "sprite-sheet",
                    "single-cutout",
                    "reuse-or-search",
                }:
                    errors.append({"code": "IMAGE_MODE_MISSING", "name": name})

    schema_images = schema_image_count(schema)
    if schema_images != editable_images:
        errors.append(
            {
                "code": "IMAGE_SCHEMA_SLOT_MISMATCH",
                "schema": schema_images,
                "editable": editable_images,
            }
        )
    if not isinstance(metadata, dict):
        warnings.append({"code": "LAYOUT_METADATA_MISSING"})
    else:
        readability = metadata.get("readability") or {}
        declared_minimum = readability.get("minimumFontSize") or readability.get(
            "minimum_font_size"
        )
        for element in walk(layout.get("components") or []):
            if element.get("type") != "text" or element.get("decorative") is not False:
                continue
            size = (element.get("font") or {}).get("size")
            if isinstance(declared_minimum, (int, float)) and isinstance(size, (int, float)) and size < declared_minimum:
                errors.append({"code": "TEXT_BELOW_DECLARED_MINIMUM", "name": element.get("name")})
        media = metadata.get("media") or {}
        declared_images = sum(
            int(media.get(key, 0) or 0)
            for key in (
                "backgroundSlots",
                "framedImageSlots",
                "cutoutSlots",
                "background_slots",
                "framed_image_slots",
                "cutout_slots",
            )
        )
        if declared_images != editable_images:
            errors.append(
                {
                    "code": "MEDIA_SLOT_COUNT_MISMATCH",
                    "declared": declared_images,
                    "editable": editable_images,
                }
            )

        content_shape = metadata.get("contentShape") or metadata.get("content_shape") or {}
        declared_min_items = content_shape.get("minItems", content_shape.get("min_items"))
        declared_max_items = content_shape.get("maxItems", content_shape.get("max_items"))
        fixed_capacity = infer_fixed_item_capacity(layout)
        if fixed_capacity is not None and (
            declared_min_items != fixed_capacity or declared_max_items != fixed_capacity
        ):
            errors.append(
                {
                    "code": "FIXED_ITEM_CAPACITY_MISMATCH",
                    "inferred": fixed_capacity,
                    "declaredMin": declared_min_items,
                    "declaredMax": declared_max_items,
                }
            )

    # Pending layouts may remain editable for migration, but only a layout
    # explicitly claiming to be passed can fail the production audit.
    return {
        "id": layout_id,
        "qualityStatus": "passed" if passed else "pending",
        "editableText": editable_text,
        "editableImages": editable_images,
        "errors": errors if passed else [],
        "warnings": warnings + ([] if passed else errors),
    }


def audit_template(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    # Validation also guarantees unique IDs and valid component structures.
    SlideLayouts.model_validate({"layouts": data.get("layouts")})
    merged = data.get("merged_components")
    if merged is not None:
        MergedComponents.model_validate(
            {"components": merged} if isinstance(merged, list) else merged
        )
    schemas = get_template_schema(data, source_file=str(path))
    results = [
        audit_layout(layout, schema_item["schema"])
        for layout, schema_item in zip(data["layouts"], schemas["layouts"])
    ]
    return {
        "id": data.get("id") or path.parent.name,
        "layoutCount": len(results),
        "passedLayouts": sum(item["qualityStatus"] == "passed" and not item["errors"] for item in results),
        "pendingLayouts": sum(item["qualityStatus"] != "passed" for item in results),
        "errorCount": sum(len(item["errors"]) for item in results),
        "warningCount": sum(len(item["warnings"]) for item in results),
        "layouts": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--templates-root", type=Path, default=REPOSITORY_ROOT / "templates")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict-exit", action="store_true")
    args = parser.parse_args()

    reports = [
        audit_template(path)
        for path in sorted(args.templates_root.glob("*/template.json"))
    ]
    report = {
        "templateCount": len(reports),
        "passedLayouts": sum(item["passedLayouts"] for item in reports),
        "pendingLayouts": sum(item["pendingLayouts"] for item in reports),
        "errorCount": sum(item["errorCount"] for item in reports),
        "warningCount": sum(item["warningCount"] for item in reports),
        "templates": reports,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 2 if args.strict_exit and report["errorCount"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
