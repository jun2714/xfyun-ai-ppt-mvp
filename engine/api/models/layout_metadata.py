from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class LayoutContentShape(BaseModel):
    relationship: Optional[str] = None
    min_items: int = Field(default=0, alias="minItems", ge=0)
    max_items: int = Field(default=1, alias="maxItems", ge=0)
    text_blocks: int = Field(default=1, alias="textBlocks", ge=0)
    image_slots: int = Field(default=0, alias="imageSlots", ge=0)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def validate_item_range(self):
        if self.max_items < self.min_items:
            raise ValueError("maxItems must be greater than or equal to minItems")
        return self


class LayoutMediaMetadata(BaseModel):
    background_slots: int = Field(default=0, alias="backgroundSlots", ge=0)
    framed_image_slots: int = Field(default=0, alias="framedImageSlots", ge=0)
    cutout_slots: int = Field(default=0, alias="cutoutSlots", ge=0)
    required: bool = False

    model_config = {"populate_by_name": True}

    @property
    def total_slots(self) -> int:
        return self.background_slots + self.framed_image_slots + self.cutout_slots


class LayoutReadabilityMetadata(BaseModel):
    minimum_font_size: int = Field(alias="minimumFontSize", ge=12)
    maximum_visible_characters: int = Field(
        alias="maximumVisibleCharacters", ge=1
    )

    model_config = {"populate_by_name": True}


class LayoutMetadata(BaseModel):
    capabilities: List[str] = Field(min_length=1)
    content_shape: LayoutContentShape = Field(alias="contentShape")
    media: LayoutMediaMetadata
    readability: LayoutReadabilityMetadata
    quality_status: str = Field(default="pending", alias="qualityStatus")

    model_config = {"populate_by_name": True}
