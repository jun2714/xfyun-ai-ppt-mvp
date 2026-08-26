"""add ppt library items

Revision ID: a9c1e3f5b7d9
Revises: c6e8a0b3d5f7
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a9c1e3f5b7d9"
down_revision: str | None = "c6e8a0b3d5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ppt_library_items" in inspector.get_table_names():
        return
    op.create_table(
        "ppt_library_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("age_group", sa.String(length=32), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("thumbnail", sa.Text(), nullable=True),
        sa.Column("pptx_path", sa.Text(), nullable=False),
        sa.Column("layouts", sa.JSON(), nullable=True),
        sa.Column("raw_layouts", sa.JSON(), nullable=True),
        sa.Column("assets", sa.JSON(), nullable=True),
        sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ppt_library_items_category", "ppt_library_items", ["category"])
    op.create_index("ix_ppt_library_items_age_group", "ppt_library_items", ["age_group"])
    op.create_index("ix_ppt_library_items_created_by", "ppt_library_items", ["created_by"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ppt_library_items" not in inspector.get_table_names():
        return
    op.drop_index("ix_ppt_library_items_created_by", table_name="ppt_library_items")
    op.drop_index("ix_ppt_library_items_age_group", table_name="ppt_library_items")
    op.drop_index("ix_ppt_library_items_category", table_name="ppt_library_items")
    op.drop_table("ppt_library_items")
