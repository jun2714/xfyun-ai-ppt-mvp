from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from models.layout_metadata import LayoutMetadata
from templates.v2.models.layouts import (
    Component,
    MergedComponent,
    MergedComponents,
    RawSlideLayout,
    SlideLayout,
    SlideLayouts,
)
from templates.v2.models.elements import Position, SlideElement


_SLIDE_ELEMENT_ADAPTER = TypeAdapter(SlideElement)


class EditableFieldSpec(BaseModel):
    source_name: str = Field(alias="sourceName", min_length=1)
    name: str = Field(min_length=1, max_length=80)
    font_size: float | None = Field(default=None, alias="fontSize", ge=16, le=160)
    font_family: str | None = Field(default=None, alias="fontFamily", min_length=1)
    max_length: int | None = Field(default=None, alias="maxLength", ge=1)

    model_config = ConfigDict(populate_by_name=True)


class AssetSlotSpec(BaseModel):
    source_name: str = Field(alias="sourceName", min_length=1)
    name: str = Field(min_length=1, max_length=80)
    role: Literal["background", "framed-image", "cutout"]
    mode: Literal[
        "auto",
        "direct-background",
        "composite-image",
        "sprite-sheet",
        "single-cutout",
        "reuse-or-search",
    ] = "auto"
    group: str | None = None
    aspect_ratio: str | None = Field(default=None, alias="aspectRatio")
    text_safe_area: Literal["none", "left", "right", "center"] = Field(
        default="none", alias="textSafeArea"
    )
    required: bool = True

    model_config = ConfigDict(populate_by_name=True)


class CuratedLayoutSpec(BaseModel):
    source_index: int = Field(alias="sourceIndex", ge=0)
    id: str = Field(min_length=3, max_length=80)
    description: str = Field(min_length=10, max_length=300)
    metadata: LayoutMetadata
    editable_fields: list[EditableFieldSpec] = Field(
        default_factory=list, alias="editableFields"
    )
    asset_slots: list[AssetSlotSpec] = Field(default_factory=list, alias="assetSlots")

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _names_are_unique(self) -> "CuratedLayoutSpec":
        output_names = [field.name for field in self.editable_fields]
        output_names.extend(slot.name for slot in self.asset_slots)
        if len(output_names) != len(set(output_names)):
            raise ValueError("editable field and asset slot names must be unique")

        source_names = [field.source_name for field in self.editable_fields]
        source_names.extend(slot.source_name for slot in self.asset_slots)
        if len(source_names) != len(set(source_names)):
            raise ValueError("a source element can only be curated once")
        return self


class DeriveTemplateLayoutsRequest(BaseModel):
    template_id: str = Field(alias="templateId", min_length=1)
    layouts: list[CuratedLayoutSpec] = Field(min_length=1)

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def _layout_ids_and_sources_are_unique(self) -> "DeriveTemplateLayoutsRequest":
        ids = [layout.id for layout in self.layouts]
        if len(ids) != len(set(ids)):
            raise ValueError("curated layout ids must be unique")
        sources = [layout.source_index for layout in self.layouts]
        if len(sources) != len(set(sources)):
            raise ValueError("a raw source slide can only be selected once")
        return self


def derive_template_layouts_without_model(
    raw_layouts: list[RawSlideLayout],
    specs: list[CuratedLayoutSpec],
) -> tuple[SlideLayouts, MergedComponents, list[int]]:
    """Create editable layouts from explicitly curated raw slides.

    The source-to-field mapping lives in data supplied by a curator. Keeping it out
    of runtime topic branches makes imports deterministic and prevents model calls
    during template construction.
    """

    generated: list[SlideLayout] = []
    layout_indexes: list[int] = []
    for spec in specs:
        if spec.source_index >= len(raw_layouts):
            raise ValueError(f"source slide index {spec.source_index} is out of range")
        generated.append(_derive_layout(raw_layouts[spec.source_index], spec))
        layout_indexes.append(spec.source_index)

    layouts = SlideLayouts(layouts=generated)
    merged = MergedComponents(
        components=[
            MergedComponent(
                id=layout.components[0].id,
                description=layout.components[0].description,
                variants=[layout.components[0]],
            )
            for layout in layouts.layouts
        ]
    )
    return layouts, merged, layout_indexes


def _derive_layout(raw: RawSlideLayout, spec: CuratedLayoutSpec) -> SlideLayout:
    editable = {field.source_name: field for field in spec.editable_fields}
    asset_slots = {slot.source_name: slot for slot in spec.asset_slots}
    found: set[str] = set()

    elements = [
        _curate_element(element, editable, asset_slots, found)
        for element in raw.elements
    ]
    requested = set(editable) | set(asset_slots)
    missing = sorted(requested - found)
    if missing:
        raise ValueError(
            f"curated source elements do not exist on slide {spec.source_index + 1}: "
            + ", ".join(missing)
        )

    component = Component(
        id=f"{spec.id}_canvas",
        description="Complete editable canvas preserving the curated source geometry.",
        position=Position(x=0, y=0),
        elements=elements,
    )
    return SlideLayout(
        id=spec.id,
        description=spec.description,
        components=[component],
        metadata=spec.metadata,
    )


def _curate_element(
    element: SlideElement,
    editable: dict[str, EditableFieldSpec],
    asset_slots: dict[str, AssetSlotSpec],
    found: set[str],
) -> SlideElement:
    data = element.model_dump(mode="json", exclude_none=True)
    _curate_element_dict(data, editable, asset_slots, found)
    return _SLIDE_ELEMENT_ADAPTER.validate_python(data)


def _curate_element_dict(
    data: dict[str, Any],
    editable: dict[str, EditableFieldSpec],
    asset_slots: dict[str, AssetSlotSpec],
    found: set[str],
) -> None:
    source_name = data.get("name")
    if isinstance(source_name, str) and source_name in editable:
        spec = editable[source_name]
        if data.get("type") in {
            "text",
            "text-list",
            "math",
            "table",
            "chart",
            "infographic",
        }:
            # PPTX importers occasionally assign the same source name to a
            # decorative image and its overlaid text. Select by semantic type
            # instead of failing on the first duplicate encountered.
            data["name"] = spec.name
            data["decorative"] = False
            if spec.max_length is not None:
                data["max_length"] = spec.max_length
                # Template V2 intentionally requires minimum length to equal half
                # the maximum. Recompute both so a curator cannot create an invalid
                # schema while repairing a layout for Chinese text.
                data["min_length"] = (spec.max_length + 1) // 2
            if spec.font_size is not None:
                font = data.setdefault("font", {})
                font["size"] = spec.font_size
                for run in data.get("runs") or []:
                    if isinstance(run, dict):
                        run_font = run.setdefault("font", {})
                        run_font["size"] = spec.font_size
            if spec.font_family is not None:
                font = data.setdefault("font", {})
                font["family"] = spec.font_family
                for run in data.get("runs") or []:
                    if isinstance(run, dict):
                        run_font = run.setdefault("font", {})
                        run_font["family"] = spec.font_family
            found.add(source_name)

    if isinstance(source_name, str) and source_name in asset_slots:
        spec = asset_slots[source_name]
        if data.get("type") == "image":
            data.update(
                {
                    "name": spec.name,
                    "decorative": False,
                    "asset_role": spec.role,
                    "asset_mode": spec.mode,
                    "asset_group": spec.group,
                    "aspect_ratio": spec.aspect_ratio,
                    "text_safe_area": spec.text_safe_area,
                    "required": spec.required,
                }
            )
            found.add(source_name)

    for child in _element_children(data):
        _curate_element_dict(child, editable, asset_slots, found)


def _element_children(data: dict[str, Any]) -> Iterable[dict[str, Any]]:
    child = data.get("child")
    if isinstance(child, dict):
        yield child
    children = data.get("children")
    if isinstance(children, list):
        for item in children:
            if isinstance(item, dict):
                yield item
