"""Context hash on chunk_embeddings: the judgment metadata each vector was built from.

Existing rows start NULL and are excluded from dense search until ``worker.embed`` runs;
it backfills the hash for vectors whose input is still current, without re-embedding.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-08 21:25:50.838896
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "chunk_embeddings", sa.Column("context_hash", sa.String(length=32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chunk_embeddings", "context_hash")
