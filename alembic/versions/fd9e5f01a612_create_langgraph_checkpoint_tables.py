"""create langgraph checkpoint tables

Revision ID: fd9e5f01a612
Revises: d57dd2a1f838
Create Date: 2026-10-07 13:18:17.689745

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fd9e5f01a612'
down_revision: Union[str, Sequence[str], None] = 'd57dd2a1f838'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Copia de AsyncPostgresSaver.MIGRATIONS de langgraph-checkpoint-postgres 3.1.2 (fijado en uv.lock). Se copia en vez de
# importarla para que esta migración no cambie al actualizar la librería; una versión con migraciones nuevas exige otra
# migración de Alembic. CREATE INDEX va sin CONCURRENTLY porque Alembic migra dentro de una transacción y las tablas
# se acaban de crear vacías.
CHECKPOINT_MIGRATIONS = [
    """CREATE TABLE IF NOT EXISTS checkpoint_migrations (
    v INTEGER PRIMARY KEY
)""",
    """CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
)""",
    """CREATE TABLE IF NOT EXISTS checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
)""",
    """CREATE TABLE IF NOT EXISTS checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
)""",
    "ALTER TABLE checkpoint_blobs ALTER COLUMN blob DROP not null",
    "SELECT 1",
    "CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints(thread_id)",
    "CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx ON checkpoint_blobs(thread_id)",
    "CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx ON checkpoint_writes(thread_id)",
    "ALTER TABLE checkpoint_writes ADD COLUMN IF NOT EXISTS task_path TEXT NOT NULL DEFAULT ''",
]


def upgrade() -> None:
    """Upgrade schema."""
    for version, statement in enumerate(CHECKPOINT_MIGRATIONS):
        op.execute(statement)
        # Registrar la versión hace que AsyncPostgresSaver.setup() no tenga nada que aplicar.
        op.execute(sa.text("INSERT INTO checkpoint_migrations (v) VALUES (:v)").bindparams(v=version))


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TABLE checkpoint_writes, checkpoint_blobs, checkpoints, checkpoint_migrations")
