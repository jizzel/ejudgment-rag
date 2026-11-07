"""Canonical decisions: copies of one judicial decision stored as several text groups.

A graph node is one judicial decision. The corpus sometimes holds one decision as two or
more *text groups* (``source_text_hash``): the same judgment published under several URIs
with different extracted text (another PDF, OCR), so the exact-text grouping that already
joins byte-identical re-publications keeps them apart. A reference to such a decision then
has several candidate cases and resolves to none. This module groups those copies into one
decision without touching them: every text group stays as it is and is mapped to its
decision, so the graph can point to the decision once while provenance still names the
copy that cited and the copies that make up the target.

Same court, date and parties are not enough: a court can give several decisions in one
matter on one day, and party names identify a litigation. Two text groups are copies of one
decision only when, for the pair, all of these hold:

1. **near-identical text**: each text contains at least ``TEXT_THRESHOLD`` of the other's
   20-character n-grams (``ejudgment.ingestion.pdf_verify``, the measure that verifies
   source files), over the whole text, since two decisions of one suit share their caption;
2. **no decision-level contradiction**: their decision numbers (``ECW/CCJ/JUD/…``) agree when
   both have one, their proceeding numbers (suit, application, communication) agree when
   both have one, the case numbers in their citations' parentheses agree when both have
   one (``case_numbers``: it also reads registry-prefixed suit numbers such as
   ``NR/DC/KPA/A2/7/24`` that ``extraction.identifiers`` does not), and their stage labels
   are the same (a label on one copy only also blocks).

Neutral citations are not compared: GhaLII numbers every publication, so each copy carries
its own (all 673 candidate pairs in build ``e21359336a18`` differ there). They are a
publication's identifier, not the decision's, and are all kept on the decision.

A decision is a set of copies in which **every** pair passes (complete link): a chain of
passing pairs does not by itself make one decision. Its id is the smallest member text
group's id, so a decision with one copy keeps its text group's id.
"""

import itertools
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ejudgment.ingestion.pdf_verify import char_grams, containment, squash
from experiments.graphrag.extraction.identifiers import identifier_kind
from experiments.graphrag.resolution.index import CorpusIndex

DECISIONS_VERSION = "decisions-v2"
TEXT_THRESHOLD = 0.8  # verified own files score 1.0, another record's file at most 0.5


@dataclass(frozen=True)
class PairEvidence:
    """Why two text groups are, or are not, copies of one decision."""

    first: str
    second: str
    court: str
    decided: date
    similarity: float
    blocked_by: tuple[str, ...]  # contradictions found ("proceeding_number", …)

    @property
    def same_decision(self) -> bool:
        return self.similarity >= TEXT_THRESHOLD and not self.blocked_by

    def record(self) -> dict[str, Any]:
        return {
            "first": self.first,
            "second": self.second,
            "court": self.court,
            "date": self.decided.isoformat(),
            "similarity": round(self.similarity, 4),
            "blocked_by": list(self.blocked_by),
            "same_decision": self.same_decision,
        }


@dataclass
class DecisionMap:
    """Text group -> decision, the decisions' copies, and the evidence for every pair."""

    decision_of: dict[str, str] = field(default_factory=dict)
    members: dict[str, tuple[str, ...]] = field(default_factory=dict)
    evidence: list[PairEvidence] = field(default_factory=list)

    def merged(self) -> dict[str, tuple[str, ...]]:
        """The decisions with more than one copy."""
        return {d: m for d, m in self.members.items() if len(m) > 1}


_PARENTHESIS = re.compile(r"\(([^()]*\d[^()]*)\)")
_NUMBER_TOKEN = re.compile(r"([A-Za-z]*)(\d+)")


def case_numbers(citation: str) -> frozenset[tuple[str, ...]]:
    """The case numbers in parentheses before the neutral citation, as the sequence of
    their numbered tokens (``A9/01/2022`` -> ``("A9", "1", "22")``): leading zeros dropped,
    four-digit years shortened, words and registry prefixes ignored."""
    head = re.split(r"\[\d{4}\]", citation, maxsplit=1)[0]
    keys = set()
    for inside in _PARENTHESIS.findall(head):
        for part in inside.split(";"):
            tokens = []
            for letters, digits in _NUMBER_TOKEN.findall(part):
                number = int(digits)
                if not letters and len(digits) == 4 and number >= 1900:
                    number %= 100
                tokens.append(f"{letters.upper()}{number}")
            if tokens:
                keys.add(tuple(tokens))
    return frozenset(keys)


def _case_numbers(index: CorpusIndex, group: str) -> frozenset[tuple[str, ...]]:
    return frozenset().union(*(case_numbers(j.citation) for j in index.groups[group]))


def _keys(index: CorpusIndex, group: str, kind: str) -> frozenset[str]:
    return frozenset(
        key
        for judgment in index.groups[group]
        for key in index.identifiers[judgment.id]
        if identifier_kind(key) == kind
    )


def _stages(index: CorpusIndex, group: str) -> frozenset[str]:
    return frozenset().union(*(index.stages[j.id] for j in index.groups[group]))


def _sides(index: CorpusIndex, group: str) -> list[frozenset[str]]:
    return index.sides[index.groups[group][0].id]


def _same_parties(first: list[frozenset[str]], second: list[frozenset[str]]) -> bool:
    """Both titles have two sides, and each side of each shares a word with the other."""
    if len(first) < 2 or len(second) < 2:
        return False
    return all(any(a & b for b in second) for a in first[:2]) and all(
        any(b & a for a in first) for b in second[:2]
    )


def candidate_pairs(index: CorpusIndex) -> list[tuple[str, str]]:
    """Text groups of the same court and decision date whose parties agree."""
    by_day: dict[tuple[str, date], list[str]] = defaultdict(list)
    for group, judgments in index.groups.items():
        decided = index.group_date(group)
        if decided is not None:
            by_day[(judgments[0].court, decided)].append(group)
    return [
        (a, b)
        for groups in by_day.values()
        for a, b in itertools.combinations(sorted(groups), 2)
        if _same_parties(_sides(index, a), _sides(index, b))
    ]


def similarity(first: str, second: str) -> float:
    """The smaller of the two containments of each text's 20-character n-grams."""
    a, b = char_grams(squash(first)), char_grams(squash(second))
    if not a or not b:
        return 0.0
    return min(containment(a, b), containment(b, a))


def pair_evidence(
    index: CorpusIndex, first: str, second: str, texts: dict[str, str]
) -> PairEvidence:
    blocked = []
    for kind, label in (("decision", "decision_number"), ("proceeding", "proceeding_number")):
        a, b = _keys(index, first, kind), _keys(index, second, kind)
        if a and b and not a & b:
            blocked.append(label)
    first_numbers, second_numbers = _case_numbers(index, first), _case_numbers(index, second)
    if first_numbers and second_numbers and not first_numbers & second_numbers:
        blocked.append("case_number")
    if _stages(index, first) != _stages(index, second):
        blocked.append("stage")
    decided = index.group_date(first)
    assert decided is not None
    return PairEvidence(
        first=first,
        second=second,
        court=index.groups[first][0].court,
        decided=decided,
        similarity=similarity(texts.get(first, ""), texts.get(second, "")),
        blocked_by=tuple(blocked),
    )


def _complete_link(groups: list[str], passes: Callable[[str, str], bool]) -> list[list[str]]:
    """Greedy cliques in a fixed order: each group joins the first clique it passes with
    entirely, else starts its own."""
    cliques: list[list[str]] = []
    for group in sorted(groups):
        for clique in cliques:
            if all(passes(group, member) for member in clique):
                clique.append(group)
                break
        else:
            cliques.append([group])
    return cliques


def canonicalize(index: CorpusIndex, texts: dict[str, str]) -> DecisionMap:
    """Groups the copies of each decision. ``texts``: each candidate text group's full text
    (``load_texts``); groups without a candidate pair are their own decision."""
    evidence = [pair_evidence(index, a, b, texts) for a, b in candidate_pairs(index)]
    passing = {(e.first, e.second) for e in evidence if e.same_decision}
    linked: dict[str, set[str]] = defaultdict(set)
    for a, b in passing:
        linked[a].add(b)
        linked[b].add(a)

    def passes(a: str, b: str) -> bool:
        return (min(a, b), max(a, b)) in passing

    result = DecisionMap(evidence=evidence)
    seen: set[str] = set()
    for group in sorted(index.groups):
        if group in seen:
            continue
        # The connected component, then complete-link cliques within it.
        component, frontier = {group}, [group]
        while frontier:
            for other in linked[frontier.pop()]:
                if other not in component:
                    component.add(other)
                    frontier.append(other)
        seen |= component
        for clique in _complete_link(sorted(component), passes):
            decision = min(clique)
            result.members[decision] = tuple(sorted(clique))
            for member in clique:
                result.decision_of[member] = decision
    return result


def decision_records(index: CorpusIndex, decisions: DecisionMap) -> Iterable[dict[str, Any]]:
    """One line per decision with more than one copy: ids, URIs and citations, no text."""
    for decision, members in sorted(decisions.merged().items()):
        yield {
            "decision": decision,
            "copies": [
                {
                    "text_group": member,
                    "judgments": [
                        {"id": j.id, "uri": j.uri, "citation": j.citation, "neutral": j.neutral}
                        for j in sorted(index.groups[member], key=lambda j: j.uri)
                    ],
                }
                for member in members
            ],
            "evidence": [
                e.record() for e in decisions.evidence if e.first in members and e.second in members
            ],
        }
