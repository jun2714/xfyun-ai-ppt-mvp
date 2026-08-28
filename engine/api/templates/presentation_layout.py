import json
from typing import List, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

from models.presentation_structure_model import PresentationStructureModel
from models.layout_metadata import LayoutMetadata
from utils.icon_weights import DEFAULT_ICON_TYPE, extract_icon_type_from_settings


# These bundled families are currently used as child-facing kindergarten themes.
# They still contain a few legacy business/chart layouts inherited from the source
# project. Until a template explicitly opts back in, charts are excluded so a
# preschool lesson can never be forced to fabricate percentages or dashboard data.
KINDERGARTEN_NO_CHART_TEMPLATE_NAMES = {
    "dynamic",
    "modern",
    "momentum",
    "standard",
    "swift",
}


class SlideLayoutModel(BaseModel):
    id: str
    name: Optional[str] = None
    description: Optional[str] = None
    json_schema: dict
    metadata: Optional[LayoutMetadata] = None


class PresentationLayoutModel(BaseModel):
    name: str
    ordered: bool = Field(default=False)
    icon_type: str = Field(default=DEFAULT_ICON_TYPE)
    icon_weight: str = Field(default=DEFAULT_ICON_TYPE)
    allow_charts: bool = Field(default=True)
    slides: List[SlideLayoutModel]

    @model_validator(mode="before")
    @classmethod
    def normalize_runtime_settings(cls, data):
        if isinstance(data, dict):
            normalized = dict(data)
            icon_type = extract_icon_type_from_settings(normalized)
            normalized["icon_type"] = icon_type
            normalized["icon_weight"] = icon_type

            # Explicit template metadata/JSON always wins. The name-based default
            # protects the bundled kindergarten families even before routing.json
            # metadata is imported into older deployments.
            if "allow_charts" not in normalized:
                name = str(normalized.get("name") or "").strip().casefold()
                normalized["allow_charts"] = (
                    name not in KINDERGARTEN_NO_CHART_TEMPLATE_NAMES
                )
            return normalized
        return data

    def get_slide_layout_index(self, slide_layout_id: str) -> int:
        for index, slide in enumerate(self.slides):
            if slide.id == slide_layout_id:
                return index
        raise HTTPException(
            status_code=404, detail=f"Slide layout {slide_layout_id} not found"
        )

    def to_presentation_structure(self) -> PresentationStructureModel:
        return PresentationStructureModel(
            slides=[index for index in range(len(self.slides))]
        )

    def to_string(self, with_schema: bool = False) -> str:
        message = "## Presentation Layout\n\n"
        for index, slide in enumerate(self.slides):
            message += f"### Slide Layout: {index}\n"
            message += f"- Name: {slide.name or slide.json_schema.get('title')}\n"
            message += f"- Description: {slide.description}\n"
            if slide.metadata:
                metadata_text = json.dumps(
                    slide.metadata.model_dump(mode="json", by_alias=True),
                    ensure_ascii=False,
                )
                message += f"- Capability Metadata: {metadata_text}\n"
            if with_schema:
                try:
                    schema_text = json.dumps(slide.json_schema, ensure_ascii=False)
                except (TypeError, ValueError):
                    schema_text = str(slide.json_schema)
                message += f"- Schema: {schema_text}\n"
            message += "\n"
        return message
