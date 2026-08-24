"""add ppt library visibility

Revision ID: b1c3d5e7f9a2
Revises: a9c1e3f5b7d9
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b1c3d5e7f9a2"
down_revision: str | None = "a9c1e3f5b7d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ppt_library_items" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("ppt_library_items")}
    if "visibility" in columns:
        return
    op.add_column(
        "ppt_library_items",
        sa.Column(
            "visibility",
            sa.String(length=16),
            nullable=False,
            server_default="official",
        ),
    )
    op.create_index(
        "ix_ppt_library_items_visibility",
        "ppt_library_items",
        ["visibility"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ppt_library_items" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("ppt_library_items")}
    if "visibility" not in columns:
        return
    op.drop_index("ix_ppt_library_items_visibility", table_name="ppt_library_items")
    op.drop_column("ppt_library_items", "visibility")
