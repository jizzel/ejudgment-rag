"""Text quality checks. They flag problems for review; they never drop text on their own.

The legacy export's HTML ``full_text`` was captured from GhaLII's page, so it starts with
site navigation labels and, for PDF-backed judgments, consists only of the embedded PDF
viewer's labels ("Loading PDF… Download PDF…"). That viewer text is not judgment text.
"""

import re
from dataclasses import dataclass, field

# Navigation labels that precede the document body on every captured page.
_NAVIGATION_LINES = frozenset(
    {"Skip to document content", "Summary", "Table of contents", "Pages", "Search"}
)
# Labels of the embedded PDF viewer.
_VIEWER_LINES = frozenset(
    {
        "Loading PDF...",
        "Load document",
        "Error loading PDF",
        "Try reloading the page or downloading the PDF.",
        "Reload page",
        "Download PDF",
        "Error:",
    }
)
_VIEWER_SIZE_PROMPT = re.compile(r"^This document is [\d.,]+\s*[KMG]?B\. Do you want to load it\?$")
_REPLACEMENT_CHAR = "�"
_REPLACEMENT_RATIO_LIMIT = 0.01
# Typical UTF-8 decoded as Latin-1/CP1252 artefacts, e.g. "Â" or "â€™".
_MOJIBAKE = re.compile(r"Â|â€")


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _is_chrome_line(line: str) -> bool:
    return (
        line in _NAVIGATION_LINES or line in _VIEWER_LINES or bool(_VIEWER_SIZE_PROMPT.match(line))
    )


def is_viewer_boilerplate(text: str | None) -> bool:
    """True when the text is only page navigation and PDF-viewer labels."""
    if not text:
        return False
    lines = _lines(text)
    return bool(lines) and all(_is_chrome_line(line) for line in lines)


def strip_leading_navigation(text: str) -> tuple[str, bool]:
    """Remove the site navigation lines that precede the document body.

    Only leading navigation labels are removed; the document body is returned unchanged.
    Returns the text and whether anything was removed.
    """
    lines = text.splitlines()
    index = 0
    while index < len(lines) and (
        not lines[index].strip() or lines[index].strip() in _NAVIGATION_LINES
    ):
        index += 1
    if index == 0:
        return text, False
    return "\n".join(lines[index:]).strip(), True


@dataclass(frozen=True)
class QualityReport:
    flags: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.flags)


def assess_text(text: str) -> QualityReport:
    flags: list[str] = []
    stripped = text.strip()
    if not stripped:
        return QualityReport(flags=["empty"])
    if stripped.count(_REPLACEMENT_CHAR) / len(stripped) > _REPLACEMENT_RATIO_LIMIT:
        flags.append("replacement_characters")
    if _MOJIBAKE.search(stripped):
        flags.append("mojibake")
    if is_viewer_boilerplate(stripped):
        flags.append("viewer_boilerplate")
    return QualityReport(flags=flags)
