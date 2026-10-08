"""Pure normalization helpers for legacy export rows.

Rules: missing values become ``None`` (never invented); nothing here guesses a value that
the source does not state.
"""

import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

MISSING_MARKERS = frozenset({"", "n/a", "na", "nan", "none", "null"})

# GhaLII renders a "Copy" button next to citations; the legacy scraper captured its label.
_COPY_SUFFIX = re.compile(r"\s*Copy\s*$")
_WHITESPACE = re.compile(r"\s+")
_NEUTRAL_CITATION = re.compile(r"\[(\d{4})\]\s+([A-Za-z][A-Za-z0-9]*)\s+(\d+)")
_AKN_PATH = re.compile(
    r"^/akn/(?P<jurisdiction>[a-z0-9-]+)/judgment/(?P<court>[a-z0-9-]+)/"
    r"(?P<year>\d{4})/(?P<number>[A-Za-z0-9-]+)/(?P<language>[a-z]{3})@(?P<expr_date>\d{4}-\d{2}-\d{2})/?$"
)


def has_nul(value: Any) -> bool:
    return isinstance(value, str) and "\x00" in value


def clean_value(value: Any) -> Any:
    """Map the export's missing markers (``N/A``, NaN, empty, whitespace) to ``None``.

    NUL characters (PDF extraction debris) are removed: PostgreSQL text and JSONB cannot
    store them. Callers flag affected text with :func:`has_nul` before cleaning.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        stripped = value.replace("\x00", "").strip()
        if stripped.lower() in MISSING_MARKERS:
            return None
        return stripped
    return value


def clean_text(value: Any) -> str | None:
    cleaned = clean_value(value)
    return None if cleaned is None else str(cleaned)


def collapse_whitespace(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def strip_copy_suffix(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = _COPY_SUFFIX.sub("", value).strip()
    return stripped or None


def normalize_citation(citation: str) -> str:
    """Case-insensitive, punctuation-free form used for exact/fuzzy citation lookup.

    ``"Lomotey v Richardson [2022] GHASC 65 (15 June 2022)"`` ->
    ``"LOMOTEY V RICHARDSON 2022 GHASC 65 15 JUNE 2022"``.
    """
    upper = citation.upper()
    no_punct = re.sub(r"[^\w\s]", " ", upper)
    return collapse_whitespace(no_punct.replace("_", " "))


@dataclass(frozen=True)
class NeutralCitation:
    year: int
    court: str
    number: int

    def __str__(self) -> str:
        return f"[{self.year}] {self.court} {self.number}"


def parse_neutral_citation(text: str | None) -> NeutralCitation | None:
    if not text:
        return None
    match = _NEUTRAL_CITATION.search(text)
    if not match:
        return None
    return NeutralCitation(int(match.group(1)), match.group(2), int(match.group(3)))


def derive_title(citation: str) -> str | None:
    """Party names: the citation text before the case number ``(…)`` or neutral citation."""
    cut = len(citation)
    bracket = citation.find(" [")
    if bracket != -1:
        cut = min(cut, bracket)
    paren = re.search(r"\s\((?=[^)]*\))", citation[:cut])
    if paren:
        cut = min(cut, paren.start())
    title = citation[:cut].strip()
    return title or None


def normalize_case_number(value: str | None) -> str | None:
    """Collapse the multi-line, ``;``-separated case numbers the export contains."""
    if value is None:
        return None
    parts = [collapse_whitespace(part) for part in value.split(";")]
    joined = "; ".join(part for part in parts if part)
    return joined or None


def parse_judgment_date(value: str | None) -> date | None:
    """Parse ``"17 June 1963"``; return ``None`` (never a guess) for anything else."""
    if value is None:
        return None
    text = collapse_whitespace(value)
    for fmt in ("%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def split_judges(value: str | None) -> list[str]:
    """Split the export's newline-separated judge list, e.g.
    ``"Adumua-Bossman, JSC,\\n   \\n  Crabbe, JSC"`` -> ``["Adumua-Bossman, JSC", "Crabbe, JSC"]``.
    """
    if value is None:
        return []
    judges: list[str] = []
    for line in value.splitlines():
        name = collapse_whitespace(line).rstrip(",;").strip()
        if name:
            judges.append(name)
    return judges


@dataclass(frozen=True)
class AknIdentity:
    """Parsed Akoma Ntoso expression URI."""

    canonical_uri: (
        str  # host-independent AKN path, e.g. /akn/gh/judgment/ghasc/1963/1/eng@1963-06-17
    )
    work_uri: str  # same without the language/expression date
    jurisdiction: str
    court_code: str
    year: int
    number: str
    language: str
    expression_date: date


def parse_akn_uri(url: str | None) -> AknIdentity | None:
    if not url:
        return None
    path = urlsplit(url.strip()).path
    match = _AKN_PATH.match(path)
    if not match:
        return None
    try:
        expression_date = date.fromisoformat(match.group("expr_date"))
    except ValueError:
        return None
    canonical = path.rstrip("/")
    work = canonical.rsplit("/", 1)[0]
    return AknIdentity(
        canonical_uri=canonical,
        work_uri=work,
        jurisdiction=match.group("jurisdiction"),
        court_code=match.group("court"),
        year=int(match.group("year")),
        number=match.group("number"),
        language=match.group("language"),
        expression_date=expression_date,
    )
