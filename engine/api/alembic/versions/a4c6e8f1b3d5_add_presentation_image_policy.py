"""add presentation image policy

Revision ID: a4c6e8f1b3d5
Revises: f3a7c1d9e5b2
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a4c6e8f1b3d5"
down_revision: str | None = "f3a7c1d9e5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "image_policy" not in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "image_policy",
                    sa.String(32),
                    nullable=False,
                    server_default="standard",
                )
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "presentations" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("presentations")}
    if "image_policy" in columns:
        with op.batch_alter_table("presentations") as batch_op:
            batch_op.drop_column("image_policy")
