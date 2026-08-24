"""add ppt library season and scene

Revision ID: c2d4e6f8a0b1
Revises: b1c3d5e7f9a2
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c2d4e6f8a0b1"
down_revision: str | None = "b1c3d5e7f9a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ppt_library_items" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("ppt_library_items")}
    if "season" not in columns:
        op.add_column(
            "ppt_library_items",
            sa.Column("season", sa.String(length=16), nullable=False, server_default="不限"),
        )
        op.create_index("ix_ppt_library_items_season", "ppt_library_items", ["season"])
    if "scene" not in columns:
        op.add_column(
            "ppt_library_items",
            sa.Column("scene", sa.String(length=16), nullable=False, server_default="其他"),
        )
        op.create_index("ix_ppt_library_items_scene", "ppt_library_items", ["scene"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ppt_library_items" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("ppt_library_items")}
    if "scene" in columns:
        op.drop_index("ix_ppt_library_items_scene", table_name="ppt_library_items")
        op.drop_column("ppt_library_items", "scene")
    if "season" in columns:
        op.drop_index("ix_ppt_library_items_season", table_name="ppt_library_items")
        op.drop_column("ppt_library_items", "season")
