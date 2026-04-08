"""Issue 52 admin catalog infra

Revision ID: a6f6d7ac9c2b
Revises: 4c8660e9e4d1
Create Date: 2026-04-08 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a6f6d7ac9c2b"
down_revision: Union[str, Sequence[str], None] = "4c8660e9e4d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _backfill_legacy_courses(connection: sa.Connection) -> None:
    connection.execute(
        sa.text(
            """
            UPDATE courses
            SET
                code = 'LEGACY-' || upper(substr(replace(id, '-', ''), 1, 8)),
                semester = concat(
                    extract(year from timezone('UTC', created_at))::int,
                    '-',
                    CASE
                        WHEN extract(month from timezone('UTC', created_at))::int <= 6 THEN 'I'
                        ELSE 'II'
                    END
                ),
                academic_level = 'Pregrado',
                max_students = 30,
                status = 'active',
                pending_teacher_invite_id = NULL
            WHERE code IS NULL
               OR semester IS NULL
               OR academic_level IS NULL
               OR max_students IS NULL
               OR status IS NULL
            """
        )
    )


def upgrade() -> None:
    connection = op.get_bind()

    op.add_column("courses", sa.Column("code", sa.Text(), nullable=True))
    op.add_column("courses", sa.Column("semester", sa.Text(), nullable=True))
    op.add_column("courses", sa.Column("academic_level", sa.Text(), nullable=True))
    op.add_column("courses", sa.Column("max_students", sa.Integer(), nullable=True))
    op.add_column("courses", sa.Column("status", sa.Text(), nullable=True))
    op.add_column("courses", sa.Column("pending_teacher_invite_id", sa.Text(), nullable=True))
    op.alter_column("courses", "teacher_membership_id", existing_type=sa.Text(), nullable=True)

    op.add_column("invites", sa.Column("full_name", sa.Text(), nullable=True))

    op.create_table(
        "course_access_links",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('active', 'rotated', 'revoked')", name="ck_course_access_links_status"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_course_access_links_course_id", "course_access_links", ["course_id"], unique=False)
    op.create_index(
        "uix_course_access_links_active_course",
        "course_access_links",
        ["course_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    _backfill_legacy_courses(connection)

    op.create_foreign_key(
        "fk_courses_pending_teacher_invite_id_invites",
        "courses",
        "invites",
        ["pending_teacher_invite_id"],
        ["id"],
    )

    op.alter_column("courses", "code", existing_type=sa.Text(), nullable=False)
    op.alter_column("courses", "semester", existing_type=sa.Text(), nullable=False)
    op.alter_column("courses", "academic_level", existing_type=sa.Text(), nullable=False)
    op.alter_column("courses", "max_students", existing_type=sa.Integer(), nullable=False)
    op.alter_column("courses", "status", existing_type=sa.Text(), nullable=False)

    op.create_check_constraint("ck_courses_status", "courses", "status IN ('active', 'inactive')")
    op.create_check_constraint("ck_courses_max_students_positive", "courses", "max_students > 0")
    op.create_check_constraint(
        "ck_courses_academic_level",
        "courses",
        "academic_level IN ('Pregrado', 'Especialización', 'Maestría', 'MBA', 'Doctorado')",
    )
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
    op.create_unique_constraint(
        "uix_courses_university_code_semester",
        "courses",
        ["university_id", "code", "semester"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    pending_teacher_courses = connection.execute(
        sa.text(
            """
            SELECT id
            FROM courses
            WHERE teacher_membership_id IS NULL
               OR pending_teacher_invite_id IS NOT NULL
            ORDER BY id
            LIMIT 5
            """
        )
    ).scalars().all()
    if pending_teacher_courses:
        raise RuntimeError(
            "Issue 52 downgrade cannot preserve courses that only exist in the new pending-teacher shape. "
            f"Resolve or delete these rows before downgrade: {pending_teacher_courses}"
        )

    op.drop_constraint("uix_courses_university_code_semester", "courses", type_="unique")
    op.drop_constraint("ck_courses_teacher_assignment_xor", "courses", type_="check")
    op.drop_constraint("ck_courses_academic_level", "courses", type_="check")
    op.drop_constraint("ck_courses_max_students_positive", "courses", type_="check")
    op.drop_constraint("ck_courses_status", "courses", type_="check")
    op.drop_constraint("fk_courses_pending_teacher_invite_id_invites", "courses", type_="foreignkey")

    op.drop_index("uix_course_access_links_active_course", table_name="course_access_links")
    op.drop_index("ix_course_access_links_course_id", table_name="course_access_links")
    op.drop_table("course_access_links")

    op.drop_column("invites", "full_name")

    op.alter_column("courses", "teacher_membership_id", existing_type=sa.Text(), nullable=False)
    op.drop_column("courses", "pending_teacher_invite_id")
    op.drop_column("courses", "status")
    op.drop_column("courses", "max_students")
    op.drop_column("courses", "academic_level")
    op.drop_column("courses", "semester")
    op.drop_column("courses", "code")
