"""Issue 180 assignment target-course links

Revision ID: b7c8d9e0f1a2
Revises: f2a3b4c5d6e7
Create Date: 2026-04-22 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "assignment_courses",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("assignment_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"]),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("assignment_id", "course_id", name="uix_assignment_course"),
    )
    op.create_index(
        "ix_assignment_courses_assignment_id",
        "assignment_courses",
        ["assignment_id"],
        unique=False,
    )
    op.create_index(
        "ix_assignment_courses_course_id",
        "assignment_courses",
        ["course_id"],
        unique=False,
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO assignment_courses (id, assignment_id, course_id, created_at)
            SELECT assignments.id || ':' || assignments.course_id,
                   assignments.id,
                   assignments.course_id,
                   COALESCE(assignments.created_at, NOW())
            FROM assignments
            WHERE assignments.course_id IS NOT NULL
            ON CONFLICT (assignment_id, course_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_assignment_courses_course_id", table_name="assignment_courses")
    op.drop_index("ix_assignment_courses_assignment_id", table_name="assignment_courses")
    op.drop_table("assignment_courses")