"""SQLAlchemy models for the canonical provenance schema (AGENTS.md).

M1 covers judgments, their sources and page text, plus ingestion bookkeeping.
Chunks, embeddings, audit and evaluation tables arrive with the code that uses them.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ejudgment.domain.enums import (
    AuthEventKind,
    EligibilityStatus,
    ExtractionMethod,
    GoldAction,
    GoldStatus,
    IssueSeverity,
    JobStatus,
    LlmCallStatus,
    PageReferenceStatus,
    QualityStatus,
    RightsStatus,
    SourceKind,
    SourceStatus,
    UserRole,
    VerificationStatus,
    check_in,
)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Judgment(TimestampMixin, Base):
    __tablename__ = "judgments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    canonical_uri: Mapped[str] = mapped_column(Text, unique=True)
    akn_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    citation: Mapped[str] = mapped_column(Text)
    citation_normalized: Mapped[str] = mapped_column(Text)
    neutral_citation: Mapped[str | None] = mapped_column(Text)
    case_number: Mapped[str | None] = mapped_column(Text)
    court_code: Mapped[str | None] = mapped_column(String(64))
    court_name: Mapped[str | None] = mapped_column(Text)
    jurisdiction: Mapped[str | None] = mapped_column(String(64))
    judgment_date: Mapped[date | None] = mapped_column(Date)
    language: Mapped[str | None] = mapped_column(String(32))
    judges: Mapped[list[Any]] = mapped_column(default=list)
    summary: Mapped[str | None] = mapped_column(Text)
    flynote: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict)
    source_status: Mapped[str] = mapped_column(String(32))
    eligibility_status: Mapped[str] = mapped_column(String(32))
    record_hash: Mapped[str] = mapped_column(String(64))

    sources: Mapped[list["DocumentSource"]] = relationship(back_populates="judgment")

    __table_args__ = (
        CheckConstraint(check_in("source_status", SourceStatus), name="source_status"),
        CheckConstraint(
            check_in("eligibility_status", EligibilityStatus), name="eligibility_status"
        ),
        Index(
            "ix_judgments_citation_normalized_trgm",
            "citation_normalized",
            postgresql_using="gin",
            postgresql_ops={"citation_normalized": "gin_trgm_ops"},
        ),
        Index("ix_judgments_court_code", "court_code"),
        Index("ix_judgments_jurisdiction", "jurisdiction"),
        Index("ix_judgments_judgment_date", "judgment_date"),
    )


class DocumentSource(Base):
    __tablename__ = "document_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    judgment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("judgments.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    original_url: Mapped[str | None] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    sha256: Mapped[str | None] = mapped_column(String(64))
    rights_status: Mapped[str] = mapped_column(String(32))
    verification_status: Mapped[str] = mapped_column(String(32))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    source_version: Mapped[str] = mapped_column(Text)

    judgment: Mapped[Judgment] = relationship(back_populates="sources")
    pages: Mapped[list["DocumentPage"]] = relationship(back_populates="source")

    __table_args__ = (
        UniqueConstraint("judgment_id", "kind"),
        CheckConstraint(check_in("kind", SourceKind), name="kind"),
        CheckConstraint(check_in("rights_status", RightsStatus), name="rights_status"),
        CheckConstraint(
            check_in("verification_status", VerificationStatus), name="verification_status"
        ),
    )


class DocumentPage(Base):
    """Extracted text for a source.

    ``page_index`` NULL means the text has no page mapping (legacy text); chunks built from
    it must carry ``page_reference_status=unknown``.
    """

    __tablename__ = "document_pages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_sources.id", ondelete="CASCADE")
    )
    page_index: Mapped[int | None] = mapped_column(Integer)
    printed_page_label: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(String(16))
    quality_status: Mapped[str] = mapped_column(String(32))
    quality_flags: Mapped[list[Any]] = mapped_column(default=list)
    # Mean Tesseract word confidence (0-100) for OCR pages; NULL otherwise.
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    # Extractor that produced a converted/OCR page (engine, settings, parser version); a
    # different current version makes worker.extract redo the source. NULL for importer pages.
    extractor_version: Mapped[str | None] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(String(64))

    source: Mapped[DocumentSource] = relationship(back_populates="pages")

    __table_args__ = (
        CheckConstraint(check_in("extraction_method", ExtractionMethod), name="extraction_method"),
        CheckConstraint(check_in("quality_status", QualityStatus), name="quality_status"),
        Index("ix_document_pages_source_id", "source_id"),
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    source_path: Mapped[str] = mapped_column(Text)
    source_version: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    counts: Mapped[dict[str, Any]] = mapped_column(default=dict)

    __table_args__ = (CheckConstraint(check_in("status", JobStatus), name="status"),)


class IngestionIssue(Base):
    """Quarantined records and source problems found during an ingestion job."""

    __tablename__ = "ingestion_issues"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_jobs.id", ondelete="CASCADE"))
    canonical_uri: Mapped[str | None] = mapped_column(Text)
    source_row_key: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)

    __table_args__ = (
        CheckConstraint(check_in("severity", IssueSeverity), name="severity"),
        Index("ix_ingestion_issues_job_id", "job_id"),
    )


class Chunk(Base):
    """A token-budgeted, exact span of one judgment's chosen source text.

    ``char_start``/``char_end`` index the source's pages joined by a blank line (see
    ``ingestion.chunking.SourceText.text``). Page bounds are set only when
    ``page_reference_status='verified'``.
    """

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    judgment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("judgments.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_sources.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    section_label: Mapped[str | None] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    page_reference_status: Mapped[str] = mapped_column(String(16))
    paragraph_refs: Mapped[list[Any]] = mapped_column(default=list)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    token_count: Mapped[int] = mapped_column(Integer)
    chunker_version: Mapped[str] = mapped_column(String(128))
    # Hash of the whole source text; judgments re-published under several URIs share it.
    source_text_hash: Mapped[str] = mapped_column(String(64))
    textsearch_en: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True)
    )
    textsearch_simple: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', content)", persisted=True)
    )

    __table_args__ = (
        UniqueConstraint("judgment_id", "ordinal"),
        CheckConstraint(
            check_in("page_reference_status", PageReferenceStatus), name="page_reference_status"
        ),
        CheckConstraint(
            "(page_reference_status = 'verified') = "
            "(page_start IS NOT NULL AND page_end IS NOT NULL)",
            name="page_bounds_only_when_verified",
        ),
        CheckConstraint("char_end > char_start", name="char_span"),
        Index("ix_chunks_textsearch_en", "textsearch_en", postgresql_using="gin"),
        Index("ix_chunks_textsearch_simple", "textsearch_simple", postgresql_using="gin"),
        Index("ix_chunks_source_text_hash", "source_text_hash"),
        Index("ix_chunks_content_hash", "content_hash"),
    )


class QueryAudit(Base):
    """Search audit. Raw query text is stored only when AUDIT_STORE_RAW_QUERIES=true."""

    __tablename__ = "query_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    endpoint: Mapped[str] = mapped_column(String(64))
    query_hash: Mapped[str] = mapped_column(String(64))
    query_text: Mapped[str | None] = mapped_column(Text)
    filters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result_judgment_ids: Mapped[list[Any]] = mapped_column(default=list)
    latency_ms: Mapped[int] = mapped_column(Integer)
    # Who asked (NULL for CLI and evaluation runs). Deleting a user keeps their audit rows.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    __table_args__ = (Index("ix_query_audit_created_at", "created_at"),)


class ChunkEmbedding(Base):
    """One vector per chunk and model revision (AGENTS.md).

    ``embedding`` is an untyped ``vector``; each model gets a partial HNSW expression index on
    ``embedding::vector(<dim>)`` created by migration, and queries cast to the same dimension
    and filter on the same model/revision so that index is used.
    """

    __tablename__ = "chunk_embeddings"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    model_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    model_revision: Mapped[str] = mapped_column(String(64), primary_key=True)
    dimension: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float]] = mapped_column(Vector())
    content_hash: Mapped[str] = mapped_column(String(64))
    # SHA-256 of the exact contextualized text sent to the model (incl. template version).
    embedding_input_hash: Mapped[str] = mapped_column(String(64))
    embedding_template_version: Mapped[str] = mapped_column(String(32))
    # MD5 of the judgment metadata (title, court, year) the input was built from; NULL until
    # backfilled. Dense search ignores vectors whose context no longer matches the judgment.
    context_hash: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("vector_dims(embedding) = dimension", name="dimension_matches"),
        Index("ix_chunk_embeddings_model", "model_id", "model_revision"),
    )


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    model_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    revision: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    dimension: Mapped[int | None] = mapped_column(Integer)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (CheckConstraint("kind IN ('embedding', 'reranker')", name="kind"),)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    config: Mapped[dict[str, Any]] = mapped_column(default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    per_question: Mapped[list[Any]] = mapped_column(default=list)


class LlmUsage(Base):
    """One row per generation request (AGENTS.md OpenAI pilot): usage and estimated cost.

    No prompt, question or answer text is stored. ``run_id`` groups the calls of one
    evaluation run; API calls have none.
    """

    __tablename__ = "llm_usage_ledger"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    endpoint: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cached_input_tokens: Mapped[int] = mapped_column(Integer)
    estimated_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6))
    latency_ms: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        CheckConstraint(check_in("status", LlmCallStatus), name="status"),
        Index("ix_llm_usage_ledger_created_at", "created_at"),
        Index("ix_llm_usage_ledger_run_id", "run_id"),
    )


class User(Base):
    """An invited account. Passwords are stored only as Argon2id hashes."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lowercased
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(check_in("role", UserRole), name="role"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
    )


class UserSession(Base):
    """A signed-in session. Only the SHA-256 of the bearer token is stored."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # absolute limit
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_sessions_user_id", "user_id"),)


class AuthEvent(Base):
    """Security audit: sign-ins, failures, lockouts, account changes. No secrets, no raw IPs."""

    __tablename__ = "auth_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Salted hash of the lowercased email tried (rate limiting also for unknown emails).
    email_hash: Mapped[str | None] = mapped_column(String(64))
    event: Mapped[str] = mapped_column(String(32))
    client_hash: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)

    __table_args__ = (
        CheckConstraint(check_in("event", AuthEventKind), name="event"),
        Index("ix_auth_events_email_hash_created_at", "email_hash", "created_at"),
        Index("ix_auth_events_created_at", "created_at"),
    )


class GoldQuestionRecord(Base):
    """An evaluation question under review (exported to evals/gold.jsonl for evaluations).

    Gold passages are stored as verbatim text with their judgment's URI, not chunk ids, so they
    survive re-chunking. Reviewer identity stays here; the exported file carries no names.
    """

    __tablename__ = "gold_questions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32))
    filters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    expect_no_answer: Mapped[bool] = mapped_column(Boolean, default=False)
    gold_canonical_uris: Mapped[list[Any]] = mapped_column(default=list)
    gold_passages: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(16))
    notes: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(check_in("status", GoldStatus), name="status"),
        CheckConstraint(
            "category IN ('citation', 'case_name', 'issue', 'fact_pattern', 'out_of_corpus')",
            name="category",
        ),
        Index("ix_gold_questions_status", "status"),
    )


class GoldQuestionHistory(Base):
    """Append-only record of every change to a gold question (who, when, what it became)."""

    __tablename__ = "gold_question_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    question_id: Mapped[str] = mapped_column(ForeignKey("gold_questions.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(16))
    snapshot: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(check_in("action", GoldAction), name="action"),
        Index("ix_gold_question_history_question_id", "question_id", "created_at"),
    )
