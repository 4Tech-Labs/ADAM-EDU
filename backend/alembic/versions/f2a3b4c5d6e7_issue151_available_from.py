"""Issue 151 available_from column and composite index

Revision ID: f2a3b4c5d6e7
Revises: 9f3e2a1b7c4d
Create Date: 2026-04-20 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "9f3e2a1b7c4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("available_from", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_assignments_teacher_status_deadline",
        "assignments",
        ["teacher_id", "status", "deadline"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_assignments_teacher_status_deadline", table_name="assignments")
    op.drop_column("assignments", "available_from")
