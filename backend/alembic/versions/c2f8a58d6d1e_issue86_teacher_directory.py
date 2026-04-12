"""Issue 86 teacher directory

Revision ID: c2f8a58d6d1e
Revises: a6f6d7ac9c2b
Create Date: 2026-04-11 23:30:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c2f8a58d6d1e"
down_revision: Union[str, Sequence[str], None] = "a6f6d7ac9c2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_courses_teacher_assignment_xor", "courses", type_="check")
    op.create_check_constraint(
        "ck_courses_teacher_assignment_xor",
        "courses",
        "NOT (teacher_membership_id IS NOT NULL AND pending_teacher_invite_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_courses_teacher_assignment_xor", "courses", type_="check")
    op.create_check_constraint(
        "ck_courses_teacher_assignment_xor",
        "courses",
        """
        (
            teacher_membership_id IS NOT NULL
            AND pending_teacher_invite_id IS NULL
        ) OR (
            teacher_membership_id IS NULL
            AND pending_teacher_invite_id IS NOT NULL
        )
        """,
    )
