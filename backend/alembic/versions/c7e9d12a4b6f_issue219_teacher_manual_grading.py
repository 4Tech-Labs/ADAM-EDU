"""issue219_teacher_manual_grading

Revision ID: c7e9d12a4b6f
Revises: 9ee3b0659e9a
Create Date: 2026-04-27 23:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c7e9d12a4b6f"
down_revision: Union[str, Sequence[str], None] = "9ee3b0659e9a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "assignments",
        sa.Column("weight_per_module", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.add_column(
        "case_grades",
        sa.Column("graded_by", sa.String(length=16), server_default=sa.text("'human'"), nullable=False),
    )
    op.add_column("case_grades", sa.Column("ai_model_version", sa.String(length=64), nullable=True))
    op.add_column("case_grades", sa.Column("ai_suggested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("case_grades", sa.Column("human_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "case_grades",
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column("case_grades", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("case_grades", sa.Column("draft_feedback_global", sa.Text(), nullable=True))
    op.add_column(
        "case_grades",
        sa.Column(
            "last_modified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_case_grades_graded_by",
        "case_grades",
        "graded_by IN ('human', 'ai', 'hybrid')",
    )
    op.create_check_constraint(
        "ck_case_grades_version_positive",
        "case_grades",
        "version >= 1",
    )

    op.create_table(
        "case_grade_module_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_grade_id", sa.String(length=36), nullable=False),
        sa.Column("module_id", sa.String(length=2), nullable=False),
        sa.Column("weight", sa.Numeric(precision=4, scale=3), server_default=sa.text("0.200"), nullable=False),
        sa.Column("feedback_module", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("source", sa.String(length=24), server_default=sa.text("'human'"), nullable=False),
        sa.Column("ai_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("module_id IN ('M1', 'M2', 'M3', 'M4', 'M5')", name="ck_case_grade_module_entries_module_id"),
        sa.CheckConstraint("weight >= 0 AND weight <= 1", name="ck_case_grade_module_entries_weight_range"),
        sa.CheckConstraint("state IN ('draft', 'published')", name="ck_case_grade_module_entries_state"),
        sa.CheckConstraint(
            "source IN ('human', 'ai_suggested', 'ai_edited_by_human')",
            name="ck_case_grade_module_entries_source",
        ),
        sa.CheckConstraint(
            "ai_confidence IS NULL OR (ai_confidence >= 0 AND ai_confidence <= 1)",
            name="ck_case_grade_module_entries_ai_confidence_range",
        ),
        sa.ForeignKeyConstraint(["case_grade_id"], ["case_grades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_grade_id",
            "module_id",
            "state",
            name="uix_case_grade_module_entries_case_grade_module_state",
        ),
    )
    op.create_index(
        "ix_case_grade_module_entries_case_grade_id",
        "case_grade_module_entries",
        ["case_grade_id"],
        unique=False,
    )

    op.create_table(
        "case_grade_question_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_grade_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=64), nullable=False),
        sa.Column("module_id", sa.String(length=2), nullable=False),
        sa.Column("rubric_level", sa.String(length=16), nullable=True),
        sa.Column("score_normalized", sa.Float(), nullable=True),
        sa.Column("feedback_question", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=16), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("source", sa.String(length=24), server_default=sa.text("'human'"), nullable=False),
        sa.Column("ai_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("module_id IN ('M1', 'M2', 'M3', 'M4', 'M5')", name="ck_case_grade_question_entries_module_id"),
        sa.CheckConstraint(
            "rubric_level IS NULL OR rubric_level IN ('excelente', 'bien', 'aceptable', 'insuficiente', 'no_responde')",
            name="ck_case_grade_question_entries_rubric_level",
        ),
        sa.CheckConstraint(
            "score_normalized IS NULL OR (score_normalized >= 0 AND score_normalized <= 1)",
            name="ck_case_grade_question_entries_score_normalized_range",
        ),
        sa.CheckConstraint("state IN ('draft', 'published')", name="ck_case_grade_question_entries_state"),
        sa.CheckConstraint(
            "source IN ('human', 'ai_suggested', 'ai_edited_by_human')",
            name="ck_case_grade_question_entries_source",
        ),
        sa.CheckConstraint(
            "ai_confidence IS NULL OR (ai_confidence >= 0 AND ai_confidence <= 1)",
            name="ck_case_grade_question_entries_ai_confidence_range",
        ),
        sa.ForeignKeyConstraint(["case_grade_id"], ["case_grades.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_grade_id",
            "question_id",
            "state",
            name="uix_case_grade_question_entries_case_grade_question_state",
        ),
    )
    op.create_index(
        "ix_case_grade_question_entries_case_grade_module",
        "case_grade_question_entries",
        ["case_grade_id", "module_id"],
        unique=False,
    )

    op.execute("ALTER TABLE case_grade_module_entries ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS case_grade_module_entries_deny_all ON case_grade_module_entries")
    op.execute(
        """
        CREATE POLICY case_grade_module_entries_deny_all ON case_grade_module_entries
          FOR ALL
          USING (false)
          WITH CHECK (false)
        """
    )

    op.execute("ALTER TABLE case_grade_question_entries ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS case_grade_question_entries_deny_all ON case_grade_question_entries")
    op.execute(
        """
        CREATE POLICY case_grade_question_entries_deny_all ON case_grade_question_entries
          FOR ALL
          USING (false)
          WITH CHECK (false)
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS case_grade_question_entries_deny_all ON case_grade_question_entries")
    op.execute("DROP POLICY IF EXISTS case_grade_module_entries_deny_all ON case_grade_module_entries")
    op.drop_index("ix_case_grade_question_entries_case_grade_module", table_name="case_grade_question_entries")
    op.drop_table("case_grade_question_entries")
    op.drop_index("ix_case_grade_module_entries_case_grade_id", table_name="case_grade_module_entries")
    op.drop_table("case_grade_module_entries")

    op.drop_constraint("ck_case_grades_version_positive", "case_grades", type_="check")
    op.drop_constraint("ck_case_grades_graded_by", "case_grades", type_="check")
    op.drop_column("case_grades", "last_modified_at")
    op.drop_column("case_grades", "published_at")
    op.drop_column("case_grades", "version")
    op.drop_column("case_grades", "human_reviewed_at")
    op.drop_column("case_grades", "ai_suggested_at")
    op.drop_column("case_grades", "ai_model_version")
    op.drop_column("case_grades", "draft_feedback_global")
    op.drop_column("case_grades", "graded_by")

    op.drop_column("assignments", "weight_per_module")