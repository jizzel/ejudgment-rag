"""The corpus as the resolver sees it: eligible judgments grouped into cases.

A *case* is a group of judgments with the same ``source_text_hash``: re-publications of
one judgment under several AKN URIs (about 10% of the corpus) are one case, as they are
in search. Edges therefore point at cases, never at one arbitrary copy.
"""

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Connection, text

from experiments.graphrag.extraction.case_names import significant_words
from experiments.graphrag.extraction.citations import find_citations
from experiments.graphrag.extraction.identifiers import identifiers, stages

# Also "X -vrs- Y": some titles set the separator off with hyphens.
_SIDE_SEPARATOR = re.compile(r"[\s\-–]+(?:versus|v\s?rs|vs|v)\.?[\s\-–]+", re.IGNORECASE)


@dataclass(frozen=True)
class Judgment:
    id: str
    uri: str
    group: str  # source_text_hash: the case this judgment belongs to
    title: str
    citation: str
    neutral: str | None  # normalised neutral citation key, e.g. "[2019] GHASC 12"
    date: date | None
    court: str


def neutral_key(citation: str | None) -> str | None:
    """The normalised key of a neutral citation, as mentions are keyed."""
    if not citation:
        return None
    found = [c for c in find_citations(citation) if c.kind == "neutral"]
    return found[0].key if found else None


def title_sides(title: str) -> list[frozenset[str]]:
    """Significant words of each party side of a title (the same words as in references)."""
    sides = _SIDE_SEPARATOR.split(f" {title} ")
    words = [significant_words(side.split()) for side in sides]
    return [side for side in words if side]


@dataclass
class CorpusIndex:
    judgments: dict[str, Judgment] = field(default_factory=dict)
    by_neutral: dict[str, list[Judgment]] = field(default_factory=lambda: defaultdict(list))
    groups: dict[str, list[Judgment]] = field(default_factory=lambda: defaultdict(list))
    sides: dict[str, list[frozenset[str]]] = field(default_factory=dict)
    # word -> ids of judgments whose title has that word on some side
    by_word: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # Application, communication and suit numbers, and stage words, from each judgment's
    # own citation (``extraction.identifiers``): they tell one decision of a case from another.
    identifiers: dict[str, frozenset[str]] = field(default_factory=dict)
    by_identifier: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    stages: dict[str, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, judgments: Iterable[Judgment]) -> "CorpusIndex":
        index = cls()
        for judgment in judgments:
            index.judgments[judgment.id] = judgment
            index.groups[judgment.group].append(judgment)
            if judgment.neutral:
                index.by_neutral[judgment.neutral].append(judgment)
            sides = title_sides(judgment.title)
            index.sides[judgment.id] = sides
            for side in sides:
                for word in side:
                    index.by_word[word].add(judgment.id)
            index.identifiers[judgment.id] = identifiers(judgment.citation)
            for key in index.identifiers[judgment.id]:
                index.by_identifier[key].add(judgment.id)
            index.stages[judgment.id] = stages(judgment.citation)
        return index

    def group_date(self, group: str) -> date | None:
        """Earliest date among a case's copies (re-publications can carry later dates)."""
        dates = [j.date for j in self.groups[group] if j.date is not None]
        return min(dates) if dates else None


def load_index(conn: Connection) -> CorpusIndex:
    """Every eligible judgment that has chunks, i.e. that search can return."""
    rows = conn.execute(
        text(
            "SELECT j.id::text AS id, j.canonical_uri, g.source_text_hash, "
            "coalesce(j.title, j.citation) AS title, j.citation, j.neutral_citation, "
            "j.judgment_date, j.court_code "
            "FROM judgments j "
            "JOIN (SELECT DISTINCT judgment_id, source_text_hash FROM chunks) g "
            "ON g.judgment_id = j.id "
            "WHERE j.eligibility_status = 'eligible'"
        )
    )
    return CorpusIndex.build(
        Judgment(
            id=row.id,
            uri=row.canonical_uri,
            group=row.source_text_hash,
            title=row.title,
            citation=row.citation,
            neutral=neutral_key(row.neutral_citation),
            date=row.judgment_date,
            court=row.court_code,
        )
        for row in rows
    )
