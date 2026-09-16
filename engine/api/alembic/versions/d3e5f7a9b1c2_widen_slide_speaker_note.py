"""widen slide speaker notes to text

Revision ID: d3e5f7a9b1c2
Revises: c2d4e6f8a0b1
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d3e5f7a9b1c2"
down_revision: str | None = "c2d4e6f8a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "slides" not in inspector.get_table_names():
        return
    dialect = op.get_bind().dialect.name
    if dialect == "mysql":
        op.execute("ALTER TABLE slides MODIFY speaker_note TEXT")
        return
    if dialect == "postgresql":
        op.alter_column(
            "slides",
            "speaker_note",
            existing_type=sa.String(),
            type_=sa.Text(),
            existing_nullable=True,
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "slides" not in inspector.get_table_names():
        return
    dialect = op.get_bind().dialect.name
    if dialect == "mysql":
        op.execute("ALTER TABLE slides MODIFY speaker_note VARCHAR(255)")
        return
    if dialect == "postgresql":
        op.alter_column(
            "slides",
            "speaker_note",
            existing_type=sa.Text(),
            type_=sa.String(),
            existing_nullable=True,
        )
