"""Issue 90 assignment deadline

Revision ID: d4f4c2f9c1aa
Revises: c2f8a58d6d1e
Create Date: 2026-04-12 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4f4c2f9c1aa"
down_revision: Union[str, Sequence[str], None] = "c2f8a58d6d1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_assignments_teacher_id_deadline",
        "assignments",
        ["teacher_id", "deadline"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_assignments_teacher_id_deadline", table_name="assignments")
    op.drop_column("assignments", "deadline")
