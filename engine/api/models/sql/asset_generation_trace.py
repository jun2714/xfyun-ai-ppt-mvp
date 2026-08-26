from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, String
from sqlmodel import Field, SQLModel

from api.v1.auth.context import get_current_owner_id
from utils.datetime_utils import get_current_utc_datetime


class AssetGenerationTrace(SQLModel, table=True):
    __tablename__ = "asset_generation_traces"

    request_id: str = Field(primary_key=True)
    owner_id: Optional[uuid.UUID] = Field(
        default_factory=get_current_owner_id,
        exclude=True,
        sa_column=Column(
            ForeignKey("user.id", ondelete="CASCADE"), nullable=True, index=True
        ),
    )
    presentation_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            ForeignKey("presentations.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
    )
    generation_mode: str = Field(sa_column=Column(String(64), nullable=False))
    model: str = Field(sa_column=Column(String(255), nullable=False))
    output_count: int = 0
    consumer_slot_count: int = 0
    reused_consumer_slot_count: int = 0
    retry_of: Optional[str] = Field(default=None, nullable=True)
    status: str = Field(sa_column=Column(String(32), nullable=False))
    cost: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
    error: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            default=get_current_utc_datetime,
        )
    )
