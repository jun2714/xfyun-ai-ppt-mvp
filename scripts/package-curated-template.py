#!/usr/bin/env python3
"""Package an audited database template as a portable bundled template."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-id", required=True)
    parser.add_argument("--output-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--curation-manifest", type=Path, required=True)
    parser.add_argument("--source-pptx", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=ROOT / ".data/engine/fastapi.db")
    parser.add_argument("--app-data", type=Path, default=ROOT / ".data/engine")
    parser.add_argument("--output-root", type=Path, default=ROOT / "templates")
    args = parser.parse_args()

    manifest = json.loads(args.curation_manifest.read_text(encoding="utf-8"))
    with sqlite3.connect(args.database) as connection:
        row = connection.execute(
            "select layouts, assets from template_v2 where id = ?",
            (args.template_id,),
        ).fetchone()
    if row is None:
        raise SystemExit(f"template not found: {args.template_id}")

    layouts_payload = json.loads(row[0])
    source_assets = json.loads(row[1]) if row[1] else {}
    # The curation manifest is the portable source of truth for contracts.
    # Database layouts hold reviewed geometry, but their metadata may predate a
    # later contract correction. Requiring both statuses prevents an unreviewed
    # manifest entry or a stale database flag from entering production alone.
    reviews_by_id = {
        review["id"]: review
        for review in manifest.get("layouts", [])
        if isinstance(review, dict) and review.get("id")
    }
    passed: list[dict[str, Any]] = []
    for stored_layout in layouts_payload.get("layouts", []):
        review = reviews_by_id.get(stored_layout.get("id"))
        if review is None:
            continue
        if _quality_status(stored_layout) != "passed":
            continue
        if _quality_status({"metadata": review.get("metadata") or {}}) != "passed":
            continue
        layout = copy.deepcopy(stored_layout)
        layout["description"] = review.get("description", layout.get("description"))
        layout["metadata"] = copy.deepcopy(review["metadata"])
        passed.append(layout)
    if not passed:
        raise SystemExit("template has no visually accepted layouts")

    passed.extend(_build_curated_variants(passed, manifest.get("variants") or []))
    optimization = manifest.get("decorativeOptimization") or {}
    size_limit = optimization.get("removeImagesAtOrBelow") or {}
    if size_limit:
        passed = _remove_small_decorative_images(
            passed,
            max_width=float(size_limit["width"]),
            max_height=float(size_limit["height"]),
        )

    output_directory = args.output_root / args.output_id
    static_directory = output_directory / "static" / "assets"
    # Repackaging must be reproducible. Keeping assets from the previous family
    # can silently ship fixed characters that no accepted layout references.
    if output_directory.exists():
        shutil.rmtree(output_directory)
    static_directory.mkdir(parents=True, exist_ok=True)

    portable_layouts = _copy_and_rewrite_assets(
        {"layouts": passed},
        app_data=args.app_data.resolve(),
        static_directory=static_directory,
    )
    overlay_asset = optimization.get("sharedOverlayAsset")
    if isinstance(overlay_asset, str) and overlay_asset:
        source_overlay = (args.curation_manifest.parent / overlay_asset).resolve()
        if args.curation_manifest.parent.resolve() not in source_overlay.parents:
            raise ValueError(f"unsafe decorative overlay path: {overlay_asset}")
        if not source_overlay.is_file():
            raise ValueError(f"decorative overlay is missing: {source_overlay}")
        target_name = f"theme-{source_overlay.name}"
        shutil.copy2(source_overlay, static_directory / target_name)
        _insert_shared_overlay(
            portable_layouts["layouts"], f"static/assets/{target_name}"
        )
    merged_components = {
        "components": [
            {
                "id": component["id"],
                "description": component["description"],
                "variants": [component],
            }
            for layout in portable_layouts["layouts"]
            for component in layout.get("components", [])
        ]
    }
    family_metadata = manifest.get("templateMetadata") or {}
    package = {
        "id": args.output_id,
        "name": args.name,
        "description": args.description,
        "iconType": source_assets.get("icon_type", "regular"),
        "fonts": source_assets.get("fonts", {}),
        "layouts": portable_layouts["layouts"],
        "merged_components": merged_components,
        "metadata": {
            "audiences": family_metadata.get(
                "audiences", ["children", "parents", "teachers"]
            ),
            "moods": family_metadata.get("moods", []),
            "capabilities": family_metadata.get("capabilities", []),
            "license": manifest["license"],
            "attribution": manifest["attribution"],
            "sourceId": manifest["sourceId"],
            "sourcePptxSha256": _sha256(args.source_pptx),
            "retainedSourceSlides": manifest["retainedSourceSlides"],
            "removedSourceSlides": manifest["removedSourceSlides"],
            "qualityEvidence": {
                "renderer": "WPS Presentation",
                "canvas": "1280x720",
                "imagePolicy": "disabled",
            },
        },
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "template.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "templateId": args.output_id,
                "layouts": len(passed),
                "assets": len(list(static_directory.iterdir())),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _quality_status(layout: dict[str, Any]) -> str | None:
    metadata = layout.get("metadata") or {}
    return metadata.get("qualityStatus") or metadata.get("quality_status")


def _build_curated_variants(
    source_layouts: list[dict[str, Any]],
    variant_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Create explicit geometry variants from already accepted source layouts."""
    source_by_id = {layout["id"]: layout for layout in source_layouts}
    variants: list[dict[str, Any]] = []
    for spec in variant_specs:
        source_id = spec["sourceLayoutId"]
        if source_id not in source_by_id:
            raise ValueError(f"variant source layout is not accepted: {source_id}")
        variant = copy.deepcopy(source_by_id[source_id])
        variant["id"] = spec["id"]
        variant["description"] = spec["description"]
        variant["metadata"] = spec["metadata"]
        remove_names = set(spec.get("removeElements") or [])
        transforms = {
            item["name"]: item["set"] for item in spec.get("elementRepairs") or []
        }
        for component in variant.get("components", []):
            # The component catalog requires globally unique IDs even when a
            # layout variant started as a clone of an accepted source layout.
            source_component_id = str(component.get("id") or "component")
            component["id"] = f"{spec['id']}_{source_component_id}"[:120]
            component["elements"] = _transform_elements(
                component.get("elements", []), remove_names, transforms
            )
        variants.append(variant)
    return variants


def _transform_elements(
    elements: list[Any],
    remove_names: set[str],
    transforms: dict[str, dict[str, Any]],
) -> list[Any]:
    transformed: list[Any] = []
    for element in elements:
        if not isinstance(element, dict):
            transformed.append(element)
            continue
        if element.get("name") in remove_names:
            continue
        item = copy.deepcopy(element)
        for key, value in transforms.get(str(item.get("name")), {}).items():
            _set_nested(item, key.split("."), value)
        if isinstance(item.get("children"), list):
            item["children"] = _transform_elements(
                item["children"], remove_names, transforms
            )
        if isinstance(item.get("elements"), list):
            item["elements"] = _transform_elements(
                item["elements"], remove_names, transforms
            )
        child = item.get("child")
        if isinstance(child, dict):
            children = _transform_elements([child], remove_names, transforms)
            item["child"] = children[0] if children else None
        transformed.append(item)
    return transformed


def _remove_small_decorative_images(
    layouts: list[dict[str, Any]], *, max_width: float, max_height: float
) -> list[dict[str, Any]]:
    optimized = copy.deepcopy(layouts)
    for layout in optimized:
        for component in layout.get("components", []):
            component["elements"] = _filter_small_decorations(
                component.get("elements", []), max_width, max_height
            )
    return optimized


def _filter_small_decorations(
    elements: list[Any], max_width: float, max_height: float
) -> list[Any]:
    result: list[Any] = []
    for element in elements:
        if not isinstance(element, dict):
            result.append(element)
            continue
        size = element.get("size") or {}
        if (
            element.get("type") == "image"
            and element.get("decorative") is True
            and float(size.get("width", max_width + 1)) <= max_width
            and float(size.get("height", max_height + 1)) <= max_height
        ):
            continue
        item = copy.deepcopy(element)
        if isinstance(item.get("children"), list):
            item["children"] = _filter_small_decorations(
                item["children"], max_width, max_height
            )
        result.append(item)
    return result


def _insert_shared_overlay(layouts: list[dict[str, Any]], asset_path: str) -> None:
    for layout in layouts:
        components = layout.get("components") or []
        if not components:
            continue
        elements = components[0].setdefault("elements", [])
        insert_at = 1 if elements else 0
        elements.insert(
            insert_at,
            {
                "type": "image",
                "position": {"x": 0, "y": 0},
                "size": {"width": 1280, "height": 720},
                "data": asset_path,
                "fit": "fill",
                "decorative": True,
                "name": f"{layout['id']}_shared_confetti_background",
                "is_icon": False,
                "required": True,
            },
        )


def _set_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    current = target
    for segment in path[:-1]:
        child = current.get(segment)
        if not isinstance(child, dict):
            child = {}
            current[segment] = child
        current = child
    current[path[-1]] = value


def _copy_and_rewrite_assets(
    value: Any,
    *,
    app_data: Path,
    static_directory: Path,
) -> Any:
    if isinstance(value, list):
        return [
            _copy_and_rewrite_assets(
                item,
                app_data=app_data,
                static_directory=static_directory,
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    rewritten = {
        key: _copy_and_rewrite_assets(
            child,
            app_data=app_data,
            static_directory=static_directory,
        )
        for key, child in value.items()
    }
    if rewritten.get("type") != "image":
        return rewritten
    source_url = rewritten.get("data")
    if not isinstance(source_url, str):
        return rewritten

    source = _resolve_app_data_url(source_url, app_data)
    if source is None:
        raise ValueError(f"template image is not a local app-data asset: {source_url}")
    digest = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:12]
    target_name = f"{digest}-{source.name}"
    shutil.copy2(source, static_directory / target_name)
    rewritten["data"] = f"static/assets/{target_name}"
    return rewritten


def _resolve_app_data_url(value: str, app_data: Path) -> Path | None:
    parsed = urlparse(value)
    path = unquote(parsed.path if parsed.scheme else value)
    prefix = "/app_data/"
    if not path.startswith(prefix):
        return None
    candidate = (app_data / path[len(prefix) :]).resolve()
    if app_data not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def _sha256(file: Path) -> str:
    digest = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
