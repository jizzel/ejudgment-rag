from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, text

from ejudgment.config import Settings
from ejudgment.ingestion.chunk_service import run_chunking
from ejudgment.ingestion.extract_service import ExtractReport, run_extraction
from ejudgment.ingestion.ocr import FakeOcr, OcrPage
from ejudgment.ingestion.service import run_legacy_import
from ejudgment.ingestion.tokenizer import WhitespaceTokenizer
from tests.fixtures import legacy_fixture as fx
from tests.integration.conftest import alembic_config

pytestmark = pytest.mark.integration

# What the fake OCR "reads" from every scanned PDF: the scanned row's own citation on page 1,
# body text on page 2, and a blank page 3.
SCANNED_CITATION = f"[2020] GHASC {fx.ROW_SCANNED_PDF + 1}"
OCR_PAGES = [
    f"IN THE SUPREME COURT OF GHANA\n{SCANNED_CITATION}\nJUDGMENT\n" + "ocrmarker " * 30,
    "The appellant's tenancy was terminated. " * 20,
    "",
]


@pytest.fixture
def imported(
    legacy_fixture: fx.LegacyFixture, settings: Settings, migrated_engine: Engine
) -> Engine:
    run_legacy_import(
        legacy_fixture.db_path, legacy_fixture.base_dir, settings, engine=migrated_engine
    )
    return migrated_engine


def _extract(
    engine: Engine, fixture: fx.LegacyFixture, settings: Settings, pages: list[str] | None = None
) -> ExtractReport:
    return run_extraction(engine, settings, fixture.base_dir, FakeOcr(pages or OCR_PAGES))


def _row(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).one()


def _status(engine: Engine, title: str) -> Any:
    return _row(
        engine,
        "SELECT j.source_status, s.verification_status FROM judgments j "
        "JOIN document_sources s ON s.judgment_id = j.id AND s.kind = 'pdf' WHERE j.title = :t",
        t=title,
    )


def test_placeholder_download_is_quarantined(imported: Engine) -> None:
    row = _row(
        imported,
        "SELECT j.eligibility_status, j.source_status, s.verification_status, s.mime_type "
        "FROM judgments j JOIN document_sources s ON s.judgment_id = j.id AND s.kind = 'pdf' "
        "WHERE j.title = :t",
        t=f"Party{fx.ROW_PLACEHOLDER_HTML} Vrs Other{fx.ROW_PLACEHOLDER_HTML}",
    )
    assert tuple(row) == ("quarantined", "no_source", "mismatch", "text/html")
    reason = _row(
        imported,
        "SELECT details->>'reason' AS reason FROM ingestion_issues "
        "WHERE reason = 'pdf_mismatch' AND canonical_uri LIKE :u",
        u=f"%/ghasc/2020/{fx.ROW_PLACEHOLDER_HTML + 1}/%",
    ).reason
    assert reason == "placeholder_page"


def test_extraction_converts_word_and_ocrs_scans(
    imported: Engine, legacy_fixture: fx.LegacyFixture, settings: Settings
) -> None:
    scanned = f"Party{fx.ROW_SCANNED_PDF} Vrs Other{fx.ROW_SCANNED_PDF}"
    word = f"Party{fx.ROW_DOCX_AS_PDF} Vrs Other{fx.ROW_DOCX_AS_PDF}"
    # Pretend the scan could not be verified at import, so OCR evidence has to do it.
    with imported.begin() as conn:
        conn.execute(
            text(
                "UPDATE document_sources s SET verification_status = 'unverified' FROM judgments j "
                "WHERE j.id = s.judgment_id AND s.kind = 'pdf' AND j.title = :t"
            ),
            {"t": scanned},
        )
    assert tuple(_status(imported, scanned)) == ("ocr_pending", "unverified")
    assert tuple(_status(imported, word)) == ("conversion_pending", "unverified")

    report = _extract(imported, legacy_fixture, settings)
    assert (report.candidates, report.converted, report.ocr_documents) == (3, 1, 2)
    assert report.ocr_pages == 6 and report.still_pending == 0 and report.failed == 0
    assert report.verified_upgrades == 2  # the scan (own citation) and the Word file
    assert report.issues["verified_by_extracted_citation_match"] == 2
    assert tuple(_status(imported, scanned)) == ("text_available", "verified")
    assert tuple(_status(imported, word)) == ("text_available", "verified")

    with imported.connect() as conn:
        ocr = conn.execute(
            text(
                "SELECT p.page_index, p.extraction_method, p.ocr_confidence, p.quality_flags "
                "FROM document_pages p JOIN document_sources s ON s.id = p.source_id "
                "JOIN judgments j ON j.id = s.judgment_id WHERE j.title = :t "
                "ORDER BY p.page_index"
            ),
            {"t": scanned},
        ).all()
        converted = conn.execute(
            text(
                "SELECT p.page_index, p.extraction_method, p.text FROM document_pages p "
                "JOIN document_sources s ON s.id = p.source_id JOIN judgments j "
                "ON j.id = s.judgment_id WHERE j.title = :t AND s.kind = 'pdf'"
            ),
            {"t": word},
        ).one()
    assert [(r.page_index, r.extraction_method, r.ocr_confidence) for r in ocr] == [
        (0, "ocr", 90.0),
        (1, "ocr", 90.0),
        (2, "ocr", None),
    ]
    assert ocr[2].quality_flags == ["empty"]  # a blank page stays flagged for review
    assert (converted.page_index, converted.extraction_method) == (None, "converted")
    assert "docxmarker17" in converted.text

    # Idempotent, and a re-import of the unchanged export keeps the extracted pages.
    assert _extract(imported, legacy_fixture, settings).candidates == 0
    reimport = run_legacy_import(
        legacy_fixture.db_path, legacy_fixture.base_dir, settings, engine=imported
    )
    assert (reimport.inserted, reimport.updated) == (0, 0)
    assert tuple(_status(imported, scanned)) == ("text_available", "verified")

    # Chunks: OCR pages of a verified file give verified page bounds; Word text has none.
    run_chunking(imported, WhitespaceTokenizer(), settings)
    with imported.connect() as conn:
        chunks = {
            row.title: (row.status, row.page_start)
            for row in conn.execute(
                text(
                    "SELECT j.title, c.page_reference_status AS status, c.page_start "
                    "FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
                    "WHERE j.title IN (:a, :b) AND c.ordinal = 0"
                ),
                {"a": scanned, "b": word},
            )
        }
    assert chunks[scanned] == ("verified", 0)
    assert chunks[word] == ("unknown", None)


def test_low_confidence_pages_are_flagged(
    imported: Engine, legacy_fixture: fx.LegacyFixture, settings: Settings
) -> None:
    strict = settings.model_copy(update={"ocr_min_confidence": 95.0})
    report = _extract(imported, legacy_fixture, strict)
    assert report.low_confidence_pages == 4  # 2 scans x 2 pages with text at 90%
    with imported.connect() as conn:
        flagged = conn.execute(
            text(
                "SELECT count(*) FROM document_pages WHERE quality_flags ? 'low_ocr_confidence' "
                "AND quality_status = 'needs_review'"
            )
        ).scalar_one()
    assert flagged == 4


def test_no_text_keeps_the_record_pending(
    imported: Engine, legacy_fixture: fx.LegacyFixture, settings: Settings
) -> None:
    report = _extract(imported, legacy_fixture, settings, pages=["", "  "])
    assert report.still_pending == 2  # both scans; the Word file still converts
    assert report.issues["no_text_extracted"] == 2
    scanned = f"Party{fx.ROW_SCANNED_PDF} Vrs Other{fx.ROW_SCANNED_PDF}"
    assert _status(imported, scanned).source_status == "ocr_pending"


def test_changed_file_is_not_extracted(
    imported: Engine, legacy_fixture: fx.LegacyFixture, settings: Settings
) -> None:
    with imported.connect() as conn:
        local_path = conn.execute(
            text(
                "SELECT s.local_path FROM document_sources s JOIN judgments j "
                "ON j.id = s.judgment_id WHERE s.kind = 'pdf' AND j.title = :t"
            ),
            {"t": f"Party{fx.ROW_DOCX_AS_PDF} Vrs Other{fx.ROW_DOCX_AS_PDF}"},
        ).scalar_one()
    (legacy_fixture.base_dir / local_path).write_bytes(b"replaced after import")
    report = _extract(imported, legacy_fixture, settings)
    assert report.source_changed == 1 and report.converted == 0


def test_existing_pages_are_never_extracted_again(
    imported: Engine, legacy_fixture: fx.LegacyFixture, settings: Settings
) -> None:
    _extract(imported, legacy_fixture, settings)
    # A status reset (manual fix, partial restore) must not re-extract a file that has pages.
    with imported.begin() as conn:
        conn.execute(
            text("UPDATE judgments SET source_status = 'ocr_pending' WHERE title = :t"),
            {"t": f"Party{fx.ROW_SCANNED_PDF} Vrs Other{fx.ROW_SCANNED_PDF}"},
        )
    assert _extract(imported, legacy_fixture, settings).candidates == 0


class _CrashingOcr(FakeOcr):
    """Reads the first scan, then fails the way an unexpected error would."""

    def __init__(self) -> None:
        super().__init__(OCR_PAGES)
        self.calls = 0

    def ocr_pdf(self, path: Path) -> list[OcrPage]:
        self.calls += 1
        if self.calls > 1:
            raise FileNotFoundError(2, "No such file or directory", "pdftoppm")
        return super().ocr_pdf(path)


def test_aborted_run_is_recorded_as_failed(
    imported: Engine, legacy_fixture: fx.LegacyFixture, settings: Settings
) -> None:
    with pytest.raises(FileNotFoundError):
        run_extraction(imported, settings, legacy_fixture.base_dir, _CrashingOcr())
    job = _row(
        imported,
        "SELECT status, counts FROM ingestion_jobs WHERE kind = 'extract' ORDER BY started_at DESC "
        "LIMIT 1",
    )
    assert job.status == "failed"
    assert job.counts["aborted"].startswith("FileNotFoundError")
    assert job.counts["failed"] == 0  # no per-document failure: the batch itself stopped
    # Documents finished before the error keep their pages; a re-run picks up only the rest.
    assert job.counts["ocr_documents"] == 1
    done = job.counts["ocr_documents"] + job.counts["converted"]
    rerun = run_extraction(imported, settings, legacy_fixture.base_dir, FakeOcr(OCR_PAGES))
    assert rerun.candidates == job.counts["candidates"] - done
    assert rerun.ocr_documents == 1 and rerun.failed == 0


def _scan_pages(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT p.text, p.extractor_version FROM document_pages p "
                "JOIN document_sources s ON s.id = p.source_id JOIN judgments j "
                "ON j.id = s.judgment_id WHERE j.title = :t ORDER BY p.page_index"
            ),
            {"t": f"Party{fx.ROW_SCANNED_PDF} Vrs Other{fx.ROW_SCANNED_PDF}"},
        ).all()


def test_extractor_change_reextracts_only_its_pages(
    imported: Engine, legacy_fixture: fx.LegacyFixture, settings: Settings
) -> None:
    base = legacy_fixture.base_dir
    run_extraction(imported, settings, base, FakeOcr(OCR_PAGES, name="engine-a"))
    run_chunking(imported, WhitespaceTokenizer(), settings)
    assert {page.extractor_version for page in _scan_pages(imported)} == {"engine-a; psm1-tsv-v1"}

    # A new OCR engine version redoes the scans, not the Word file.
    upgraded = [OCR_PAGES[0], "The lease was renewed by upgradedmarker. " * 20]
    report = run_extraction(imported, settings, base, FakeOcr(upgraded, name="engine-b"))
    assert (report.candidates, report.reextracted, report.ocr_documents) == (2, 2, 2)
    assert report.converted == 0 and report.failed == 0
    pages = _scan_pages(imported)
    assert len(pages) == 2  # the old third page is gone, not left behind
    assert "upgradedmarker" in pages[1].text
    assert {page.extractor_version for page in pages} == {"engine-b; psm1-tsv-v1"}

    # Chunks follow the new text.
    run_chunking(imported, WhitespaceTokenizer(), settings)
    with imported.connect() as conn:
        rechunked = conn.execute(
            text("SELECT count(*) FROM chunks WHERE content LIKE '%upgradedmarker%'")
        ).scalar_one()
    assert rechunked > 0

    # Same engine again: nothing to do. An engine that reads nothing keeps the old pages.
    assert (
        run_extraction(imported, settings, base, FakeOcr(upgraded, name="engine-b")).candidates == 0
    )
    blank = run_extraction(imported, settings, base, FakeOcr(["", ""], name="engine-c"))
    assert blank.still_pending == 2 and blank.reextracted == 0
    assert {page.extractor_version for page in _scan_pages(imported)} == {"engine-b; psm1-tsv-v1"}
    scanned = f"Party{fx.ROW_SCANNED_PDF} Vrs Other{fx.ROW_SCANNED_PDF}"
    assert _status(imported, scanned).source_status == "text_available"


def test_threshold_change_only_reflags(
    imported: Engine, legacy_fixture: fx.LegacyFixture, settings: Settings
) -> None:
    _extract(imported, legacy_fixture, settings)  # 90% pages, default threshold 60

    def flagged() -> int:
        with imported.connect() as conn:
            return int(
                conn.execute(
                    text(
                        "SELECT count(*) FROM document_pages WHERE quality_flags ? "
                        "'low_ocr_confidence' AND quality_status = 'needs_review'"
                    )
                ).scalar_one()
            )

    strict = settings.model_copy(update={"ocr_min_confidence": 95.0})
    report = _extract(imported, legacy_fixture, strict)
    assert (report.candidates, report.reflagged_pages) == (0, 4)
    assert flagged() == 4
    report = _extract(imported, legacy_fixture, settings)
    assert (report.candidates, report.reflagged_pages) == (0, 4)
    assert flagged() == 0
    with imported.connect() as conn:
        statuses = conn.execute(
            text(
                "SELECT quality_status, count(*) FROM document_pages "
                "WHERE extraction_method = 'ocr' GROUP BY 1"
            )
        ).all()
    assert dict(statuses) == {"ok": 4, "needs_review": 2}  # the blank pages stay flagged


def test_extract_jobs_record_finished_at(
    imported: Engine, legacy_fixture: fx.LegacyFixture, settings: Settings
) -> None:
    with pytest.raises(FileNotFoundError):
        run_extraction(imported, settings, legacy_fixture.base_dir, _CrashingOcr())
    _extract(imported, legacy_fixture, settings)
    with imported.connect() as conn:
        jobs = conn.execute(
            text("SELECT status, finished_at FROM ingestion_jobs WHERE kind = 'extract'")
        ).all()
    assert sorted(job.status for job in jobs) == ["failed", "succeeded"]
    assert all(job.finished_at is not None for job in jobs)


def test_downgrade_removes_what_converted_pages_produced(
    imported: Engine, legacy_fixture: fx.LegacyFixture, settings: Settings, database_url: str
) -> None:
    _extract(imported, legacy_fixture, settings)
    run_chunking(imported, WhitespaceTokenizer(), settings)
    word = f"Party{fx.ROW_DOCX_AS_PDF} Vrs Other{fx.ROW_DOCX_AS_PDF}"
    scanned = f"Party{fx.ROW_SCANNED_PDF} Vrs Other{fx.ROW_SCANNED_PDF}"
    count_chunks = (
        "SELECT count(*) AS n FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
        "WHERE j.title = :t"
    )
    assert _row(imported, count_chunks, t=word).n > 0

    command.downgrade(alembic_config(database_url), "0004")
    assert _row(imported, count_chunks, t=word).n == 0
    assert _status(imported, word).source_status == "conversion_pending"
    assert (
        _row(
            imported,
            "SELECT count(*) AS n FROM document_pages WHERE extraction_method = 'converted'",
        ).n
        == 0
    )
    # OCR pages are valid before 0005 and keep their chunks.
    assert _row(imported, count_chunks, t=scanned).n > 0
    assert _status(imported, scanned).source_status == "text_available"


def test_upgrade_backfills_the_version_of_existing_pages(
    imported: Engine, legacy_fixture: fx.LegacyFixture, settings: Settings, database_url: str
) -> None:
    """Pages extracted before 0006 must not all be OCR'd again after upgrading."""
    _extract(imported, legacy_fixture, settings)
    config = alembic_config(database_url)
    command.downgrade(config, "0005")
    command.upgrade(config, "head")
    assert _extract(imported, legacy_fixture, settings).candidates == 0
