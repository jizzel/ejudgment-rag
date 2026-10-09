"""Chunk every eligible judgment's chosen source text into the ``chunks`` table.

Idempotent: a judgment whose chunks already carry the current ``chunker_version`` and the
hash of its current source text is skipped. Exactly one source is chunked per judgment so
the same text is never indexed twice.
"""

import logging
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, cast

from sqlalchemy import Engine, Table, delete, func, insert, select
from sqlalchemy.engine import Connection

from ejudgment.config import Settings
from ejudgment.domain.enums import (
    EligibilityStatus,
    ExtractionMethod,
    PageReferenceStatus,
    RightsStatus,
    SourceKind,
    VerificationStatus,
)
from ejudgment.domain.models import Chunk, DocumentPage, DocumentSource, Judgment
from ejudgment.ingestion.chunking import (
    SourcePage,
    SourceText,
    chunk_source,
    chunker_version,
)
from ejudgment.ingestion.hashing import sha256_text, stable_id
from ejudgment.ingestion.tokenizer import Tokenizer

logger = logging.getLogger(__name__)

JUDGMENTS = cast(Table, Judgment.__table__)
SOURCES = cast(Table, DocumentSource.__table__)
PAGES = cast(Table, DocumentPage.__table__)
CHUNKS = cast(Table, Chunk.__table__)

ELIGIBLE_RIGHTS = [status.value for status in RightsStatus if status.eligible]
_USABLE_FILE = (VerificationStatus.VERIFIED.value, VerificationStatus.UNVERIFIED.value)
# Extraction methods whose page_index is a real physical page of the file.
_PAGED_METHODS = (ExtractionMethod.PDF_TEXT.value, ExtractionMethod.OCR.value)


@dataclass
class ChunkReport:
    chunker_version: str
    judgments_seen: int = 0
    chunked: int = 0
    skipped_unchanged: int = 0
    no_text: int = 0
    chunks_written: int = 0
    chunks_deleted: int = 0
    max_tokens_seen: int = 0
    sources: Counter[str] = field(default_factory=Counter)
    page_reference_status: Counter[str] = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        for key in ("sources", "page_reference_status"):
            data[key] = dict(sorted(data[key].items()))
        return data


@dataclass(frozen=True)
class _PageRow:
    source_id: uuid.UUID
    kind: str
    verification_status: str
    page_index: int | None
    extraction_method: str
    text: str


def select_source(pages: list[_PageRow]) -> tuple[uuid.UUID, str, SourceText] | None:
    """Pick one source per judgment: the file's own text (PDF, OCR or converted Word)
    > legacy text > HTML text."""
    by_source: dict[uuid.UUID, list[_PageRow]] = defaultdict(list)
    for page in pages:
        by_source[page.source_id].append(page)

    def rank(rows: list[_PageRow]) -> int:
        kind = rows[0].kind
        if kind == SourceKind.PDF.value and rows[0].verification_status in _USABLE_FILE:
            return 0
        if kind == SourceKind.LEGACY.value:
            return 1
        if kind == SourceKind.HTML.value:
            return 2
        return 99

    candidates = sorted(
        (rows for rows in by_source.values() if rank(rows) < 99),
        key=lambda rows: (rank(rows), str(rows[0].source_id)),
    )
    if not candidates:
        return None
    rows = candidates[0]
    paged = all(row.page_index is not None for row in rows)
    if rows[0].kind == SourceKind.PDF.value and paged:
        # Machine-readable or OCR pages of the file: real physical page numbers.
        rows = sorted(rows, key=lambda row: row.page_index if row.page_index is not None else -1)
        status = (
            PageReferenceStatus.VERIFIED
            if rows[0].verification_status == VerificationStatus.VERIFIED.value
            and all(row.extraction_method in _PAGED_METHODS for row in rows)
            else PageReferenceStatus.PENDING
        )
    else:
        # Legacy, HTML or converted (Word) text: no page mapping.
        status = PageReferenceStatus.UNKNOWN
    source = SourceText([SourcePage(row.text, row.page_index) for row in rows], status)
    return rows[0].source_id, rows[0].kind, source


def _load_pages(conn: Connection, judgment_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[_PageRow]]:
    rows = conn.execute(
        select(
            SOURCES.c.judgment_id,
            SOURCES.c.id,
            SOURCES.c.kind,
            SOURCES.c.verification_status,
            PAGES.c.page_index,
            PAGES.c.extraction_method,
            PAGES.c.text,
        )
        .join(PAGES, PAGES.c.source_id == SOURCES.c.id)
        .where(
            SOURCES.c.judgment_id.in_(judgment_ids),
            SOURCES.c.rights_status.in_(ELIGIBLE_RIGHTS),
        )
    )
    pages: dict[uuid.UUID, list[_PageRow]] = defaultdict(list)
    for row in rows:
        pages[row.judgment_id].append(
            _PageRow(
                row.id,
                row.kind,
                row.verification_status,
                row.page_index,
                row.extraction_method,
                row.text,
            )
        )
    return pages


def _existing_state(
    conn: Connection, judgment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, str]]:
    rows = conn.execute(
        select(
            CHUNKS.c.judgment_id,
            func.min(CHUNKS.c.chunker_version).label("version"),
            func.min(CHUNKS.c.source_text_hash).label("text_hash"),
            func.count(func.distinct(CHUNKS.c.chunker_version)).label("versions"),
        )
        .where(CHUNKS.c.judgment_id.in_(judgment_ids))
        .group_by(CHUNKS.c.judgment_id)
    )
    # A judgment with mixed versions (an interrupted run) never counts as up to date.
    return {row.judgment_id: (row.version, row.text_hash) for row in rows if row.versions == 1}


def run_chunking(
    engine: Engine,
    tokenizer: Tokenizer,
    settings: Settings,
    *,
    limit: int | None = None,
    judgment_uri: str | None = None,
    batch_size: int = 200,
) -> ChunkReport:
    version = chunker_version(tokenizer, settings.chunk_target_tokens, settings.chunk_max_tokens)
    report = ChunkReport(chunker_version=version)

    with engine.begin() as conn:
        # Judgments that are no longer eligible lose their chunks.
        stale = conn.execute(
            delete(CHUNKS).where(
                CHUNKS.c.judgment_id.in_(
                    select(JUDGMENTS.c.id).where(
                        JUDGMENTS.c.eligibility_status != EligibilityStatus.ELIGIBLE.value
                    )
                )
            )
        )
        report.chunks_deleted += stale.rowcount

        query = (
            select(JUDGMENTS.c.id)
            .where(JUDGMENTS.c.eligibility_status == EligibilityStatus.ELIGIBLE.value)
            .order_by(JUDGMENTS.c.id)
        )
        if judgment_uri is not None:
            query = query.where(JUDGMENTS.c.canonical_uri == judgment_uri)
        if limit is not None:
            query = query.limit(limit)
        judgment_ids = list(conn.execute(query).scalars())

    for start in range(0, len(judgment_ids), batch_size):
        batch = judgment_ids[start : start + batch_size]
        with engine.begin() as conn:
            pages = _load_pages(conn, batch)
            existing = _existing_state(conn, batch)
            for judgment_id in batch:
                report.judgments_seen += 1
                _chunk_judgment(
                    conn, judgment_id, pages.get(judgment_id, []), existing, tokenizer,
                    settings, version, report,
                )  # fmt: skip
        logger.info("Chunked %d/%d judgments", report.judgments_seen, len(judgment_ids))
    return report


def _chunk_judgment(
    conn: Connection,
    judgment_id: uuid.UUID,
    pages: list[_PageRow],
    existing: dict[uuid.UUID, tuple[str, str]],
    tokenizer: Tokenizer,
    settings: Settings,
    version: str,
    report: ChunkReport,
) -> None:
    selected = select_source(pages)
    if selected is None:
        report.no_text += 1
        if judgment_id in existing:
            result = conn.execute(delete(CHUNKS).where(CHUNKS.c.judgment_id == judgment_id))
            report.chunks_deleted += result.rowcount
        return
    source_id, kind, source = selected
    text_hash = sha256_text(source.text)
    report.sources[kind] += 1
    if existing.get(judgment_id) == (version, text_hash):
        report.skipped_unchanged += 1
        return

    drafts = chunk_source(
        source,
        tokenizer,
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
    )
    # Replace unconditionally: this also clears chunks left by an interrupted earlier run.
    result = conn.execute(delete(CHUNKS).where(CHUNKS.c.judgment_id == judgment_id))
    report.chunks_deleted += result.rowcount
    if drafts:
        conn.execute(
            insert(CHUNKS),
            [
                {
                    "id": stable_id(str(judgment_id), version, str(draft.ordinal)),
                    "judgment_id": judgment_id,
                    "source_id": source_id,
                    "ordinal": draft.ordinal,
                    "section_label": draft.section_label,
                    "page_start": draft.page_start,
                    "page_end": draft.page_end,
                    "page_reference_status": draft.page_reference_status.value,
                    "paragraph_refs": draft.paragraph_refs,
                    "char_start": draft.char_start,
                    "char_end": draft.char_end,
                    "content": draft.content,
                    "content_hash": draft.content_hash,
                    "token_count": draft.token_count,
                    "chunker_version": version,
                    "source_text_hash": text_hash,
                }
                for draft in drafts
            ],
        )
    report.chunked += 1
    report.chunks_written += len(drafts)
    for draft in drafts:
        report.page_reference_status[draft.page_reference_status.value] += 1
        report.max_tokens_seen = max(report.max_tokens_seen, draft.token_count)
