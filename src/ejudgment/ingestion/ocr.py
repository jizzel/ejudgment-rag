"""Page-level OCR for scanned PDFs with the Tesseract CLI.

System prerequisites (macOS): ``brew install tesseract poppler``. Pages are rendered with
poppler's ``pdftoppm`` and recognised with ``tesseract ... tsv``; the TSV gives both the
text (rebuilt line by line) and per-word confidences, so each page needs one OCR pass.
Tests use :class:`FakeOcr`.
"""

import csv
import io
import statistics
import subprocess
import tempfile
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ejudgment.config import Settings


class OcrError(Exception):
    """Rendering or recognition failed."""


@dataclass(frozen=True)
class OcrPage:
    page_index: int  # 0-based physical page
    text: str
    mean_confidence: float | None  # mean word confidence 0-100; None when no words


class OcrEngine(Protocol):
    @property
    def name(self) -> str: ...

    def ocr_pdf(self, path: Path) -> list[OcrPage]: ...


def parse_tsv(tsv: str) -> tuple[str, float | None]:
    """Text and mean word confidence from ``tesseract ... tsv`` output.

    Words (level 5) are joined by spaces within a line; lines by newlines within a paragraph;
    paragraphs and blocks by blank lines.
    """
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5":
            continue
        word = (row.get("text") or "").strip()
        conf = float(row.get("conf") or -1)
        if not word or conf < 0:
            continue
        key = (int(row["block_num"]), int(row["par_num"]), int(row["line_num"]))
        lines.setdefault(key, []).append(word)
        confidences.append(conf)
    paragraphs: dict[tuple[int, int], list[str]] = {}
    for (block, par, _), words in sorted(lines.items()):
        paragraphs.setdefault((block, par), []).append(" ".join(words))
    text = "\n\n".join("\n".join(lines_) for _, lines_ in sorted(paragraphs.items()))
    mean = round(statistics.fmean(confidences), 2) if confidences else None
    return text, mean


class TesseractOcr:
    def __init__(self, settings: Settings) -> None:
        self._tesseract = settings.tesseract_cmd
        self._pdftoppm = settings.pdftoppm_cmd
        self._dpi = settings.ocr_dpi
        self._language = settings.ocr_language
        self._workers = settings.ocr_workers
        self._name = f"tesseract {self.version()} ({self._language}, {self._dpi} dpi)"
        self._check_pdftoppm()

    @property
    def name(self) -> str:
        return self._name

    def version(self) -> str:
        try:
            result = subprocess.run(
                [self._tesseract, "--version"], capture_output=True, text=True, check=True
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise OcrError(
                f"{self._tesseract!r} is not usable; install it (brew install tesseract)"
            ) from exc
        return result.stdout.split()[1] if result.stdout.split() else "unknown"

    def _check_pdftoppm(self) -> None:
        # Fail before any work starts rather than on the first scan of a batch.
        try:
            subprocess.run([self._pdftoppm, "-v"], capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise OcrError(
                f"{self._pdftoppm!r} is not usable; install it (brew install poppler)"
            ) from exc

    @staticmethod
    def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(args, capture_output=True, text=True, check=False)
        except OSError as exc:  # the tool vanished or cannot be executed mid-run
            raise OcrError(f"cannot run {args[0]!r}: {exc}") from exc

    def _recognise(self, image: Path) -> tuple[str, float | None]:
        result = self._run(
            [self._tesseract, str(image), "stdout", "--psm", "1", "-l", self._language, "tsv"]
        )
        if result.returncode != 0:
            raise OcrError(f"tesseract failed on {image.name}: {result.stderr.strip()[:200]}")
        return parse_tsv(result.stdout)

    def ocr_pdf(self, path: Path) -> list[OcrPage]:
        with tempfile.TemporaryDirectory(prefix="ejudgment-ocr-") as directory:
            render = self._run(
                [self._pdftoppm, "-r", str(self._dpi), "-png", str(path), f"{directory}/page"]
            )
            if render.returncode != 0:
                raise OcrError(f"pdftoppm failed on {path}: {render.stderr.strip()[:200]}")
            # pdftoppm zero-pads page numbers to a common width, so name order is page order.
            images = sorted(Path(directory).glob("page-*.png"))
            with ThreadPoolExecutor(max_workers=self._workers) as pool:
                results = list(pool.map(self._recognise, images))
        return [
            OcrPage(page_index=index, text=text, mean_confidence=confidence)
            for index, (text, confidence) in enumerate(results)
        ]


class FakeOcr:
    """Deterministic OCR for tests: returns preset page texts for any file."""

    name = "fake-ocr"

    def __init__(self, pages: Sequence[str], confidence: float = 90.0) -> None:
        self._pages = list(pages)
        self._confidence = confidence

    def ocr_pdf(self, path: Path) -> list[OcrPage]:
        return [
            OcrPage(index, text, self._confidence if text.strip() else None)
            for index, text in enumerate(self._pages)
        ]
