"""Legacy export import: normalize, verify, quarantine and upsert idempotently.

Re-running an import over unchanged input writes nothing: every row carries a
``record_hash`` and deterministic IDs, so unchanged records are skipped.
"""

import logging
import uuid
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Engine, Table, delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from ejudgment.config import Settings
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
)
from ejudgment.domain.models import (
    DocumentPage,
    DocumentSource,
    IngestionIssue,
    IngestionJob,
    Judgment,
)
from ejudgment.ingestion.hashing import sha256_text, stable_id, stable_json_hash
from ejudgment.ingestion.legacy_adapter import TEXT_COLUMNS, LegacyExport, LegacyRecord
from ejudgment.ingestion.normalize import (
    clean_text,
    clean_value,
    derive_title,
    has_nul,
    normalize_case_number,
    normalize_citation,
    parse_akn_uri,
    parse_judgment_date,
    parse_neutral_citation,
    split_judges,
    strip_copy_suffix,
)
from ejudgment.ingestion.pdf_verify import PdfCheck, PdfVerifier
from ejudgment.ingestion.quality import assess_text, is_viewer_boilerplate, strip_leading_navigation

logger = logging.getLogger(__name__)

JOB_KIND = "legacy_import"
# The whole local export is used under GhaLII's CC BY-NC 4.0 licence (see AGENTS.md).
EXPORT_RIGHTS = RightsStatus.CC_BY_NC_LOCAL_EXPORT
_USABLE_PDF = (VerificationStatus.VERIFIED, VerificationStatus.UNVERIFIED)

JUDGMENTS = cast(Table, Judgment.__table__)
SOURCES = cast(Table, DocumentSource.__table__)
PAGES = cast(Table, DocumentPage.__table__)
JOBS = cast(Table, IngestionJob.__table__)
ISSUES = cast(Table, IngestionIssue.__table__)


@dataclass
class Issue:
    row_key: str
    canonical_uri: str | None
    severity: IssueSeverity
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreparedSource:
    row: dict[str, Any]
    pages: list[dict[str, Any]]


@dataclass
class PreparedJudgment:
    row: dict[str, Any]
    sources: list[PreparedSource]
    pdf_check: PdfCheck | None
    html_boilerplate_discarded: bool
    pages_needing_review: int

    @property
    def id(self) -> uuid.UUID:
        value = self.row["id"]
        assert isinstance(value, uuid.UUID)
        return value

    @property
    def record_hash(self) -> str:
        return str(self.row["record_hash"])


@dataclass
class ImportReport:
    source: str
    source_version: str
    dry_run: bool
    rows_read: int = 0
    accepted: int = 0
    quarantined: int = 0
    failed: int = 0
    skipped_duplicate: int = 0
    skipped_unchanged: int = 0
    # Judgments stored by an earlier import whose URI now has conflicting rows.
    quarantined_existing: int = 0
    inserted: int = 0
    updated: int = 0
    text_available: int = 0
    ocr_pending: int = 0
    conversion_pending: int = 0
    html_boilerplate_discarded: int = 0
    pages_needing_review: int = 0
    pdf: Counter[str] = field(default_factory=Counter)
    source_file_types: Counter[str] = field(default_factory=Counter)
    quarantine_reasons: Counter[str] = field(default_factory=Counter)
    warnings: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        for key in ("pdf", "source_file_types", "quarantine_reasons", "warnings"):
            data[key] = dict(sorted(data[key].items()))
        return data


@dataclass(frozen=True)
class _PrePass:
    uri_counts: Counter[str]
    conflicting_uris: frozenset[str]
    path_counts: Counter[str]
    # Legacy text hash -> URIs carrying that exact text (GhaLII sometimes publishes one
    # judgment under several numbers). Only groups with more than one URI are kept.
    text_twins: dict[str, list[str]]


def _pre_pass(records: Iterable[LegacyRecord]) -> _PrePass:
    """Find duplicate identities, PDF paths shared by several rows and duplicated texts."""
    uri_counts: Counter[str] = Counter()
    uri_row_hashes: dict[str, set[str]] = {}
    path_counts: Counter[str] = Counter()
    text_uris: dict[str, set[str]] = {}
    for record in records:
        identity = parse_akn_uri(clean_text(record.get("url")))
        if identity is not None:
            uri_counts[identity.canonical_uri] += 1
            uri_row_hashes.setdefault(identity.canonical_uri, set()).add(
                stable_json_hash(record.values)
            )
            pdf_text = clean_text(record.get("pdf_text"))
            if pdf_text is not None:
                text_uris.setdefault(sha256_text(pdf_text), set()).add(identity.canonical_uri)
        path = clean_text(record.get("pdf_local_path"))
        if path is not None:
            path_counts[path] += 1
    conflicting = frozenset(uri for uri, hashes in uri_row_hashes.items() if len(hashes) > 1)
    twins = {digest: sorted(uris) for digest, uris in text_uris.items() if len(uris) > 1}
    return _PrePass(uri_counts, conflicting, path_counts, twins)


def _legacy_metadata(record: LegacyRecord) -> dict[str, Any]:
    """Original row values (minus the large text columns), with missing markers as NULL."""
    return {
        column: clean_value(value)
        for column, value in sorted(record.values.items())
        if column not in TEXT_COLUMNS
    }


def _page_row(source_id: uuid.UUID, text: str, *, nul_removed: bool) -> dict[str, Any]:
    quality = assess_text(text)
    flags = [*quality.flags, *(["nul_characters_removed"] if nul_removed else [])]
    return {
        "id": stable_id(str(source_id), "page", "unmapped"),
        "source_id": source_id,
        "page_index": None,  # legacy text has no page mapping
        "printed_page_label": None,
        "text": text,
        "extraction_method": ExtractionMethod.LEGACY.value,
        "quality_status": (
            QualityStatus.NEEDS_REVIEW.value if quality.needs_review else QualityStatus.OK.value
        ),
        # nul_characters_removed is recorded for provenance; it does not need review.
        "quality_flags": flags,
        "text_hash": sha256_text(text),
    }


def prepare_record(
    record: LegacyRecord,
    *,
    source_version: str,
    verifier: PdfVerifier,
    path_counts: Counter[str],
    text_twins: dict[str, list[str]] | None = None,
) -> tuple[PreparedJudgment | None, list[Issue]]:
    """Normalize one export row. Returns ``(None, issues)`` when it cannot be imported."""
    issues: list[Issue] = []
    row_key = record.row_key
    url = clean_text(record.get("url"))
    identity = parse_akn_uri(url)
    if identity is None:
        issues.append(
            Issue(row_key, None, IssueSeverity.QUARANTINE, "invalid_akn_uri", {"url": url})
        )
        return None, issues
    uri = identity.canonical_uri

    citation = strip_copy_suffix(clean_text(record.get("citation")))
    if citation is None:
        issues.append(Issue(row_key, uri, IssueSeverity.QUARANTINE, "missing_citation"))
        return None, issues

    if not EXPORT_RIGHTS.eligible:
        issues.append(Issue(row_key, uri, IssueSeverity.QUARANTINE, "rights_not_eligible"))
        return None, issues

    judgment_id = stable_id("judgment", uri)
    raw_date = clean_text(record.get("judgment_date"))
    judgment_date = parse_judgment_date(raw_date)
    if raw_date is not None and judgment_date is None:
        issues.append(
            Issue(
                row_key, uri, IssueSeverity.WARNING, "unparsed_judgment_date", {"value": raw_date}
            )
        )
    elif judgment_date is not None and judgment_date != identity.expression_date:
        issues.append(
            Issue(
                row_key,
                uri,
                IssueSeverity.WARNING,
                "judgment_date_differs_from_uri",
                {"judgment_date": judgment_date, "uri_date": identity.expression_date},
            )
        )

    neutral = strip_copy_suffix(clean_text(record.get("media_neutral_citation")))
    if neutral is None:
        parsed = parse_neutral_citation(citation)
        neutral = str(parsed) if parsed else None

    title = derive_title(citation)
    pdf_download_link = clean_text(record.get("pdf_download_link"))
    sources: list[PreparedSource] = []

    # Legacy PDF text: usable, but without page mapping.
    pdf_text = clean_text(record.get("pdf_text"))
    if pdf_text is not None:
        twins = (text_twins or {}).get(sha256_text(pdf_text), [])
        if twins:
            issues.append(
                Issue(
                    row_key,
                    uri,
                    IssueSeverity.WARNING,
                    "duplicate_text_across_uris",
                    {"other_uris": [other for other in twins if other != uri][:10]},
                )
            )
        source_id = stable_id(str(judgment_id), SourceKind.LEGACY.value)
        sources.append(
            PreparedSource(
                row={
                    "id": source_id,
                    "judgment_id": judgment_id,
                    "kind": SourceKind.LEGACY.value,
                    "original_url": pdf_download_link,
                    "local_path": None,
                    "mime_type": "text/plain",
                    "sha256": sha256_text(pdf_text),
                    "rights_status": EXPORT_RIGHTS.value,
                    "verification_status": VerificationStatus.NOT_APPLICABLE.value,
                    "source_version": source_version,
                },
                pages=[_page_row(source_id, pdf_text, nul_removed=has_nul(record.get("pdf_text")))],
            )
        )

    # Captured HTML text: often only PDF-viewer labels, which are discarded.
    full_text = clean_text(record.get("full_text"))
    html_boilerplate = is_viewer_boilerplate(full_text)
    if full_text is not None and not html_boilerplate:
        body, _ = strip_leading_navigation(full_text)
        if body:
            source_id = stable_id(str(judgment_id), SourceKind.HTML.value)
            sources.append(
                PreparedSource(
                    row={
                        "id": source_id,
                        "judgment_id": judgment_id,
                        "kind": SourceKind.HTML.value,
                        "original_url": url,
                        "local_path": None,
                        "mime_type": "text/plain",
                        "sha256": sha256_text(body),
                        "rights_status": EXPORT_RIGHTS.value,
                        "verification_status": VerificationStatus.NOT_APPLICABLE.value,
                        "source_version": source_version,
                    },
                    pages=[
                        _page_row(source_id, body, nul_removed=has_nul(record.get("full_text")))
                    ],
                )
            )

    # Local source file: registered with its verification result; text extraction comes later.
    # Kind "pdf" means "the downloaded source file"; mime_type records its real format, since
    # many legacy downloads are Word/RTF/HTML files saved with a .pdf name.
    local_path = clean_text(record.get("pdf_local_path"))
    pdf_check: PdfCheck | None = None
    if local_path is not None:
        pdf_check = verifier.verify(
            local_path,
            reference_text=pdf_text,
            title=title,
            path_shared=path_counts[local_path] > 1,
            neutral_citation=neutral,
        )
        sources.append(
            PreparedSource(
                row={
                    "id": stable_id(str(judgment_id), SourceKind.PDF.value),
                    "judgment_id": judgment_id,
                    "kind": SourceKind.PDF.value,
                    "original_url": pdf_download_link,
                    "local_path": local_path,
                    "mime_type": pdf_check.mime_type,
                    "sha256": pdf_check.sha256,
                    "rights_status": EXPORT_RIGHTS.value,
                    "verification_status": pdf_check.status.value,
                    "source_version": source_version,
                },
                pages=[],
            )
        )
        if pdf_check.status in (VerificationStatus.MISMATCH, VerificationStatus.MISSING):
            issues.append(
                Issue(
                    row_key,
                    uri,
                    IssueSeverity.WARNING,
                    f"pdf_{pdf_check.status.value}",
                    {
                        "reason": pdf_check.reason,
                        "local_path": local_path,
                        "score": pdf_check.score,
                    },
                )
            )

    has_text = any(source.pages for source in sources)
    has_usable_pdf = pdf_check is not None and pdf_check.status in _USABLE_PDF
    if has_text:
        source_status = SourceStatus.TEXT_AVAILABLE
    elif has_usable_pdf and pdf_check is not None and not pdf_check.is_pdf:
        source_status = SourceStatus.CONVERSION_PENDING
    elif has_usable_pdf:
        source_status = SourceStatus.OCR_PENDING
    else:
        source_status = SourceStatus.NO_SOURCE

    eligibility = EligibilityStatus.ELIGIBLE
    if source_status is SourceStatus.NO_SOURCE:
        eligibility = EligibilityStatus.QUARANTINED
        issues.append(Issue(row_key, uri, IssueSeverity.QUARANTINE, "no_usable_text_and_no_pdf"))

    row: dict[str, Any] = {
        "id": judgment_id,
        "canonical_uri": uri,
        "akn_id": identity.work_uri,
        "title": title,
        "citation": citation,
        "citation_normalized": normalize_citation(citation),
        "neutral_citation": neutral,
        "case_number": normalize_case_number(clean_text(record.get("case_number"))),
        "court_code": identity.court_code,
        "court_name": clean_text(record.get("court")),
        "jurisdiction": identity.jurisdiction,
        "judgment_date": judgment_date,
        "language": clean_text(record.get("language")),
        "judges": split_judges(clean_text(record.get("judges"))),
        "summary": None,
        "flynote": None,
        "metadata_": {
            "derived": {"title": "from_citation"},
            "akn": {
                "work_uri": identity.work_uri,
                "year": identity.year,
                "number": identity.number,
                "language": identity.language,
                "expression_date": identity.expression_date.isoformat(),
            },
            "legacy": _legacy_metadata(record),
        },
        "source_status": source_status.value,
        "eligibility_status": eligibility.value,
    }
    row["record_hash"] = stable_json_hash(
        {
            "judgment": row,
            # source_version is excluded so a re-exported but unchanged record stays unchanged.
            "sources": [
                {
                    "row": {k: v for k, v in source.row.items() if k != "source_version"},
                    "pages": [
                        {k: v for k, v in page.items() if k != "text"} for page in source.pages
                    ],
                }
                for source in sources
            ],
        }
    )
    prepared = PreparedJudgment(
        row=row,
        sources=sources,
        pdf_check=pdf_check,
        html_boilerplate_discarded=html_boilerplate,
        pages_needing_review=sum(
            page["quality_status"] == QualityStatus.NEEDS_REVIEW.value
            for source in sources
            for page in source.pages
        ),
    )
    return prepared, issues


def _batched[T](items: Iterable[T], size: int) -> Iterator[list[T]]:
    iterator = iter(items)
    while batch := list(islice(iterator, size)):
        yield batch


def _judgment_columns(row: dict[str, Any]) -> dict[str, Any]:
    """Map attribute names to column names (``metadata_`` -> ``metadata``)."""
    return {("metadata" if key == "metadata_" else key): value for key, value in row.items()}


def _write_batch(
    conn: Connection, prepared: Sequence[PreparedJudgment], report: ImportReport
) -> None:
    judgments, sources, pages = JUDGMENTS, SOURCES, PAGES

    rows = conn.execute(
        select(judgments.c.id, judgments.c.record_hash).where(
            judgments.c.id.in_([item.id for item in prepared])
        )
    )
    existing: dict[uuid.UUID, str] = {row.id: row.record_hash for row in rows}
    for item in prepared:
        previous_hash = existing.get(item.id)
        if previous_hash == item.record_hash:
            report.skipped_unchanged += 1
            continue
        values = _judgment_columns(item.row)
        statement = pg_insert(judgments).values(**values)
        update_columns: dict[str, Any] = {
            key: statement.excluded[key] for key in values if key not in ("id", "canonical_uri")
        }
        update_columns["updated_at"] = func.now()
        conn.execute(
            statement.on_conflict_do_update(index_elements=["canonical_uri"], set_=update_columns)
        )
        # Sources and pages are derived from the record: replace them wholesale on change.
        conn.execute(delete(sources).where(sources.c.judgment_id == item.id))
        for source in item.sources:
            conn.execute(insert(sources).values(**source.row))
            if source.pages:
                conn.execute(insert(pages), source.pages)
        if previous_hash is None:
            report.inserted += 1
        else:
            report.updated += 1


# Stored as record_hash of a judgment quarantined for a URI conflict. It never equals a real
# hash, so once the conflict is resolved the next import rewrites the record.
CONFLICT_RECORD_HASH = "quarantined:duplicate_uri_conflict"


def _quarantine_conflicts(conn: Connection, uris: set[str], report: ImportReport) -> None:
    """Quarantine already-stored judgments whose URI now has conflicting export rows."""
    if not uris:
        return
    result = conn.execute(
        update(JUDGMENTS)
        .where(
            JUDGMENTS.c.canonical_uri.in_(sorted(uris)),
            JUDGMENTS.c.record_hash != CONFLICT_RECORD_HASH,
        )
        .values(
            eligibility_status=EligibilityStatus.QUARANTINED.value,
            record_hash=CONFLICT_RECORD_HASH,
            updated_at=func.now(),
        )
    )
    report.quarantined_existing += result.rowcount


def _write_issues(conn: Connection, job_id: uuid.UUID, issues: Sequence[Issue]) -> None:
    if not issues:
        return
    rows = [
        {
            "id": uuid.uuid4(),
            "job_id": job_id,
            "canonical_uri": issue.canonical_uri,
            "source_row_key": issue.row_key,
            "severity": issue.severity.value,
            "reason": issue.reason,
            "details": {key: _jsonable(value) for key, value in issue.details.items()},
        }
        for issue in issues
    ]
    conn.execute(insert(ISSUES), rows)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def run_legacy_import(
    source: Path,
    pdf_base_dir: Path,
    settings: Settings,
    *,
    engine: Engine | None,
    dry_run: bool = False,
    limit: int | None = None,
) -> ImportReport:
    """Import the legacy export. With ``dry_run`` (or no engine) nothing is written."""
    if not dry_run and engine is None:
        raise ValueError("An engine is required unless dry_run=True")
    export = LegacyExport(source)
    source_version = export.source_version()
    report = ImportReport(source=str(source), source_version=source_version, dry_run=dry_run)
    verifier = PdfVerifier(
        pdf_base_dir,
        pages=settings.pdf_verify_pages,
        min_window_chars=settings.pdf_verify_min_window_chars,
        min_overlap=settings.pdf_verify_min_overlap,
    )
    logger.info("Pre-pass over %s (%s)", source, source_version)
    pre = _pre_pass(export.records(limit=limit))

    job_id = uuid.uuid4()
    if not dry_run:
        assert engine is not None
        with engine.begin() as conn:
            conn.execute(
                insert(JOBS).values(
                    id=job_id,
                    kind=JOB_KIND,
                    source_path=str(source),
                    source_version=source_version,
                    status=JobStatus.RUNNING.value,
                )
            )

    seen_uris: set[str] = set()
    try:
        for batch in _batched(export.records(limit=limit), settings.ingest_batch_size):
            prepared_batch: list[PreparedJudgment] = []
            batch_issues: list[Issue] = []
            for record in batch:
                report.rows_read += 1
                prepared, issues = _prepare_with_guards(
                    record, pre, seen_uris, source_version, verifier, report
                )
                batch_issues.extend(issues)
                for issue in issues:
                    target = (
                        report.quarantine_reasons
                        if issue.severity is IssueSeverity.QUARANTINE
                        else report.warnings
                    )
                    target[issue.reason] += 1
                if prepared is not None:
                    _count_prepared(prepared, report)
                    prepared_batch.append(prepared)
            if not dry_run and engine is not None:
                with engine.begin() as conn:
                    if prepared_batch:
                        _write_batch(conn, prepared_batch, report)
                    _quarantine_conflicts(
                        conn,
                        {
                            issue.canonical_uri
                            for issue in batch_issues
                            if issue.reason == "duplicate_uri_conflict" and issue.canonical_uri
                        },
                        report,
                    )
                    _write_issues(conn, job_id, batch_issues)
            logger.info("Processed %d rows", report.rows_read)
    except Exception:
        if not dry_run and engine is not None:
            _finish_job(engine, job_id, JobStatus.FAILED, report)
        raise
    if not dry_run and engine is not None:
        _finish_job(engine, job_id, JobStatus.SUCCEEDED, report)
    return report


def _prepare_with_guards(
    record: LegacyRecord,
    pre: _PrePass,
    seen_uris: set[str],
    source_version: str,
    verifier: PdfVerifier,
    report: ImportReport,
) -> tuple[PreparedJudgment | None, list[Issue]]:
    identity = parse_akn_uri(clean_text(record.get("url")))
    if identity is not None:
        uri = identity.canonical_uri
        if uri in pre.conflicting_uris:
            report.quarantined += 1
            return None, [
                Issue(
                    record.row_key,
                    uri,
                    IssueSeverity.QUARANTINE,
                    "duplicate_uri_conflict",
                    {"rows_with_uri": pre.uri_counts[uri]},
                )
            ]
        if uri in seen_uris:
            report.skipped_duplicate += 1
            return None, [
                Issue(record.row_key, uri, IssueSeverity.WARNING, "duplicate_uri_identical")
            ]
        seen_uris.add(uri)
    try:
        prepared, issues = prepare_record(
            record,
            source_version=source_version,
            verifier=verifier,
            path_counts=pre.path_counts,
            text_twins=pre.text_twins,
        )
    except Exception as exc:  # one bad row must not abort the import
        logger.exception("Failed to prepare %s", record.row_key)
        report.failed += 1
        return None, [
            Issue(
                record.row_key,
                identity.canonical_uri if identity else None,
                IssueSeverity.QUARANTINE,
                "prepare_failed",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        ]
    if prepared is None or prepared.row["eligibility_status"] == EligibilityStatus.QUARANTINED:
        report.quarantined += 1
    else:
        report.accepted += 1
    return prepared, issues


def _count_prepared(prepared: PreparedJudgment, report: ImportReport) -> None:
    status = prepared.row["source_status"]
    if status == SourceStatus.TEXT_AVAILABLE:
        report.text_available += 1
    elif status == SourceStatus.OCR_PENDING:
        report.ocr_pending += 1
    elif status == SourceStatus.CONVERSION_PENDING:
        report.conversion_pending += 1
    if prepared.html_boilerplate_discarded:
        report.html_boilerplate_discarded += 1
    report.pages_needing_review += prepared.pages_needing_review
    if prepared.pdf_check is not None:
        report.pdf[prepared.pdf_check.status.value] += 1
        if prepared.pdf_check.mime_type is not None:
            report.source_file_types[prepared.pdf_check.mime_type] += 1


def _finish_job(engine: Engine, job_id: uuid.UUID, status: JobStatus, report: ImportReport) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(JOBS)
            .where(JOBS.c.id == job_id)
            .values(
                status=status.value,
                finished_at=datetime.now(UTC),
                counts=report.as_dict(),
            )
        )
