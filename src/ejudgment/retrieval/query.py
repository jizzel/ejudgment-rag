"""Query interpretation: citation and case-name detection."""

import re
from dataclasses import dataclass

from ejudgment.ingestion.normalize import (
    NeutralCitation,
    normalize_citation,
    parse_neutral_citation,
)

_CASE_NAME = re.compile(r"\S\s+(?:v|vs|vrs|versus)\.?\s+\S", re.IGNORECASE)
_PARTY_SEPARATOR = re.compile(r"\s(?:v|vs|vrs|versus)\.?\s", re.IGNORECASE)
# Words that do not identify a party.
_PARTY_STOPWORDS = frozenset(
    "AND ANOR ANR ORS OTHERS ANOTHER THE OF EX PARTE FOR IN ON AT BY".split()
)
_PARTY_WORD = re.compile(r"[A-Z0-9]{3,}")


@dataclass(frozen=True)
class ParsedQuery:
    text: str
    neutral_citation: NeutralCitation | None
    looks_like_case_name: bool


# Also accept a citation typed without brackets ("2020 GHASC 104") when the court token
# looks like a report abbreviation (mixed or upper case, at least two capitals).
_BARE_CITATION = re.compile(r"\b(\d{4})\s+([A-Z][A-Za-z]*[A-Z][A-Za-z]*)\s+(\d+)\b")


def detect_citation(text: str) -> NeutralCitation | None:
    bracketed = parse_neutral_citation(text)
    if bracketed is not None:
        return bracketed
    bare = _BARE_CITATION.search(text)
    if bare is None:
        return None
    return NeutralCitation(int(bare.group(1)), bare.group(2), int(bare.group(3)))


def parse_query(query: str) -> ParsedQuery:
    text = " ".join(query.split())
    return ParsedQuery(
        text=text,
        neutral_citation=detect_citation(text),
        looks_like_case_name=bool(_CASE_NAME.search(text)),
    )


def party_words(text: str) -> list[set[str]]:
    """Significant words of each side of a case name ("Mensah v Owusu" -> [{MENSAH}, {OWUSU}])."""
    sides = _PARTY_SEPARATOR.split(f" {text} ")
    words = [
        {word for word in _PARTY_WORD.findall(side.upper()) if word not in _PARTY_STOPWORDS}
        for side in sides
    ]
    return [side for side in words if side]


def party_patterns(query: str) -> list[str]:
    """One regex per party side, matched against ``citation_normalized`` in SQL.

    Trigram similarity alone ranks every "X v Tanzania" alike for "Juma v Tanzania", so each
    side must contribute a whole word. Words are ``[A-Z0-9]{3,}``, so they need no escaping.
    """
    return [f"(^| )({'|'.join(sorted(side))})( |$)" for side in party_words(query)]


def names_every_party(query: str, citation: str) -> bool:
    """Python mirror of the SQL party check (see :func:`party_patterns`)."""
    normalized = normalize_citation(citation)
    return all(re.search(pattern, normalized) for pattern in party_patterns(query))


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
