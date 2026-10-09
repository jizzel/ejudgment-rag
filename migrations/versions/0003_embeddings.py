"""Embeddings (pgvector), model registry and evaluation runs (M2 slice 2).

The per-model HNSW index is an expression index on ``embedding::vector(384)`` limited to
the pinned bge-small revision; queries must cast and filter the same way to use it.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08 20:00:32.674323
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("per_question", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_runs")),
    )
    op.create_table(
        "model_registry",
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("revision", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=True),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('embedding', 'reranker')", name=op.f("ck_model_registry_kind")
        ),
        sa.PrimaryKeyConstraint("model_id", "revision", name=op.f("pk_model_registry")),
    )
    op.create_table(
        "chunk_embeddings",
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("model_revision", sa.String(length=64), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_input_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_template_version", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "vector_dims(embedding) = dimension", name=op.f("ck_chunk_embeddings_dimension_matches")
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["chunks.id"],
            name=op.f("fk_chunk_embeddings_chunk_id_chunks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "chunk_id", "model_id", "model_revision", name=op.f("pk_chunk_embeddings")
        ),
    )
    op.create_index(
        "ix_chunk_embeddings_model",
        "chunk_embeddings",
        ["model_id", "model_revision"],
        unique=False,
    )
    op.execute(
        "CREATE INDEX ix_chunk_embeddings_hnsw_bge_small_v15 ON chunk_embeddings "
        "USING hnsw ((embedding::vector(384)) vector_cosine_ops) "
        "WHERE model_id = 'BAAI/bge-small-en-v1.5' "
        "AND model_revision = '5c38ec7c405ec4b44b94cc5a9bb96e735b38267a'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chunk_embeddings_hnsw_bge_small_v15")
    op.drop_index("ix_chunk_embeddings_model", table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")
    op.drop_table("model_registry")
    op.drop_table("evaluation_runs")
    # The vector extension is left installed: other objects may depend on it.
