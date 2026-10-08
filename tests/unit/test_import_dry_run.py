from collections import Counter

from ejudgment.config import Settings
from ejudgment.domain.enums import SourceStatus, VerificationStatus
from ejudgment.ingestion.legacy_adapter import LegacyExport
from ejudgment.ingestion.pdf_verify import PdfVerifier
from ejudgment.ingestion.service import (
    _content_fingerprint,
    _pre_pass,
    prepare_record,
    run_legacy_import,
)
from tests.fixtures import legacy_fixture as fx


def test_dry_run_report(legacy_fixture: fx.LegacyFixture, settings: Settings) -> None:
    report = run_legacy_import(
        legacy_fixture.db_path, legacy_fixture.base_dir, settings, engine=None, dry_run=True
    )
    assert report.rows_read == fx.EXPECTED["rows_read"]
    assert report.accepted == fx.EXPECTED["accepted"]
    assert report.quarantined == fx.EXPECTED["quarantined"]
    assert report.skipped_duplicate == fx.EXPECTED["skipped_duplicate"]
    assert report.failed == 0
    assert (report.inserted, report.updated, report.skipped_unchanged) == (0, 0, 0)
    assert report.quarantine_reasons == Counter(
        {"invalid_akn_uri": 1, "duplicate_uri_conflict": 2, "no_usable_text_and_no_pdf": 2}
    )
    assert report.warnings["pdf_mismatch"] == 2
    assert report.warnings["pdf_missing"] == 2  # missing file + path outside base dir
    assert report.warnings["unparsed_judgment_date"] == 1
    assert report.ocr_pending == 2
    assert report.conversion_pending == 1
    assert report.warnings["duplicate_text_across_uris"] == 2
    assert (
        report.source_file_types[
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ]
        == 1
    )
    assert report.text_available == 90
    assert report.pdf == Counter({"verified": 89, "mismatch": 2, "missing": 2, "unverified": 1})
    assert report.warnings["duplicate_uri_identical"] == 2


def test_dry_run_is_deterministic(legacy_fixture: fx.LegacyFixture, settings: Settings) -> None:
    def run() -> dict[str, object]:
        report = run_legacy_import(
            legacy_fixture.db_path, legacy_fixture.base_dir, settings, engine=None, dry_run=True
        )
        return report.as_dict()

    assert run() == run()


def _prepare_all(fixture: fx.LegacyFixture, settings: Settings) -> dict[int, object]:
    export = LegacyExport(fixture.db_path)
    pre = _pre_pass(export.records())
    verifier = PdfVerifier(
        fixture.base_dir,
        pages=settings.pdf_verify_pages,
        min_window_chars=settings.pdf_verify_min_window_chars,
        min_overlap=settings.pdf_verify_min_overlap,
    )
    results: dict[int, object] = {}
    for index, record in enumerate(export.records()):
        results[index] = prepare_record(
            record, source_version="test", verifier=verifier, path_counts=pre.path_counts
        )
    return results


def test_record_level_outcomes(legacy_fixture: fx.LegacyFixture, settings: Settings) -> None:
    results = _prepare_all(legacy_fixture, settings)

    def judgment(index: int) -> dict[str, object]:
        prepared, _ = results[index]  # type: ignore[misc]
        assert prepared is not None
        return prepared.row  # type: ignore[no-any-return]

    def kinds(index: int) -> dict[str, str]:
        prepared, _ = results[index]  # type: ignore[misc]
        return {s.row["kind"]: s.row["verification_status"] for s in prepared.sources}

    base = judgment(0)
    assert base["citation"].endswith("(1 January 2020)")  # "Copy" stripped
    assert base["neutral_citation"] == "[2020] GHASC 1"
    assert base["title"] == "Party0 Vrs Other0"
    assert base["judges"] == ["Judge0A, JSC", "Judge0B, JSC", "Judge0C, JSC"]
    assert base["source_status"] == SourceStatus.TEXT_AVAILABLE
    assert "full_text" not in base["metadata_"]["legacy"]  # type: ignore[index]
    assert kinds(0) == {"legacy": "not_applicable", "pdf": "verified"}  # viewer HTML dropped

    missing = judgment(fx.ROW_MISSING_MARKERS)
    assert missing["court_name"] is None and missing["judges"] == []
    assert missing["case_number"] is None and missing["language"] is None

    assert "html" in kinds(fx.ROW_REAL_HTML)
    assert judgment(fx.ROW_SCANNED_PDF)["source_status"] == SourceStatus.OCR_PENDING
    assert judgment(fx.ROW_NO_SOURCE)["eligibility_status"] == "quarantined"
    assert kinds(fx.ROW_SHARED_OWNER)["pdf"] == VerificationStatus.VERIFIED
    assert kinds(fx.ROW_SHARED_OTHER)["pdf"] == VerificationStatus.MISMATCH
    assert kinds(fx.ROW_MISSING_FILE)["pdf"] == VerificationStatus.MISSING

    au = judgment(fx.ROW_AU)
    assert (au["jurisdiction"], au["court_code"]) == ("aa-au", "afchpr")
    assert au["case_number"] == "Application No. 009/2020; APP/2/20"
    assert judgment(fx.ROW_REGIONAL)["jurisdiction"] == "gh-hr-accra"
    assert judgment(fx.ROW_BAD_DATE)["judgment_date"] is None

    docx_prepared, _ = results[fx.ROW_DOCX_AS_PDF]  # type: ignore[misc]
    assert docx_prepared.row["source_status"] == SourceStatus.CONVERSION_PENDING
    (docx_source,) = [s for s in docx_prepared.sources if s.row["kind"] == "pdf"]
    assert docx_source.row["mime_type"].endswith("wordprocessingml.document")
    assert judgment(fx.ROW_TEXT_TWIN_A)["id"] != judgment(fx.ROW_TEXT_TWIN_B)["id"]

    nul_prepared, _ = results[fx.ROW_NUL_BYTES]  # type: ignore[misc]
    (nul_page,) = [p for s in nul_prepared.sources for p in s.pages]
    assert "\x00" not in nul_page["text"]
    assert "nul_characters_removed" in nul_page["quality_flags"]
    assert nul_prepared.row["metadata_"]["legacy"]["attorneys"] == "A. Mensah"

    # A shared file with the same party names on it belongs only to the record it cites.
    owner, _ = results[fx.ROW_SAME_PARTIES_OWNER]  # type: ignore[misc]
    other, other_issues = results[fx.ROW_SAME_PARTIES_OTHER]  # type: ignore[misc]
    assert kinds(fx.ROW_SAME_PARTIES_OWNER)["pdf"] == VerificationStatus.VERIFIED
    assert kinds(fx.ROW_SAME_PARTIES_OTHER)["pdf"] == VerificationStatus.MISMATCH
    assert owner.pdf_check.reason == "citation_match"
    assert other.pdf_check.reason == "shared_path_title_only"
    assert other.row["eligibility_status"] == "quarantined"

    # A readable PDF without legacy text is extracted page by page, not sent to OCR.
    readable, _ = results[fx.ROW_READABLE_PDF_NO_TEXT]  # type: ignore[misc]
    assert readable.row["source_status"] == SourceStatus.TEXT_AVAILABLE
    assert readable.pdf_check.reason == "citation_match"
    pdf_pages = [p for s in readable.sources if s.row["kind"] == "pdf" for p in s.pages]
    assert [p["page_index"] for p in pdf_pages] == [0, 1, 2]
    assert {p["extraction_method"] for p in pdf_pages} == {"pdf_text"}
    assert "GHASC 24" in pdf_pages[0]["text"]
    assert pdf_pages[2]["quality_flags"] == ["empty"]  # a blank page stays an OCR candidate
    assert len({p["id"] for p in pdf_pages}) == 3

    # A PDF without machine-readable text is still left for OCR.
    scanned, _ = results[fx.ROW_SCANNED_PDF]  # type: ignore[misc]
    assert all(not s.pages for s in scanned.sources)

    invalid, issues = results[fx.ROW_INVALID_URL]  # type: ignore[misc]
    assert invalid is None and issues[0].reason == "invalid_akn_uri"


def test_legacy_text_has_no_page_mapping(
    legacy_fixture: fx.LegacyFixture, settings: Settings
) -> None:
    prepared, _ = _prepare_all(legacy_fixture, settings)[0]  # type: ignore[misc]
    pages = [page for source in prepared.sources for page in source.pages]
    assert pages
    assert all(page["page_index"] is None for page in pages)
    assert all(page["extraction_method"] == "legacy" for page in pages)


def test_semantic_duplicates_are_skipped_not_conflicts(
    legacy_fixture: fx.LegacyFixture, settings: Settings
) -> None:
    export = LegacyExport(legacy_fixture.db_path)
    records = list(export.records())
    duplicate = records[fx.ROW_DUPLICATE_NORMALIZED]
    original = records[fx.ROW_DUPLICATE_NORMALIZED_ORIGINAL]
    assert duplicate.values != original.values  # raw rows differ...
    assert _content_fingerprint(duplicate) == _content_fingerprint(original)  # ...content doesn't

    pre = _pre_pass(records)
    uri = "/akn/gh/judgment/ghasc/2020/26/eng@2020-01-26"
    assert pre.uri_counts[uri] == 2
    assert uri not in pre.conflicting_uris


def test_real_content_difference_is_still_a_conflict(legacy_fixture: fx.LegacyFixture) -> None:
    records = list(LegacyExport(legacy_fixture.db_path).records())
    a, b = records[fx.ROW_CONFLICT_A], records[fx.ROW_CONFLICT_B]
    assert _content_fingerprint(a) != _content_fingerprint(b)
