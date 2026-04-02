"""Issue 23 identity substrate

Revision ID: 4c8660e9e4d1
Revises: 1571dcf87c69
Create Date: 2026-04-02 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4c8660e9e4d1"
down_revision: Union[str, Sequence[str], None] = "1571dcf87c69"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


UUID_TEXT_PATTERN = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def _normalize_roles(connection: sa.Connection) -> None:
    """Normalize legacy role values before adding new auth-layer tables."""
    connection.execute(
        sa.text(
            """
            UPDATE users
            SET role = CASE
                WHEN lower(trim(role)) = 'teacher' THEN 'teacher'
                WHEN lower(trim(role)) = 'student' THEN 'student'
                WHEN replace(lower(trim(role)), ' ', '') IN ('universityadmin', 'university_admin')
                    THEN 'university_admin'
                ELSE role
            END
            """
        )
    )

    unexpected_roles = connection.execute(
        sa.text(
            """
            SELECT DISTINCT role
            FROM users
            WHERE role NOT IN ('teacher', 'student', 'university_admin')
            ORDER BY role
            """
        )
    ).scalars().all()
    if unexpected_roles:
        raise RuntimeError(
            "Issue #23 cannot continue with unmapped legacy roles. "
            f"Reset/reseed local data or map these roles first: {unexpected_roles}"
        )


def _validate_legacy_bridge_ids(connection: sa.Connection) -> None:
    """Fail fast if legacy ids are not compatible with the auth bridge contract."""
    invalid_ids = connection.execute(
        sa.text(
            """
            SELECT id
            FROM users
            WHERE id IS NOT NULL
              AND id !~* :uuid_pattern
            ORDER BY id
            LIMIT 5
            """
        ),
        {"uuid_pattern": UUID_TEXT_PATTERN},
    ).scalars().all()
    if invalid_ids:
        raise RuntimeError(
            "Issue #23 assumes reset/reseed of pre-auth local data. "
            "Found legacy users.id values that are not auth-compatible UUID text: "
            f"{invalid_ids}. Reset the local database and reseed with UUID ids before retrying."
        )


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind()
    _normalize_roles(connection)
    _validate_legacy_bridge_ids(connection)
    op.create_check_constraint("ck_users_id_auth_uuid", "users", f"id ~* '{UUID_TEXT_PATTERN}'")
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('teacher', 'student', 'university_admin')",
    )

    op.create_table(
        "profiles",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "memberships",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("university_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("must_rotate_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('teacher', 'student', 'university_admin')", name="ck_memberships_role"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_memberships_status"),
        sa.ForeignKeyConstraint(["university_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "university_id", "role", name="uix_membership_user_university_role"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"], unique=False)
    op.create_index("ix_memberships_university_id", "memberships", ["university_id"], unique=False)

    op.create_table(
        "allowed_email_domains",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("university_id", sa.String(length=36), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["university_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("university_id", "domain", name="uix_allowed_email_domain"),
    )
    op.create_index("ix_allowed_email_domains_university_id", "allowed_email_domains", ["university_id"], unique=False)

    op.create_table(
        "university_sso_configs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("university_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("azure_tenant_id", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("provider IN ('azure')", name="ck_university_sso_provider"),
        sa.ForeignKeyConstraint(["university_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("university_id", "provider", name="uix_university_sso_config"),
    )

    op.create_table(
        "courses",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("university_id", sa.String(length=36), nullable=False),
        sa.Column("teacher_membership_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["teacher_membership_id"], ["memberships.id"]),
        sa.ForeignKeyConstraint(["university_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "invites",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("university_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('teacher', 'student')", name="ck_invites_role"),
        sa.CheckConstraint("status IN ('pending', 'consumed', 'expired', 'revoked')", name="ck_invites_status"),
        sa.CheckConstraint("role <> 'student' OR course_id IS NOT NULL", name="ck_invites_student_requires_course"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["university_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )

    op.create_table(
        "course_memberships",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("course_id", sa.Text(), nullable=False),
        sa.Column("membership_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_id", "membership_id", name="uix_course_membership"),
    )
    op.create_index("ix_course_memberships_course_id", "course_memberships", ["course_id"], unique=False)
    op.create_index("ix_course_memberships_membership_id", "course_memberships", ["membership_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_constraint("ck_users_id_auth_uuid", "users", type_="check")
    op.drop_index("ix_course_memberships_membership_id", table_name="course_memberships")
    op.drop_index("ix_course_memberships_course_id", table_name="course_memberships")
    op.drop_table("course_memberships")
    op.drop_table("invites")
    op.drop_table("courses")
    op.drop_table("university_sso_configs")
    op.drop_index("ix_allowed_email_domains_university_id", table_name="allowed_email_domains")
    op.drop_table("allowed_email_domains")
    op.drop_index("ix_memberships_university_id", table_name="memberships")
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("profiles")
