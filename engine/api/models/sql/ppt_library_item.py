from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, Uuid
from sqlmodel import Field, SQLModel

from utils.datetime_utils import get_current_utc_datetime
from api.v1.auth.context import get_current_owner_id


def _new_library_item_id() -> str:
    return str(uuid.uuid4())


class PptLibraryItem(SQLModel, table=True):
    """Shared PPT case library. Not owner-scoped; originals are never overwritten by teacher edits."""

    __tablename__ = "ppt_library_items"

    id: str = Field(primary_key=True, default_factory=_new_library_item_id)
    title: str = Field(nullable=False)
    description: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    category: str = Field(default="其他", sa_column=Column(String(64), nullable=False, index=True))
    age_group: str = Field(default="混龄", sa_column=Column(String(32), nullable=False, index=True))
    page_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    thumbnail: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    pptx_path: str = Field(sa_column=Column(Text, nullable=False))
    layouts: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    raw_layouts: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    assets: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    download_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    visibility: str = Field(
        default="official",
        sa_column=Column(String(16), nullable=False, index=True, server_default="official"),
    )
    season: str = Field(
        default="不限",
        sa_column=Column(String(16), nullable=False, index=True, server_default="不限"),
    )
    scene: str = Field(
        default="其他",
        sa_column=Column(String(16), nullable=False, index=True, server_default="其他"),
    )
    created_by: Optional[uuid.UUID] = Field(
        default_factory=get_current_owner_id,
        sa_column=Column("created_by", Uuid, nullable=True, index=True),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, default=get_current_utc_datetime
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            default=get_current_utc_datetime,
            onupdate=get_current_utc_datetime,
        )
    )
