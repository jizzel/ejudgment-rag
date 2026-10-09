"""Turn files without usable text into ``document_pages``: Word conversion and page-level OCR.

Works on eligible judgments whose status is ``conversion_pending`` or ``ocr_pending`` and
whose downloaded file (``kind=pdf`` source) is ``verified`` or ``unverified`` and has no pages
yet, so re-running does nothing. Each judgment is one transaction.

The importer's ``record_hash`` is not touched: a re-import of an unchanged export skips these
records and keeps the extracted pages. If the export changes, the importer replaces the
sources (and the extracted pages with them) and this step runs again.
"""

import logging
import statistics
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Engine, Table, insert, select, update
from sqlalchemy.engine import Connection

from ejudgment.config import Settings
from ejudgment.domain.enums import (
    EligibilityStatus,
    ExtractionMethod,
    IssueSeverity,
    JobStatus,
    QualityStatus,
    SourceKind,
    SourceStatus,
    VerificationStatus,
)
from ejudgment.domain.models import (
    DocumentPage,
    DocumentSource,
    IngestionIssue,
    IngestionJob,
    Judgment,
)
from ejudgment.ingestion.docx_text import DocxError, docx_text
from ejudgment.ingestion.hashing import sha256_file
from ejudgment.ingestion.ocr import OcrEngine, OcrError
from ejudgment.ingestion.pdf_pages import ExtractedPage, has_machine_readable_text
from ejudgment.ingestion.pdf_verify import (
    DOCX_MIME,
    PDF_MIME,
    PdfVerifier,
    containment,
    contains_neutral_citation,
    tokens,
)
from ejudgment.ingestion.service import page_row

logger = logging.getLogger(__name__)

JUDGMENTS = cast(Table, Judgment.__table__)
SOURCES = cast(Table, DocumentSource.__table__)
PAGES = cast(Table, DocumentPage.__table__)
JOBS = cast(Table, IngestionJob.__table__)
ISSUES = cast(Table, IngestionIssue.__table__)

JOB_KIND = "extract"
_PENDING = (SourceStatus.CONVERSION_PENDING.value, SourceStatus.OCR_PENDING.value)
_USABLE = (VerificationStatus.VERIFIED.value, VerificationStatus.UNVERIFIED.value)
# Same evidence threshold the importer uses for party names on an unshared file.
_TITLE_MIN_OVERLAP = 0.8


@dataclass
class ExtractReport:
    engine: str
    candidates: int = 0
    converted: int = 0
    ocr_documents: int = 0
    ocr_pages: int = 0
    low_confidence_pages: int = 0
    verified_upgrades: int = 0
    still_pending: int = 0
    unsupported: int = 0
    source_changed: int = 0
    failed: int = 0
    seconds: float = 0.0
    page_confidences: list[float] = field(default_factory=list, repr=False)
    issues: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in self.__dict__.items() if k != "page_confidences"}
        data["issues"] = dict(sorted(self.issues.items()))
        data["seconds"] = round(self.seconds, 1)
        data["mean_ocr_confidence"] = (
            round(statistics.fmean(self.page_confidences), 1) if self.page_confidences else None
        )
        return data


def verification_evidence(text: str, neutral_citation: str | None, title: str | None) -> str | None:
    """Reason the extracted text proves the file belongs to the record, or ``None``."""
    if contains_neutral_citation(text, neutral_citation):
        return "extracted_citation_match"
    if title and containment(tokens(title), tokens(text)) >= _TITLE_MIN_OVERLAP:
        return "extracted_title_match"
    return None


@dataclass(frozen=True)
class _Candidate:
    judgment_id: uuid.UUID
    canonical_uri: str
    title: str | None
    neutral_citation: str | None
    source_id: uuid.UUID
    local_path: str
    mime_type: str | None
    sha256: str | None
    verification_status: str


def _candidates(conn: Connection, limit: int | None) -> list[_Candidate]:
    has_pages = select(PAGES.c.id).where(PAGES.c.source_id == SOURCES.c.id).exists()
    query = (
        select(
            JUDGMENTS.c.id,
            JUDGMENTS.c.canonical_uri,
            JUDGMENTS.c.title,
            JUDGMENTS.c.neutral_citation,
            SOURCES.c.id.label("source_id"),
            SOURCES.c.local_path,
            SOURCES.c.mime_type,
            SOURCES.c.sha256,
            SOURCES.c.verification_status,
        )
        .join(SOURCES, SOURCES.c.judgment_id == JUDGMENTS.c.id)
        .where(
            JUDGMENTS.c.eligibility_status == EligibilityStatus.ELIGIBLE.value,
            JUDGMENTS.c.source_status.in_(_PENDING),
            SOURCES.c.kind == SourceKind.PDF.value,
            SOURCES.c.verification_status.in_(_USABLE),
            SOURCES.c.local_path.is_not(None),
            ~has_pages,
        )
        .order_by(JUDGMENTS.c.id)
    )
    if limit is not None:
        query = query.limit(limit)
    return [_Candidate(*row) for row in conn.execute(query)]


def _issue(
    conn: Connection, job_id: uuid.UUID, candidate: _Candidate, reason: str, **details: Any
) -> None:
    conn.execute(
        insert(ISSUES).values(
            id=uuid.uuid4(),
            job_id=job_id,
            canonical_uri=candidate.canonical_uri,
            source_row_key=candidate.canonical_uri,
            severity=IssueSeverity.WARNING.value,
            reason=reason,
            details={key: str(value) for key, value in details.items()},
        )
    )


def _pages(
    candidate: _Candidate, path: Path, ocr: OcrEngine, settings: Settings, report: ExtractReport
) -> tuple[list[dict[str, Any]], str] | None:
    """Page rows and the full text, or ``None`` for an unsupported format."""
    if candidate.mime_type == DOCX_MIME:
        text = docx_text(path)
        row = page_row(candidate.source_id, text, nul_removed=False)
        row["extraction_method"] = ExtractionMethod.CONVERTED.value
        return [row], text
    if candidate.mime_type == PDF_MIME:
        rows: list[dict[str, Any]] = []
        for page in ocr.ocr_pdf(path):
            text = page.text.replace("\x00", "")
            row = page_row(
                candidate.source_id,
                text,
                nul_removed="\x00" in page.text,
                page_index=page.page_index,
                method=ExtractionMethod.OCR,
            )
            row["ocr_confidence"] = page.mean_confidence
            if page.mean_confidence is not None:
                report.page_confidences.append(page.mean_confidence)
                if page.mean_confidence < settings.ocr_min_confidence:
                    row["quality_flags"] = [*row["quality_flags"], "low_ocr_confidence"]
                    row["quality_status"] = QualityStatus.NEEDS_REVIEW.value
                    report.low_confidence_pages += 1
            rows.append(row)
        return rows, "\n\n".join(row["text"] for row in rows)
    return None


def run_extraction(
    engine: Engine,
    settings: Settings,
    pdf_base_dir: Path,
    ocr: OcrEngine,
    *,
    limit: int | None = None,
) -> ExtractReport:
    report = ExtractReport(engine=ocr.name)
    started = time.perf_counter()
    resolver = PdfVerifier(
        pdf_base_dir,
        pages=settings.pdf_verify_pages,
        min_window_chars=settings.pdf_verify_min_window_chars,
        min_overlap=settings.pdf_verify_min_overlap,
    )
    job_id = uuid.uuid4()
    with engine.begin() as conn:
        candidates = _candidates(conn, limit)
        conn.execute(
            insert(JOBS).values(
                id=job_id,
                kind=JOB_KIND,
                source_path=str(pdf_base_dir),
                source_version=ocr.name,
                status=JobStatus.RUNNING.value,
            )
        )
    report.candidates = len(candidates)
    aborted: str | None = None
    try:
        for done, candidate in enumerate(candidates, start=1):
            _extract_one(engine, job_id, candidate, resolver, ocr, settings, report)
            logger.info(
                "Extracted %d/%d (%s): %d converted, %d OCR'd (%d pages), %d still pending",
                done,
                len(candidates),
                candidate.canonical_uri,
                report.converted,
                report.ocr_documents,
                report.ocr_pages,
                report.still_pending,
            )
    except BaseException as exc:
        # An unexpected error (or Ctrl-C) stops the batch: the job must not read as succeeded.
        # Documents finished before it keep their pages (one transaction each).
        aborted = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report.seconds = time.perf_counter() - started
        failed = report.failed or aborted is not None
        counts = report.as_dict() | ({"aborted": aborted} if aborted else {})
        with engine.begin() as conn:
            conn.execute(
                update(JOBS)
                .where(JOBS.c.id == job_id)
                .values(
                    status=(JobStatus.FAILED if failed else JobStatus.SUCCEEDED).value,
                    counts=counts,
                )
            )
    return report


def _extract_one(
    engine: Engine,
    job_id: uuid.UUID,
    candidate: _Candidate,
    resolver: PdfVerifier,
    ocr: OcrEngine,
    settings: Settings,
    report: ExtractReport,
) -> None:
    path = resolver.resolve(candidate.local_path)
    with engine.begin() as conn:
        if path is None or not path.is_file():
            report.failed += 1
            report.issues["source_missing"] += 1
            _issue(conn, job_id, candidate, "source_missing", local_path=candidate.local_path)
            return
        # The file must still be the one verified at import time.
        if candidate.sha256 and sha256_file(path) != candidate.sha256:
            report.source_changed += 1
            report.issues["source_changed"] += 1
            _issue(conn, job_id, candidate, "source_changed", local_path=candidate.local_path)
            return
        try:
            extracted = _pages(candidate, path, ocr, settings, report)
        except (DocxError, OcrError) as exc:
            logger.warning("Extraction failed for %s: %s", candidate.canonical_uri, exc)
            report.failed += 1
            report.issues["extraction_failed"] += 1
            _issue(conn, job_id, candidate, "extraction_failed", error=exc)
            return
        if extracted is None:
            report.unsupported += 1
            report.issues["unsupported_format"] += 1
            _issue(conn, job_id, candidate, "unsupported_format", mime_type=candidate.mime_type)
            return
        rows, text = extracted
        readable = has_machine_readable_text([ExtractedPage(0, text, False)])
        if not readable:
            report.still_pending += 1
            report.issues["no_text_extracted"] += 1
            _issue(conn, job_id, candidate, "no_text_extracted", pages=len(rows))
            return

        conn.execute(insert(PAGES), rows)
        if candidate.mime_type == PDF_MIME:
            report.ocr_documents += 1
            report.ocr_pages += len(rows)
        else:
            report.converted += 1
        source_values: dict[str, Any] = {}
        if candidate.verification_status == VerificationStatus.UNVERIFIED.value:
            evidence = verification_evidence(text, candidate.neutral_citation, candidate.title)
            if evidence is not None:
                source_values["verification_status"] = VerificationStatus.VERIFIED.value
                report.verified_upgrades += 1
                report.issues[f"verified_by_{evidence}"] += 1
        if source_values:
            conn.execute(
                update(SOURCES).where(SOURCES.c.id == candidate.source_id).values(**source_values)
            )
        conn.execute(
            update(JUDGMENTS)
            .where(JUDGMENTS.c.id == candidate.judgment_id)
            .values(source_status=SourceStatus.TEXT_AVAILABLE.value)
        )
