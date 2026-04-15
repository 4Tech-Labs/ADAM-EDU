"""issue112_stateful_recovery_phase1

Revision ID: a6fd55f56fbc
Revises: d4f4c2f9c1aa
Create Date: 2026-04-14 21:09:27.685935

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a6fd55f56fbc'
down_revision: Union[str, Sequence[str], None] = 'd4f4c2f9c1aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "checkpoint_migrations",
        sa.Column("v", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("v"),
    )

    op.create_table(
        "checkpoints",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("parent_checkpoint_id", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("checkpoint", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id"),
    )

    op.create_table(
        "checkpoint_blobs",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("blob", postgresql.BYTEA(), nullable=True),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "channel", "version"),
    )

    op.create_table(
        "checkpoint_writes",
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("checkpoint_ns", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("checkpoint_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=True),
        sa.Column("blob", postgresql.BYTEA(), nullable=False),
        sa.Column("task_path", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.PrimaryKeyConstraint("thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx"),
    )

    op.create_index("ix_checkpoints_thread_id", "checkpoints", ["thread_id"], unique=False)
    op.create_index("ix_checkpoint_blobs_thread_id", "checkpoint_blobs", ["thread_id"], unique=False)
    op.create_index("ix_checkpoint_writes_thread_id", "checkpoint_writes", ["thread_id"], unique=False)

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_check_constraints = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints("authoring_jobs")
    }
    if "ck_authoring_jobs_status" not in existing_check_constraints:
        op.create_check_constraint(
            "ck_authoring_jobs_status",
            "authoring_jobs",
            "status IN ('pending', 'processing', 'completed', 'failed', 'failed_resumable')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_check_constraints = {
        constraint.get("name")
        for constraint in inspector.get_check_constraints("authoring_jobs")
    }
    if "ck_authoring_jobs_status" in existing_check_constraints:
        op.drop_constraint("ck_authoring_jobs_status", "authoring_jobs", type_="check")

    op.drop_index("ix_checkpoint_writes_thread_id", table_name="checkpoint_writes")
    op.drop_index("ix_checkpoint_blobs_thread_id", table_name="checkpoint_blobs")
    op.drop_index("ix_checkpoints_thread_id", table_name="checkpoints")

    op.drop_table("checkpoint_writes")
    op.drop_table("checkpoint_blobs")
    op.drop_table("checkpoints")
    op.drop_table("checkpoint_migrations")
