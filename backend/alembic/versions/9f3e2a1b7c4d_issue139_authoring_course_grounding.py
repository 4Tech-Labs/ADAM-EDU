"""Issue 139 authoring course grounding

Revision ID: 9f3e2a1b7c4d
Revises: e1b3c4d5f6a7
Create Date: 2026-04-20 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f3e2a1b7c4d"
down_revision: Union[str, Sequence[str], None] = "e1b3c4d5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assignments", sa.Column("course_id", sa.Text(), nullable=True))
    op.create_index("ix_assignments_course_id", "assignments", ["course_id"], unique=False)
    op.create_foreign_key(
        "fk_assignments_course_id_courses",
        "assignments",
        "courses",
        ["course_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_assignments_course_id_courses", "assignments", type_="foreignkey")
    op.drop_index("ix_assignments_course_id", table_name="assignments")
    op.drop_column("assignments", "course_id")