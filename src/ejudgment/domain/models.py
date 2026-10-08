"""SQLAlchemy models for the canonical provenance schema (AGENTS.md).

M1 covers judgments, their sources and page text, plus ingestion bookkeeping.
Chunks, embeddings, audit and evaluation tables arrive with the code that uses them.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ejudgment.domain.enums import (
    EligibilityStatus,
    ExtractionMethod,
    IssueSeverity,
    JobStatus,
    QualityStatus,
    RightsStatus,
    SourceKind,
    SourceStatus,
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
