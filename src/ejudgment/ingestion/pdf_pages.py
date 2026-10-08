"""Page-aware text extraction from local PDFs (machine-readable text only, no OCR)."""

import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from ejudgment.ingestion.pdf_verify import MIN_SAMPLE_CHARS, squash

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractedPage:
    page_index: int  # 0-based physical page in the PDF
    text: str
    nul_removed: bool


def extract_pdf_pages(path: Path) -> list[ExtractedPage] | None:
    """Text of every page, or ``None`` when the file cannot be read as a PDF.

    NUL characters are removed (PostgreSQL cannot store them) and reported per page.
    """
    try:
        reader = PdfReader(path)
        raw_pages = [page.extract_text() or "" for page in reader.pages]
    except (PyPdfError, ValueError, KeyError, TypeError, OSError) as exc:
        logger.warning("Could not extract text from %s: %s", path, exc)
        return None
    return [
        ExtractedPage(index, text.replace("\x00", ""), "\x00" in text)
        for index, text in enumerate(raw_pages)
    ]


def has_machine_readable_text(pages: list[ExtractedPage]) -> bool:
    """Enough extractable text that the document does not need OCR as a whole.

    Individual empty pages are flagged by quality checks and remain OCR candidates.
    """
    return len(squash("".join(page.text for page in pages))) >= MIN_SAMPLE_CHARS
