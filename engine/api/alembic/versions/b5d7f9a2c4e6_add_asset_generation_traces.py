"""add asset generation traces

Revision ID: b5d7f9a2c4e6
Revises: a4c6e8f1b3d5
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b5d7f9a2c4e6"
down_revision: str | None = "a4c6e8f1b3d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if "asset_generation_traces" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "asset_generation_traces",
        sa.Column("request_id", sa.String(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("presentation_id", sa.Uuid(), nullable=True),
        sa.Column("generation_mode", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("output_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("consumer_slot_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reused_consumer_slot_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_of", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["presentation_id"], ["presentations.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_asset_generation_traces_presentation_id",
        "asset_generation_traces",
        ["presentation_id"],
    )


def downgrade() -> None:
    if "asset_generation_traces" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("asset_generation_traces")
