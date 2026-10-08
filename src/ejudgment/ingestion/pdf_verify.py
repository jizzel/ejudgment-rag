"""Check that a local PDF referenced by the legacy export really belongs to its record.

``pdf_local_path`` is a hint, not truth: the legacy scraper named files after citations
truncated to 100 characters, so different judgments can share (and overwrite) one file.
A PDF is ``verified`` only when its text matches the record's legacy text. Mismatches are
reported and excluded; they are never "fixed" by guessing.

Matching uses character n-grams over text reduced to ``[a-z0-9]``: the legacy extractor
often dropped spaces ("INTHESUPERIORCOURT"), so word-based comparison is unreliable, and
judgments share boilerplate, so plain word overlap is not distinctive enough.
"""

import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from ejudgment.domain.enums import VerificationStatus
from ejudgment.ingestion.hashing import sha256_file
from ejudgment.ingestion.normalize import parse_neutral_citation

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"[a-z0-9]{3,}")
_NON_ALNUM = re.compile(r"[^a-z0-9]")
GRAM_SIZE = 20
# Below this many normalized characters a PDF sample is treated as having no text.
MIN_SAMPLE_CHARS = 100


PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def sniff_mime_type(path: Path) -> str:
    """Detect the real file type from its leading bytes.

    The legacy scraper saved every download as ``.pdf``, but many are Word, RTF or HTML files.
    """
    with path.open("rb") as handle:
        head = handle.read(512)
    if head.startswith(b"%PDF-"):
        return PDF_MIME
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(path) as archive:
                if any(name.startswith("word/") for name in archive.namelist()):
                    return DOCX_MIME
        except zipfile.BadZipFile:
            pass
        return "application/zip"
    if head.startswith(b"{\\rtf"):
        return "application/rtf"
    if head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "application/msword"
    lowered = head.lstrip().lower()
    if lowered.startswith((b"<!doctype html", b"<html")):
        return "text/html"
    return "application/octet-stream"


def contains_neutral_citation(text: str, citation: str | None) -> bool:
    """True if ``text`` cites ``citation`` (e.g. ``[2020] GHASC 104``), tolerating spacing.

    ``[2020] GHASC 104`` does not match ``[2020] GHASC 1040``.
    """
    parsed = parse_neutral_citation(citation)
    if parsed is None:
        return False
    pattern = rf"\[?\s*{parsed.year}\s*\]?\s*{re.escape(parsed.court)}\s*{parsed.number}(?!\d)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def squash(text: str) -> str:
    """Lowercase and drop everything except ``[a-z0-9]``."""
    return _NON_ALNUM.sub("", text.lower())


def char_grams(text: str, size: int = GRAM_SIZE) -> set[str]:
    return {text[i : i + size] for i in range(len(text) - size + 1)}


def containment(reference: set[str], candidate: set[str]) -> float:
    """Share of the reference's tokens that also occur in the candidate."""
    if not reference:
        return 0.0
    return len(reference & candidate) / len(reference)


@dataclass(frozen=True)
class PdfCheck:
    status: VerificationStatus
    reason: str
    resolved_path: Path | None = None
    sha256: str | None = None
    score: float | None = None
    mime_type: str | None = None

    @property
    def is_pdf(self) -> bool:
        return self.mime_type == PDF_MIME


@dataclass(frozen=True)
class _PdfSample:
    sha256: str
    mime_type: str
    text: str
    readable: bool


class PdfVerifier:
    def __init__(
        self,
        base_dir: Path,
        *,
        pages: int,
        min_window_chars: int,
        min_overlap: float,
    ) -> None:
        self.base_dir = base_dir.resolve()
        self.pages = pages
        self.min_window_chars = min_window_chars
        self.min_overlap = min_overlap
        self._samples: dict[Path, _PdfSample] = {}

    def resolve(self, local_path: str) -> Path | None:
        """Resolve a path from the export, refusing anything outside ``base_dir``."""
        candidate = (self.base_dir / local_path).resolve()
        if not candidate.is_relative_to(self.base_dir):
            return None
        return candidate

    def _sample(self, path: Path) -> _PdfSample:
        cached = self._samples.get(path)
        if cached is not None:
            return cached
        digest = sha256_file(path)
        mime_type = sniff_mime_type(path)
        text_parts: list[str] = []
        readable = mime_type == PDF_MIME
        if readable:
            try:
                reader = PdfReader(path)
                for page in reader.pages[: self.pages]:
                    text_parts.append(page.extract_text() or "")
            except (PyPdfError, ValueError, KeyError, TypeError, OSError) as exc:
                logger.warning("Could not read PDF %s: %s", path, exc)
                readable = False
        sample = _PdfSample(
            sha256=digest, mime_type=mime_type, text="\n".join(text_parts), readable=readable
        )
        self._samples[path] = sample
        return sample

    def verify(
        self,
        local_path: str | None,
        *,
        reference_text: str | None,
        title: str | None,
        path_shared: bool,
        neutral_citation: str | None = None,
    ) -> PdfCheck:
        if local_path is None:
            return PdfCheck(VerificationStatus.NOT_APPLICABLE, "no_local_path")
        resolved = self.resolve(local_path)
        if resolved is None:
            return PdfCheck(VerificationStatus.MISSING, "path_outside_base_dir")
        if not resolved.is_file():
            return PdfCheck(VerificationStatus.MISSING, "file_not_found", resolved)

        sample = self._sample(resolved)
        pdf_tokens = tokens(sample.text)
        squashed = squash(sample.text)

        if reference_text and len(squashed) >= MIN_SAMPLE_CHARS:
            # The PDF's first pages must appear near the start of the record's full text.
            window = squash(reference_text)[: max(4 * len(squashed), self.min_window_chars)]
            score = containment(char_grams(squashed), char_grams(window))
            status = (
                VerificationStatus.VERIFIED
                if score >= self.min_overlap
                else VerificationStatus.MISMATCH
            )
            reason = "text_match" if status is VerificationStatus.VERIFIED else "text_mismatch"
            return PdfCheck(
                status, reason, resolved, sample.sha256, round(score, 4), sample.mime_type
            )

        # No legacy text to compare (typically a scanned PDF). The record's own neutral
        # citation in the file is distinguishing evidence, even when the path is shared.
        if contains_neutral_citation(sample.text, neutral_citation):
            return PdfCheck(
                VerificationStatus.VERIFIED,
                "citation_match",
                resolved,
                sample.sha256,
                mime_type=sample.mime_type,
            )

        # Party names are not distinguishing: the records sharing a truncated filename often
        # involve the same parties. They may verify a file only when no other record claims it.
        if title and pdf_tokens:
            score = containment(tokens(title), pdf_tokens)
            if score >= self.min_overlap:
                if path_shared:
                    return PdfCheck(
                        VerificationStatus.MISMATCH,
                        "shared_path_title_only",
                        resolved,
                        sample.sha256,
                        round(score, 4),
                        sample.mime_type,
                    )
                return PdfCheck(
                    VerificationStatus.VERIFIED,
                    "title_match",
                    resolved,
                    sample.sha256,
                    round(score, 4),
                    sample.mime_type,
                )
            status = VerificationStatus.MISMATCH if path_shared else VerificationStatus.UNVERIFIED
            return PdfCheck(
                status, "title_mismatch", resolved, sample.sha256, round(score, 4), sample.mime_type
            )

        if path_shared:
            # Several records point at this file and nothing proves it is this one.
            return PdfCheck(
                VerificationStatus.MISMATCH,
                "shared_path_unverifiable",
                resolved,
                sample.sha256,
                mime_type=sample.mime_type,
            )
        if sample.mime_type != PDF_MIME:
            reason = "not_a_pdf"
        elif sample.readable:
            reason = "no_reference_text"
        else:
            reason = "unreadable_pdf"
        return PdfCheck(
            VerificationStatus.UNVERIFIED,
            reason,
            resolved,
            sample.sha256,
            mime_type=sample.mime_type,
        )
