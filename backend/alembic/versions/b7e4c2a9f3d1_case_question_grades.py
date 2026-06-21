"""case_question_grades

Per-question manual grades for student case submissions. Mirrors the case_grades
table conventions (column types, RLS deny_all) and adds an owner-bypass assertion so
a non-owner deploy fails loudly at migrate time instead of silently at first write
(case_question_grades uses ENABLE — not FORCE — RLS, so writes depend on the app role
owning the table).

Revision ID: b7e4c2a9f3d1
Revises: 9ee3b0659e9a
Create Date: 2026-06-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7e4c2a9f3d1'
down_revision: Union[str, Sequence[str], None] = '9ee3b0659e9a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'case_question_grades',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('membership_id', sa.Text(), nullable=False),
        sa.Column('assignment_id', sa.String(length=36), nullable=False),
        sa.Column('course_id', sa.Text(), nullable=False),
        sa.Column('question_id', sa.String(length=64), nullable=False),
        sa.Column('points_awarded', sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column(
            'max_points',
            sa.Numeric(precision=6, scale=2),
            server_default=sa.text('10.00'),
            nullable=False,
        ),
        sa.Column('feedback', sa.Text(), nullable=True),
        sa.Column('graded_by_membership_id', sa.Text(), nullable=True),
        sa.Column('graded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            'points_awarded >= 0 AND points_awarded <= max_points',
            name='ck_case_question_grades_points_range',
        ),
        sa.CheckConstraint('max_points > 0', name='ck_case_question_grades_max_points_positive'),
        sa.ForeignKeyConstraint(['assignment_id'], ['assignments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['graded_by_membership_id'], ['memberships.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['membership_id'], ['memberships.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'membership_id',
            'assignment_id',
            'question_id',
            name='uix_case_question_grades_membership_assignment_question',
        ),
    )
    op.create_index(
        'ix_case_question_grades_assignment_membership',
        'case_question_grades',
        ['assignment_id', 'membership_id'],
        unique=False,
    )
    op.create_index(
        'ix_case_question_grades_course_assignment',
        'case_question_grades',
        ['course_id', 'assignment_id'],
        unique=False,
    )
    # RLS parity with case_grades: ENABLE (not FORCE) + deny_all. The app role owns the
    # table and therefore bypasses the policy; deny_all only blocks Supabase anon/authenticated.
    op.execute("ALTER TABLE case_question_grades ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS case_question_grades_deny_all ON case_question_grades")
    op.execute(
        """
        CREATE POLICY case_question_grades_deny_all ON case_question_grades
          FOR ALL
          USING (false)
          WITH CHECK (false)
        """
    )
    # H12: fail loudly if the migration role is not the table owner, because the
    # owner-bypass that lets the backend write through ENABLE-RLS would not hold.
    op.execute(
        """
        DO $$
        DECLARE
          tbl_owner text;
        BEGIN
          SELECT pg_get_userbyid(c.relowner) INTO tbl_owner
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          WHERE c.relname = 'case_question_grades' AND n.nspname = 'public';
          IF tbl_owner IS DISTINCT FROM current_user THEN
            RAISE EXCEPTION
              'case_question_grades owner % != runtime role %; non-FORCED RLS owner-bypass will not hold for grade writes',
              tbl_owner, current_user;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS case_question_grades_deny_all ON case_question_grades")
    op.drop_index('ix_case_question_grades_course_assignment', table_name='case_question_grades')
    op.drop_index('ix_case_question_grades_assignment_membership', table_name='case_question_grades')
    op.drop_table('case_question_grades')
