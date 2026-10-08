from pathlib import Path

from ejudgment.ingestion.pdf_pages import extract_pdf_pages, has_machine_readable_text
from tests.fixtures.legacy_fixture import make_pdf

BODY = "The appellant's tenancy agreement was never registered with the Rent Control Department"


def test_extracts_each_page_with_its_physical_index(tmp_path: Path) -> None:
    path = tmp_path / "a.pdf"
    path.write_bytes(make_pdf(["Page one", BODY], ["Page two", BODY], []))
    pages = extract_pdf_pages(path)
    assert pages is not None
    assert [page.page_index for page in pages] == [0, 1, 2]
    assert "Page two" in pages[1].text
    assert pages[2].text.strip() == ""
    assert has_machine_readable_text(pages)


def test_scanned_like_pdf_has_no_machine_readable_text(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    path.write_bytes(make_pdf(["Cover"], []))
    pages = extract_pdf_pages(path)
    assert pages is not None
    assert not has_machine_readable_text(pages)


def test_unreadable_file_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\ntruncated")
    assert extract_pdf_pages(path) is None
