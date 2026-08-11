#!/usr/bin/env python3
"""Package a reviewed subset of an existing bundled Presenton template.

The manifest is an explicit curator decision.  This script never infers a
layout from a topic or presentation position; it only copies layouts that were
visually reviewed and attaches their generic capability contracts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-template", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "templates")
    args = parser.parse_args()

    source_file = args.source_template.resolve()
    source_directory = source_file.parent
    source = json.loads(source_file.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))

    source_by_id = {layout["id"]: layout for layout in source.get("layouts", [])}
    selected: list[dict[str, Any]] = []
    for review in manifest["layouts"]:
        layout_id = review["sourceLayoutId"]
        if layout_id not in source_by_id:
            raise ValueError(f"unknown source layout: {layout_id}")
        layout = json.loads(json.dumps(source_by_id[layout_id]))
        _apply_element_repairs(layout, review.get("elementRepairs", []))
        layout["metadata"] = review["metadata"]
        selected.append(layout)

    if not selected:
        raise ValueError("the curated template must contain at least one layout")
    if any(_quality_status(layout) != "passed" for layout in selected):
        raise ValueError("every packaged layout must have passed visual review")

    component_ids = {
        component.get("id")
        for layout in selected
        for component in layout.get("components", [])
        if isinstance(component, dict) and component.get("id")
    }
    merged_components = [
        component
        for component in source.get("merged_components", [])
        if component.get("id") in component_ids
    ]

    output_id = manifest["templateId"]
    output_directory = args.output_root / output_id
    static_directory = output_directory / "static"
    if output_directory.exists():
        shutil.rmtree(output_directory)
    static_directory.mkdir(parents=True)

    payload = {
        "id": output_id,
        "name": manifest["name"],
        "description": manifest["description"],
        "iconType": source.get("iconType", source.get("icon_type", "regular")),
        "fonts": source.get("fonts", {}),
        "layouts": selected,
        "merged_components": merged_components,
        "metadata": {
            **manifest["templateMetadata"],
            "sourceId": manifest["sourceId"],
            "license": manifest["license"],
            "attribution": manifest["attribution"],
            "sourceTemplateSha256": _sha256(source_file),
            "qualityEvidence": manifest["qualityEvidence"],
        },
    }

    referenced_assets = sorted(set(_static_assets(payload)))
    for relative in referenced_assets:
        source_asset = (source_directory / relative).resolve()
        if source_directory not in source_asset.parents or not source_asset.is_file():
            raise ValueError(f"missing or unsafe template asset: {relative}")
        target = output_directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_asset, target)

    thumbnail = source.get("thumbnail")
    if isinstance(thumbnail, str) and thumbnail.startswith("static/"):
        source_thumbnail = source_directory / thumbnail
        if source_thumbnail.is_file():
            target_thumbnail = output_directory / thumbnail
            target_thumbnail.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_thumbnail, target_thumbnail)
            payload["thumbnail"] = thumbnail

    (output_directory / "template.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "templateId": output_id,
                "layouts": len(selected),
                "assets": len(referenced_assets),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _quality_status(layout: dict[str, Any]) -> str | None:
    metadata = layout.get("metadata") or {}
    return metadata.get("qualityStatus") or metadata.get("quality_status")


def _walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _apply_element_repairs(
    layout: dict[str, Any], repairs: list[dict[str, Any]]
) -> None:
    """Apply only explicit, reviewable element repairs from the manifest."""
    elements = [item for item in _walk(layout.get("components", [])) if isinstance(item, dict)]
    for repair in repairs:
        matching = [item for item in elements if item.get("name") == repair["name"]]
        occurrence = int(repair.get("occurrence", 0))
        if occurrence >= len(matching):
            raise ValueError(
                f"repair target is missing in {layout.get('id')}: "
                f"{repair['name']}[{occurrence}]"
            )
        element = matching[occurrence]
        for key, value in repair["set"].items():
            _set_nested(element, key.split("."), value)


def _set_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    current = target
    for segment in path[:-1]:
        child = current.get(segment)
        if not isinstance(child, dict):
            child = {}
            current[segment] = child
        current = child
    current[path[-1]] = value


def _static_assets(value: Any) -> Iterator[str]:
    for item in _walk(value):
        if not isinstance(item, str) or not item.startswith("static/"):
            continue
        path = Path(item)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe static asset path: {item}")
        yield path.as_posix()


def _sha256(file: Path) -> str:
    digest = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
