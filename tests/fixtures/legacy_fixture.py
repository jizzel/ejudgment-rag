"""Deterministic synthetic stand-in for ``output/pdf/judgments_with_text.db``.

Generated at test time: no binaries in Git and no real corpus text. The rows reproduce the
traps found in the real export (``Copy`` suffixes, viewer boilerplate, shared PDF paths,
missing files, non-Ghanaian URIs, invalid and duplicate URLs, unparseable dates).
"""

import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROW_COUNT = 100

COLUMNS = [
    "citation",
    "media_neutral_citation",
    "court",
    "judges",
    "judgment_date",
    "language",
    "pdf_download_link",
    "full_text",
    "url",
    "scrape_timestamp",
    "jurisdiction",
    "case_number",
    "court_registry",
    "hearing_date",
    "civil_motion",
    "civil_case",
    "criminal_case",
    "attorneys",
    "pdf_local_path",
    "pdf_text",
    "pdf_extraction_status",
    "pdf_text_length",
]

VIEWER_BOILERPLATE = (
    "Skip to document content\nPages\nSearch\nLoading PDF...\n"
    "This document is 338.5 KB. Do you want to load it?\nLoad document\nError loading PDF\n"
    "Try reloading the page or downloading the PDF.\nReload page\nDownload PDF\nError:"
)

# Row numbers (0-based) with special cases.
ROW_MISSING_MARKERS = 1
ROW_REAL_HTML = 2
ROW_SCANNED_PDF = 3
ROW_NO_SOURCE = 4
ROW_SHARED_OWNER = 5
ROW_SHARED_OTHER = 6
ROW_MISSING_FILE = 7
ROW_AU = 8
ROW_REGIONAL = 9
ROW_INVALID_URL = 10
ROW_DUPLICATE_IDENTICAL = 11  # exact copy of row 0
ROW_CONFLICT_A = 13
ROW_CONFLICT_B = 14  # same URL as row 13, different content
ROW_BAD_DATE = 15
ROW_PATH_ESCAPE = 16
ROW_DOCX_AS_PDF = 17  # a Word file saved with a .pdf name, no legacy text
ROW_TEXT_TWIN_A = 18
ROW_TEXT_TWIN_B = 19  # different URI, identical judgment text (re-published judgment)
ROW_NUL_BYTES = 20  # extraction debris PostgreSQL cannot store
# Same parties, shared truncated filename, no legacy text: only the citation printed in the
# surviving file says which record it belongs to.
ROW_SAME_PARTIES_OWNER = 21
ROW_SAME_PARTIES_OTHER = 22
# No legacy text, but the PDF itself has machine-readable text on two pages (plus a blank one).
ROW_READABLE_PDF_NO_TEXT = 23
# Same URI and content as row 25; differs only in missing-value markers, the "Copy" suffix
# and scrape time. It is a duplicate to skip, not a conflict.
ROW_DUPLICATE_NORMALIZED = 24
ROW_DUPLICATE_NORMALIZED_ORIGINAL = 25

EXPECTED = {
    "rows_read": 100,
    # 2 without any usable source, invalid URL, two conflicting duplicates
    "quarantined": 5,
    "skipped_duplicate": 2,
    "accepted": 93,
    "judgments_written": 95,  # accepted + the 2 no-source records (stored as quarantined)
}

_WORDS = (
    "appellant respondent contract tenancy damages negligence estoppel mortgage customary "
    "succession trespass injunction declaration probate partnership lease evidence"
).split()


@dataclass(frozen=True)
class LegacyFixture:
    db_path: Path
    base_dir: Path


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(lines: list[str], *more_pages: list[str]) -> bytes:
    """A minimal PDF with Helvetica text that pypdf can extract; one page per line list."""
    pages = [lines, *more_pages]
    font_number = 3 + 2 * len(pages)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{3 + 2 * i} 0 R".encode() for i in range(len(pages)))
        + f"] /Count {len(pages)} >>".encode(),
    ]
    for index, page_lines in enumerate(pages):
        content_lines = ["BT", "/F1 10 Tf", "14 TL", "50 780 Td"]
        content_lines += [f"({_pdf_escape(line)}) Tj T*" for line in page_lines]
        content_lines.append("ET")
        stream = "\n".join(content_lines).encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
            f"/Resources << /Font << /F1 {font_number} 0 R >> >> "
            f"/Contents {4 + 2 * index} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _judgment_text(index: int) -> str:
    words = [_WORDS[(index * 7 + n) % len(_WORDS)] for n in range(60)]
    unique = [f"marker{index}x{n}" for n in range(25)]
    lines = [
        f"IN THE SUPERIOR COURT OF JUDICATURE CASE {index}",
        " ".join(unique),
        " ".join(words),
        f"Judgment delivered in synthetic matter number {index}.",
    ]
    return "\n".join(lines)


def _base_row(index: int) -> dict[str, Any]:
    day = date(2020, 1, 1) + timedelta(days=index)
    date_text = f"{day.day} {day.strftime('%B')} {day.year}"
    title = f"Party{index} Vrs Other{index}"
    number = index + 1
    return {
        "citation": f"{title} (J1/{number}/2020) [2020] GHASC {number} ({date_text})Copy",
        "media_neutral_citation": f"[2020] GHASC {number}Copy",
        "court": "Supreme Court",
        "judges": (
            f"Judge{index}A, JSC,\n      \n      Judge{index}B, JSC,\n   \n  Judge{index}C, JSC"
        ),
        "judgment_date": date_text,
        "language": "English",
        "pdf_download_link": f"https://example.invalid/source/{number}.pdf",
        "full_text": VIEWER_BOILERPLATE,
        "url": f"https://ghalii.org/akn/gh/judgment/ghasc/2020/{number}/eng@{day.isoformat()}",
        "scrape_timestamp": "2025-10-16T23:51:48",
        "jurisdiction": None,
        "case_number": f"J1/{number}/2020",
        "court_registry": None,
        "hearing_date": None,
        "civil_motion": None,
        "civil_case": None,
        "criminal_case": None,
        "attorneys": None,
        "pdf_local_path": f"output/pdf/downloaded_pdfs_2020/{title}.pdf",
        "pdf_text": _judgment_text(index),
        "pdf_extraction_status": "success",
        "pdf_text_length": None,
    }


def build_rows() -> list[dict[str, Any]]:
    rows = [_base_row(index) for index in range(ROW_COUNT)]
    for row in rows:
        row["pdf_text_length"] = len(row["pdf_text"])

    missing = rows[ROW_MISSING_MARKERS]
    missing.update(court="N/A", judges="N/A", case_number="", language=" ", hearing_date=None)

    rows[ROW_REAL_HTML]["full_text"] = (
        "Skip to document content\nSummary\nTable of contents\nSearch\n"
        "IN THE SUPREME COURT\nThe appeal is allowed. Synthetic HTML judgment body."
    )

    scanned = rows[ROW_SCANNED_PDF]
    scanned.update(pdf_text=None, pdf_extraction_status="extraction_failed", pdf_text_length=None)

    no_source = rows[ROW_NO_SOURCE]
    no_source.update(
        pdf_text=None,
        pdf_extraction_status="download_failed",
        pdf_text_length=None,
        pdf_local_path=None,
    )

    shared_path = "output/pdf/downloaded_pdfs_2020/Truncated_shared_name.pdf"
    rows[ROW_SHARED_OWNER]["pdf_local_path"] = shared_path
    rows[ROW_SHARED_OTHER]["pdf_local_path"] = shared_path

    rows[ROW_MISSING_FILE]["pdf_local_path"] = "output/pdf/downloaded_pdfs_2020/not_there.pdf"

    au = rows[ROW_AU]
    au.update(
        url="https://ghalii.org/akn/aa-au/judgment/afchpr/2020/9/eng@2020-01-09",
        court="African Court on Human and Peoples Rights",
        citation=(
            "XYZ v Republic of Benin (Application No. 009/2020) "
            "[2020] AfCHPR 9 (9 January 2020)Copy"
        ),
        media_neutral_citation="[2020] AfCHPR 9Copy",
        case_number="Application No. 009/2020\n          ;\n        \n          APP/2/20",
    )

    rows[ROW_REGIONAL].update(
        url="https://ghalii.org/akn/gh-hr-accra/judgment/ghahc/2020/10/eng@2020-01-10",
        court="Accra",
    )

    rows[ROW_INVALID_URL]["url"] = "https://ghalii.org/judgments/all/2020/"

    rows[ROW_DUPLICATE_IDENTICAL] = dict(rows[0])

    conflict_b = rows[ROW_CONFLICT_B]
    conflict_b["url"] = rows[ROW_CONFLICT_A]["url"]
    conflict_b["citation"] = "Someone Else Vrs Another [2020] GHASC 999 (14 January 2020)Copy"

    rows[ROW_BAD_DATE]["judgment_date"] = "3 March 201120 July 20113 March 2011"

    rows[ROW_PATH_ESCAPE]["pdf_local_path"] = "../../etc/passwd"

    rows[ROW_DOCX_AS_PDF].update(
        pdf_text=None, pdf_extraction_status="extraction_failed", pdf_text_length=None
    )

    rows[ROW_TEXT_TWIN_B]["pdf_text"] = rows[ROW_TEXT_TWIN_A]["pdf_text"]

    rows[ROW_NUL_BYTES]["pdf_text"] += "\nCOUNSEL FOR THE RESPONDENT\x00\t23"
    rows[ROW_NUL_BYTES]["attorneys"] = "A. Mensah\x00"

    shared_same_parties = "output/pdf/downloaded_pdfs_2020/Party21_Vrs_Other21_truncated.pdf"
    for index in (ROW_SAME_PARTIES_OWNER, ROW_SAME_PARTIES_OTHER):
        number = index + 1
        rows[index].update(
            citation=f"Party21 Vrs Other21 (J1/{number}/2020) [2020] GHASC {number} (x)Copy",
            pdf_text=None,
            pdf_extraction_status="extraction_failed",
            pdf_text_length=None,
            pdf_local_path=shared_same_parties,
        )

    rows[ROW_READABLE_PDF_NO_TEXT].update(
        pdf_text=None, pdf_extraction_status="extraction_failed", pdf_text_length=None
    )

    original = rows[ROW_DUPLICATE_NORMALIZED_ORIGINAL]
    original["court"] = "N/A"
    duplicate = dict(original)
    duplicate.update(
        court="",
        citation=original["citation"].removesuffix("Copy"),
        scrape_timestamp="2025-10-17T08:00:00",
    )
    rows[ROW_DUPLICATE_NORMALIZED] = duplicate
    return rows


def make_docx(path: Path) -> None:
    """A minimal zip with the Word layout; enough for file-type detection."""
    fixed_time = (2020, 1, 1, 0, 0, 0)  # constant timestamps keep the file's hash stable
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("[Content_Types].xml", fixed_time), "<Types/>")
        archive.writestr(zipfile.ZipInfo("word/document.xml", fixed_time), "<w:document/>")


def write_pdfs(rows: list[dict[str, Any]], base_dir: Path) -> None:
    written: set[str] = set()
    for index, row in enumerate(rows):
        path = row["pdf_local_path"]
        if path is None or index in (ROW_MISSING_FILE, ROW_PATH_ESCAPE) or path in written:
            continue
        if index == ROW_SCANNED_PDF:
            # No legacy text: verification falls back to the party names in the PDF.
            lines = [f"Party{index} Vrs Other{index}", "Scanned judgment cover page"]
        elif index == ROW_SAME_PARTIES_OWNER:
            lines = ["Party21 Vrs Other21", "[2020] GHASC 22", "Scanned judgment cover page"]
        elif index == ROW_READABLE_PDF_NO_TEXT:
            target = base_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            body = _judgment_text(index).splitlines()
            target.write_bytes(make_pdf(["[2020] GHASC 24", *body[:2]], body[2:], []))
            written.add(path)
            continue
        else:
            lines = (row["pdf_text"] or "").splitlines()
        target = base_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if index == ROW_DOCX_AS_PDF:
            make_docx(target)
        else:
            target.write_bytes(make_pdf(lines))
        written.add(path)


def build_legacy_fixture(directory: Path) -> LegacyFixture:
    rows = build_rows()
    db_path = directory / "judgments_with_text.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(f"CREATE TABLE judgments ({', '.join(f'{c} TEXT' for c in COLUMNS)})")
        conn.executemany(
            f"INSERT INTO judgments VALUES ({', '.join('?' for _ in COLUMNS)})",
            [tuple(row[column] for column in COLUMNS) for row in rows],
        )
    conn.close()
    write_pdfs(rows, directory)
    return LegacyFixture(db_path=db_path, base_dir=directory)
