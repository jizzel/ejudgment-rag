"""Chunks with generated full-text vectors, and the search audit table (M2 slice 1).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08 18:33:55.364625
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "query_audit",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("endpoint", sa.String(length=64), nullable=False),
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=True),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result_judgment_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_query_audit")),
    )
    op.create_index("ix_query_audit_created_at", "query_audit", ["created_at"], unique=False)
    op.create_table(
        "chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("judgment_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("section_label", sa.Text(), nullable=True),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("page_reference_status", sa.String(length=16), nullable=False),
        sa.Column("paragraph_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("chunker_version", sa.String(length=128), nullable=False),
        sa.Column("source_text_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "textsearch_en",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "textsearch_simple",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', content)", persisted=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(page_reference_status = 'verified') = "
            "(page_start IS NOT NULL AND page_end IS NOT NULL)",
            name=op.f("ck_chunks_page_bounds_only_when_verified"),
        ),
        sa.CheckConstraint(
            "page_reference_status IN ('verified', 'unknown', 'pending')",
            name=op.f("ck_chunks_page_reference_status"),
        ),
        sa.CheckConstraint("char_end > char_start", name=op.f("ck_chunks_char_span")),
        sa.ForeignKeyConstraint(
            ["judgment_id"],
            ["judgments.id"],
            name=op.f("fk_chunks_judgment_id_judgments"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["document_sources.id"],
            name=op.f("fk_chunks_source_id_document_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint("judgment_id", "ordinal", name=op.f("uq_chunks_judgment_id_ordinal")),
    )
    op.create_index("ix_chunks_content_hash", "chunks", ["content_hash"], unique=False)
    op.create_index("ix_chunks_source_text_hash", "chunks", ["source_text_hash"], unique=False)
    op.create_index(
        "ix_chunks_textsearch_en", "chunks", ["textsearch_en"], unique=False, postgresql_using="gin"
    )
    op.create_index(
        "ix_chunks_textsearch_simple",
        "chunks",
        ["textsearch_simple"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_textsearch_simple", table_name="chunks", postgresql_using="gin")
    op.drop_index("ix_chunks_textsearch_en", table_name="chunks", postgresql_using="gin")
    op.drop_index("ix_chunks_source_text_hash", table_name="chunks")
    op.drop_index("ix_chunks_content_hash", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("ix_query_audit_created_at", table_name="query_audit")
    op.drop_table("query_audit")
