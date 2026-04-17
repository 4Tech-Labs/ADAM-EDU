"""Issue 118 checkpoint migrations alignment

Revision ID: 97a740b07c66
Revises: a6fd55f56fbc
Create Date: 2026-04-17 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "97a740b07c66"
down_revision: Union[str, Sequence[str], None] = "a6fd55f56fbc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Align Alembic-managed checkpoint schema with LangGraph expectations."""
    op.execute("DROP INDEX IF EXISTS ix_checkpoints_thread_id")
    op.execute("DROP INDEX IF EXISTS ix_checkpoint_blobs_thread_id")
    op.execute("DROP INDEX IF EXISTS ix_checkpoint_writes_thread_id")

    op.execute(
        "CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints(thread_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx ON checkpoint_blobs(thread_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx ON checkpoint_writes(thread_id)"
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO checkpoint_migrations (v) VALUES "
            "(0), (1), (2), (3), (4), (5), (6), (7), (8), (9) "
            "ON CONFLICT DO NOTHING"
        )
    )


def downgrade() -> None:
    """Restore the pre-issue118 checkpoint index names and empty ledger."""
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM checkpoint_migrations WHERE v >= 0"))

    op.execute("DROP INDEX IF EXISTS checkpoint_writes_thread_id_idx")
    op.execute("DROP INDEX IF EXISTS checkpoint_blobs_thread_id_idx")
    op.execute("DROP INDEX IF EXISTS checkpoints_thread_id_idx")

    op.execute("CREATE INDEX IF NOT EXISTS ix_checkpoints_thread_id ON checkpoints(thread_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_checkpoint_blobs_thread_id ON checkpoint_blobs(thread_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_checkpoint_writes_thread_id ON checkpoint_writes(thread_id)"
    )