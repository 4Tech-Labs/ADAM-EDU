"""Issue 137 teacher syllabuses and revisions

Revision ID: e1b3c4d5f6a7
Revises: 97a740b07c66
Create Date: 2026-04-19 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e1b3c4d5f6a7"
down_revision: Union[str, Sequence[str], None] = "97a740b07c66"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "syllabuses",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("department", sa.Text(), nullable=False),
        sa.Column("knowledge_area", sa.Text(), nullable=False),
        sa.Column("nbc", sa.Text(), nullable=False),
        sa.Column("version_label", sa.Text(), nullable=False),
        sa.Column("academic_load", sa.Text(), nullable=False),
        sa.Column("course_description", sa.Text(), nullable=False),
        sa.Column("general_objective", sa.Text(), nullable=False),
        sa.Column("specific_objectives", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("modules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evaluation_strategy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("didactic_strategy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("integrative_project", sa.Text(), nullable=False),
        sa.Column("bibliography", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("teacher_notes", sa.Text(), nullable=False),
        sa.Column("ai_grounding_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("saved_by_membership_id", sa.Text(), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_syllabuses_revision_positive"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["saved_by_membership_id"], ["memberships.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", name="uix_syllabuses_course_id"),
    )

    op.create_table(
        "syllabus_revisions",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("syllabus_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("saved_by_membership_id", sa.Text(), nullable=False),
        sa.CheckConstraint("revision > 0", name="ck_syllabus_revisions_revision_positive"),
        sa.ForeignKeyConstraint(["saved_by_membership_id"], ["memberships.id"]),
        sa.ForeignKeyConstraint(["syllabus_id"], ["syllabuses.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_syllabus_revisions_syllabus_revision",
        "syllabus_revisions",
        ["syllabus_id", "revision"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_syllabus_revisions_syllabus_revision", table_name="syllabus_revisions")
    op.drop_table("syllabus_revisions")
    op.drop_table("syllabuses")