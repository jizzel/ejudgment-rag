import shutil
import uuid
from pathlib import Path

import pytest

from ejudgment.config import Settings
from ejudgment.domain.enums import PageReferenceStatus, VerificationStatus
from ejudgment.ingestion.chunk_service import _PageRow, select_source
from ejudgment.ingestion.docx_text import DocxError, docx_text
from ejudgment.ingestion.extract_service import verification_evidence
from ejudgment.ingestion.ocr import OcrError, TesseractOcr, parse_tsv
from ejudgment.ingestion.pdf_verify import PdfVerifier, is_placeholder_html
from tests.fixtures.legacy_fixture import (
    DOCX_PARAGRAPHS,
    PLACEHOLDER_HTML,
    make_docx,
    make_pdf,
)


def test_docx_text_keeps_order_tables_and_tabs(tmp_path: Path) -> None:
    path = tmp_path / "judgment.pdf"  # Word files arrive with a .pdf name
    make_docx(path, ["CORAM:\tKwame JSC", *DOCX_PARAGRAPHS])
    text = docx_text(path)
    assert text.split("\n\n") == ["CORAM:\tKwame JSC", *DOCX_PARAGRAPHS]
    assert text.endswith("docxmarker17 applies to the lease.")  # from the table cell


def test_docx_text_rejects_non_word_files(tmp_path: Path) -> None:
    path = tmp_path / "x.pdf"
    path.write_bytes(b"PK\x03\x04 not a zip")
    with pytest.raises(DocxError):
        docx_text(path)


TSV = "\n".join(
    [
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
        "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t",
        "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t96.5\tIN",
        "5\t1\t1\t1\t1\t2\t0\t0\t10\t10\t93.5\tTHE",
        "5\t1\t1\t1\t2\t1\t0\t0\t10\t10\t90\tSUPREME",
        "5\t1\t2\t1\t1\t1\t0\t0\t10\t10\t80\tJUDGMENT",
        "5\t1\t2\t1\t1\t2\t0\t0\t10\t10\t-1\t",
    ]
)


def test_parse_tsv_rebuilds_lines_paragraphs_and_confidence() -> None:
    text, confidence = parse_tsv(TSV)
    assert text == "IN THE\nSUPREME\n\nJUDGMENT"
    assert confidence == 90.0  # mean of 96.5, 93.5, 90, 80; blanks and -1 ignored


def test_parse_tsv_of_a_blank_page() -> None:
    assert parse_tsv(TSV.split("\n")[0]) == ("", None)


def test_placeholder_html_is_detected(tmp_path: Path) -> None:
    placeholder = tmp_path / "a.pdf"
    placeholder.write_text(PLACEHOLDER_HTML)
    judgment = tmp_path / "b.pdf"
    body = "<p>" + "The appellant appealed against the judgment of the High Court. " * 10 + "</p>"
    judgment.write_text(
        f"<!DOCTYPE html><html><head><title>J</title></head><body>{body}</body></html>"
    )
    assert is_placeholder_html(placeholder)
    assert not is_placeholder_html(judgment)
    check = PdfVerifier(tmp_path, pages=2, min_window_chars=1000, min_overlap=0.8).verify(
        "a.pdf", reference_text=None, title="Party v Other", path_shared=False
    )
    assert (check.status, check.reason) == (VerificationStatus.MISMATCH, "placeholder_page")


def test_verification_evidence() -> None:
    text = "IN THE COURT OF APPEAL\nMensah v Owusu\n[2005] GHACA 7\nJUDGMENT"
    assert verification_evidence(text, "[2005] GHACA 7", None) == "extracted_citation_match"
    assert verification_evidence(text, "[2005] GHACA 70", "Mensah v Owusu") == (
        "extracted_title_match"
    )
    assert verification_evidence(text, "[2005] GHACA 70", "Boateng v Asante") is None


def _row(page_index: int | None, method: str, verification: str = "verified") -> _PageRow:
    source = uuid.uuid5(uuid.NAMESPACE_URL, "pdf-source")
    return _PageRow(source, "pdf", verification, page_index, method, f"text {page_index}")


def test_select_source_with_ocr_and_converted_pages() -> None:
    ocr = select_source([_row(1, "ocr"), _row(0, "ocr")])
    assert ocr is not None
    assert ocr[2].page_reference_status is PageReferenceStatus.VERIFIED
    assert [page.page_index for page in ocr[2].pages] == [0, 1]
    pending = select_source([_row(0, "ocr", "unverified")])
    assert pending is not None and pending[2].page_reference_status is PageReferenceStatus.PENDING
    converted = select_source([_row(None, "converted")])
    assert converted is not None
    assert converted[1] == "pdf"
    assert converted[2].page_reference_status is PageReferenceStatus.UNKNOWN


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
def test_missing_pdftoppm_fails_before_any_work() -> None:
    with pytest.raises(OcrError, match="brew install poppler"):
        TesseractOcr(Settings(pdftoppm_cmd="/nonexistent/pdftoppm"))


@pytest.mark.skipif(
    not (shutil.which("tesseract") and shutil.which("pdftoppm")),
    reason="tesseract/pdftoppm not installed (brew install tesseract poppler)",
)
def test_real_tesseract_on_a_generated_page(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    path.write_bytes(
        make_pdf(["IN THE SUPREME COURT OF GHANA", "Mensah versus Owusu"], ["JUDGMENT"])
    )
    pages = TesseractOcr(Settings(ocr_workers=2)).ocr_pdf(path)
    assert [page.page_index for page in pages] == [0, 1]
    # Spacing differs between Tesseract builds (Debian 5.5.0 reads "J UDGMENT"): this checks the
    # pipeline (render, page order, text, confidence), not one engine's word segmentation.
    first, second = ("".join(page.text.split()) for page in pages)
    assert "SUPREMECOURT" in first and "Mensah" in first
    assert "JUDGMENT" in second
    assert pages[0].mean_confidence is not None and pages[0].mean_confidence > 50
