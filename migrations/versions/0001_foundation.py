"""Foundation: judgments, sources, pages and ingestion bookkeeping (M1).

Revision ID: 0001
Revises:
Create Date: 2026-10-08 16:00:38.866577
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pg_trgm backs fuzzy citation lookup; pgvector arrives with the embeddings migration.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name=op.f("ck_ingestion_jobs_status")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_jobs")),
    )
    op.create_table(
        "judgments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("canonical_uri", sa.Text(), nullable=False),
        sa.Column("akn_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("citation", sa.Text(), nullable=False),
        sa.Column("citation_normalized", sa.Text(), nullable=False),
        sa.Column("neutral_citation", sa.Text(), nullable=True),
        sa.Column("case_number", sa.Text(), nullable=True),
        sa.Column("court_code", sa.String(length=64), nullable=True),
        sa.Column("court_name", sa.Text(), nullable=True),
        sa.Column("jurisdiction", sa.String(length=64), nullable=True),
        sa.Column("judgment_date", sa.Date(), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("judges", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("flynote", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_status", sa.String(length=32), nullable=False),
        sa.Column("eligibility_status", sa.String(length=32), nullable=False),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "eligibility_status IN ('eligible', 'quarantined')",
            name=op.f("ck_judgments_eligibility_status"),
        ),
        sa.CheckConstraint(
            "source_status IN ('text_available', 'ocr_pending', 'conversion_pending', 'no_source')",
            name=op.f("ck_judgments_source_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_judgments")),
        sa.UniqueConstraint("canonical_uri", name=op.f("uq_judgments_canonical_uri")),
    )
    op.create_index(
        "ix_judgments_citation_normalized_trgm",
        "judgments",
        ["citation_normalized"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"citation_normalized": "gin_trgm_ops"},
    )
    op.create_index("ix_judgments_court_code", "judgments", ["court_code"], unique=False)
    op.create_index("ix_judgments_judgment_date", "judgments", ["judgment_date"], unique=False)
    op.create_index("ix_judgments_jurisdiction", "judgments", ["jurisdiction"], unique=False)
    op.create_table(
        "document_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("judgment_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("rights_status", sa.String(length=32), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('html', 'pdf', 'legacy')", name=op.f("ck_document_sources_kind")
        ),
        sa.CheckConstraint(
            "rights_status IN ('cc_by_nc_local_export', 'licensed', 'unknown', 'prohibited')",
            name=op.f("ck_document_sources_rights_status"),
        ),
        sa.CheckConstraint(
            "verification_status IN "
            "('verified', 'unverified', 'mismatch', 'missing', 'not_applicable')",
            name=op.f("ck_document_sources_verification_status"),
        ),
        sa.ForeignKeyConstraint(
            ["judgment_id"],
            ["judgments.id"],
            name=op.f("fk_document_sources_judgment_id_judgments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_sources")),
        sa.UniqueConstraint(
            "judgment_id", "kind", name=op.f("uq_document_sources_judgment_id_kind")
        ),
    )
    op.create_table(
        "ingestion_issues",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("canonical_uri", sa.Text(), nullable=True),
        sa.Column("source_row_key", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "severity IN ('quarantine', 'warning')", name=op.f("ck_ingestion_issues_severity")
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ingestion_jobs.id"],
            name=op.f("fk_ingestion_issues_job_id_ingestion_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_issues")),
    )
    op.create_index("ix_ingestion_issues_job_id", "ingestion_issues", ["job_id"], unique=False)
    op.create_table(
        "document_pages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=True),
        sa.Column("printed_page_label", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("extraction_method", sa.String(length=16), nullable=False),
        sa.Column("quality_status", sa.String(length=32), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "extraction_method IN ('pdf_text', 'ocr', 'legacy')",
            name=op.f("ck_document_pages_extraction_method"),
        ),
        sa.CheckConstraint(
            "quality_status IN ('ok', 'needs_review')",
            name=op.f("ck_document_pages_quality_status"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["document_sources.id"],
            name=op.f("fk_document_pages_source_id_document_sources"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_pages")),
    )
    op.create_index("ix_document_pages_source_id", "document_pages", ["source_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_document_pages_source_id", table_name="document_pages")
    op.drop_table("document_pages")
    op.drop_index("ix_ingestion_issues_job_id", table_name="ingestion_issues")
    op.drop_table("ingestion_issues")
    op.drop_table("document_sources")
    op.drop_index("ix_judgments_jurisdiction", table_name="judgments")
    op.drop_index("ix_judgments_judgment_date", table_name="judgments")
    op.drop_index("ix_judgments_court_code", table_name="judgments")
    op.drop_index(
        "ix_judgments_citation_normalized_trgm",
        table_name="judgments",
        postgresql_using="gin",
        postgresql_ops={"citation_normalized": "gin_trgm_ops"},
    )
    op.drop_table("judgments")
    op.drop_table("ingestion_jobs")
    # pg_trgm is left installed: other objects in the database may depend on it.
