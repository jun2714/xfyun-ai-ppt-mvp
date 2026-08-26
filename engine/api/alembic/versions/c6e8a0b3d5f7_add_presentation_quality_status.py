"""add presentation quality status

Revision ID: c6e8a0b3d5f7
Revises: b5d7f9a2c4e6
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c6e8a0b3d5f7"
down_revision: str | None = "b5d7f9a2c4e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    with op.batch_alter_table("presentations") as batch_op:
        if "quality_status" not in columns:
            batch_op.add_column(
                sa.Column(
                    "quality_status",
                    sa.String(32),
                    nullable=False,
                    server_default="pending",
                )
            )
        if "quality_report" not in columns:
            batch_op.add_column(sa.Column("quality_report", sa.JSON(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    with op.batch_alter_table("presentations") as batch_op:
        if "quality_report" in columns:
            batch_op.drop_column("quality_report")
        if "quality_status" in columns:
            batch_op.drop_column("quality_status")
