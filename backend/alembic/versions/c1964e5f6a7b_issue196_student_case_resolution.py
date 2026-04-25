"""Issue 196 student case resolution persistence

Revision ID: c1964e5f6a7b
Revises: b7c8d9e0f1a2
Create Date: 2026-04-24 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c1964e5f6a7b"
down_revision: Union[str, Sequence[str], None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "student_case_responses",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("membership_id", sa.Text(), nullable=False),
        sa.Column("assignment_id", sa.String(length=36), nullable=False),
        sa.Column(
            "answers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("first_opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_autosaved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("TIMEZONE('utc', NOW())"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("TIMEZONE('utc', NOW())"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted')",
            name="ck_student_case_responses_status",
        ),
        sa.CheckConstraint("version >= 0", name="ck_student_case_responses_version_nonnegative"),
        sa.ForeignKeyConstraint(["assignment_id"], ["assignments.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "membership_id",
            "assignment_id",
            name="uix_student_case_response_membership_assignment",
        ),
    )
    op.create_index(
        "ix_student_case_responses_assignment_id",
        "student_case_responses",
        ["assignment_id"],
        unique=False,
    )

    op.create_table(
        "student_case_response_submissions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("response_id", sa.Text(), nullable=False),
        sa.Column(
            "answers_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canonical_output_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("TIMEZONE('utc', NOW())"),
        ),
        sa.ForeignKeyConstraint(
            ["response_id"],
            ["student_case_responses.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_student_case_response_submissions_response_id",
        "student_case_response_submissions",
        ["response_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_student_case_response_submissions_response_id",
        table_name="student_case_response_submissions",
    )
    op.drop_table("student_case_response_submissions")

    op.drop_index(
        "ix_student_case_responses_assignment_id",
        table_name="student_case_responses",
    )
    op.drop_table("student_case_responses")