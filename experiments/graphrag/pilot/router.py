"""Deterministic query routing for the graph: the named case and the direction (Phase 5 probe).

The Phase 3 pilot found that B0 rarely seeds the case a relational question names: its
case-name check splits the *whole question* on "v", so "Which later decisions cite Boi v
Adjei (2014)" yields the "parties" WHICH LATER DECISIONS CITE BOI and ADJEI … REASONING.
This module does the smallest deterministic thing instead (no model, no new SQL):

1. ``named_case``: the case the question names, as a party span ("Boi and Others v Adjei
   and Others") with its year, or a neutral citation;
2. ``resolve_anchor``: that name through the search's own lookups
   (``repository.citation_matches`` / ``case_name_matches``), restricted to the year;
3. ``route_direction``: incoming (later treatment) or outgoing (what it relied on) from the
   wording around the name: voice first, then temporal cues; anything else is ``None``
   (expand both ways).

The rules are generic (a name span, a year, verbs and temporal words), not fitted to any
question's wording. They were written after the Phase 3 questions were locked and seen, so
their accuracy on that set is optimistic; the tests use held-out phrasings.
"""

import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection

from ejudgment.domain.schemas import SearchFilters
from ejudgment.ingestion.normalize import NeutralCitation
from ejudgment.retrieval import repository as repo
from ejudgment.retrieval.query import detect_citation

ROUTER_VERSION = "router-v1"
Direction = Literal["incoming", "outgoing"]

# Case-insensitive: titles print "Vrs", people type "V" or "Vs".
_SEPARATOR = re.compile(r"\s(?:v|vs|vrs|versus)\.?\s", re.IGNORECASE)
_YEAR = re.compile(r"^\(\s*((?:19|20)\d\d)\s*[),]")
# Lower-case words that may sit inside a case name.
_CONNECTORS = frozenset({"and", "of", "&", "the", "de", "du", "la", "le", "der", "van", "von"})
# Capitalised words that open a question rather than name a party.
_OPENERS = frozenset(
    "WHICH WHAT HAS HAVE HAD DID DOES DO IS WAS WERE ARE HOW WHEN WHO WHOM WHERE WHY IN ON "
    "UNDER SINCE AFTER BEFORE FIND LIST SHOW GIVE NAME CAN COULD WOULD SHOULD".split()
)
_STRIP = "?!.,;:\"'“”‘’"


@dataclass(frozen=True)
class NamedCase:
    name: str | None  # the party span, "Boi and Others v Adjei and Others"
    year: int | None
    citation: NeutralCitation | None
    start: int  # character span of the name (or citation) in the query
    end: int


def _is_name_word(word: str) -> bool:
    core = word.strip(_STRIP + "()")
    return bool(core) and (core[0].isupper() or core[0].isdigit())


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in re.finditer(r"\S+", text)]


def named_case(query: str) -> NamedCase | None:
    """The case a question names: a neutral citation, else the party span around "v"."""
    citation = detect_citation(query)
    for separator in _SEPARATOR.finditer(query):
        left = _tokens(query[: separator.start()])
        right = _tokens(query[separator.end() :])
        # Left party: back from the separator over name words and connectors.
        start_index = len(left)
        while start_index > 0:
            word = left[start_index - 1][0]
            if word.strip(_STRIP) != word and start_index != len(left):
                break  # punctuation ends the name ("…, Mensah v")
            if not (_is_name_word(word) or word.lower() in _CONNECTORS):
                break
            start_index -= 1
        party = left[start_index:]
        while party and (
            party[0][0].upper().strip(_STRIP) in _OPENERS or party[0][0] in _CONNECTORS
        ):
            party = party[1:]
        if not party:
            continue
        # Right party: forward over name words, connectors, "Ex parte" and a parenthesised
        # capitalised group; a "(YYYY)" right after the name is its year.
        end_index, year, in_group = 0, None, False
        while end_index < len(right):
            word = right[end_index][0]
            if not in_group and _YEAR.match(word + " "):
                year = int(_YEAR.match(word + " ").group(1))  # type: ignore[union-attr]
                break
            bare = word.strip(_STRIP)
            if word.startswith("(") and _is_name_word(word):
                in_group = not word.rstrip(_STRIP).endswith(")")
            elif in_group:
                in_group = not word.rstrip(_STRIP).endswith(")")
            elif bare.lower() == "parte" or bare.lower() == "ex":
                pass
            elif not (_is_name_word(word) or bare.lower() in _CONNECTORS):
                break
            end_index += 1
            if word.rstrip("?!.;:") != word or (
                word.endswith(",")
                and not (
                    end_index < len(right) and right[end_index][0].strip(_STRIP).lower() == "ex"
                )
            ):
                break  # punctuation ends the name, except ", Ex parte …"
        other = right[:end_index]
        while other and other[-1][0].strip(_STRIP).lower() in _CONNECTORS:
            other = other[:-1]
        if not other:
            continue
        if year is None and end_index < len(right):
            following = _YEAR.match(right[end_index][0] + " ")
            year = int(following.group(1)) if following else None
        start = party[0][1]
        end = separator.end() + other[-1][2]
        name = query[start:end].strip(_STRIP)
        return NamedCase(name=name, year=year, citation=citation, start=start, end=end)
    if citation is not None:
        start, end = _citation_span(query, citation)
        return NamedCase(name=None, year=None, citation=citation, start=start, end=end)
    return None


def _citation_span(query: str, citation: NeutralCitation) -> tuple[int, int]:
    """Where the whole citation ("[2019] GHASC 41", or bare "2019 GHASC 41") sits, so the
    words around it, not its own tokens, are read for the direction."""
    found = re.search(
        rf"(?:\[\s*)?{citation.year}(?:\s*\])?\s*{re.escape(citation.court)}\s*{citation.number}\b",
        query,
        re.IGNORECASE,
    )
    return (found.start(), found.end()) if found else (0, 0)


# Verbs of treatment: an earlier case is cited, applied, followed … by a later one.
_TREATMENT = (
    r"(?:cite[sd]?|citing|appl(?:y|ies|ied|ying)|follow(?:s|ed|ing)?|overrul\w*|"
    r"distinguish\w*|consider(?:s|ed|ing)?|discuss(?:es|ed|ing)?|treat(?:s|ed|ing)?|"
    r"rel(?:y|ies|ied|ying)\s+(?:on|upon)|refer(?:s|red|ring)?\s+to|approv\w*|doubt\w*)"
)
# "authorities cited in X", "cases relied on by X": X is the citing case.
_CITED_IN = re.compile(
    r"\b(?:cited|relied\s+(?:on|upon)|referred\s+to|considered|mentioned|used)\s+(?:in|by)\s+$",
    re.IGNORECASE,
)
# "… decisions cite X", "has … applied X": X is cited (incoming), the verb just before it.
_VERB_BEFORE = re.compile(rf"\b{_TREATMENT}\s+(?:\S+\s+){{0,2}}$", re.IGNORECASE)
# "X (2008) cite …", "X relied on …": X is the subject (outgoing).
_ACTIVE_AFTER = re.compile(
    rf"^\W*(?:\(\s*\d{{4}}\s*\)\s*)?(?:itself\s+)?{_TREATMENT}", re.IGNORECASE
)
# "X has been followed", "X was applied": X is cited (incoming).
_PASSIVE_AFTER = re.compile(
    rf"^\W*(?:\(\s*\d{{4}}\s*\)\s*)?(?:(?:has|have|had|was|were|been|being|ever)\s+)+"
    rf"(?:\w+ly\s+)?{_TREATMENT}",
    re.IGNORECASE,
)
# "did X cite", "does X rely on": the auxiliary before X makes X the subject.
_AUXILIARY_BEFORE = re.compile(r"\b(?:did|does|do)\s+(?:\S+\s+){0,1}$", re.IGNORECASE)
_LATER = re.compile(r"\b(?:later|subsequent(?:ly)?|since|afterwards|downstream)\b", re.IGNORECASE)
_EARLIER = re.compile(
    r"\b(?:earlier|prior|previous(?:ly)?|preceding|older|upstream)\b", re.IGNORECASE
)


def _voice(before: str, after: str) -> Direction | None:
    if _CITED_IN.search(before):
        return "outgoing"
    if _PASSIVE_AFTER.match(after):
        return "incoming"
    if _AUXILIARY_BEFORE.search(before) and _ACTIVE_AFTER.match(after):
        return "outgoing"
    if _VERB_BEFORE.search(before):
        return "incoming"
    if _ACTIVE_AFTER.match(after):
        return "outgoing"
    return None


def route_direction(query: str, named: NamedCase | None) -> Direction | None:
    """Incoming or outgoing from the wording around the named case; ``None`` when nothing
    says which, or the cues disagree (the caller then expands both ways)."""
    if named is None:
        return None
    before, after = query[: named.start], query[named.end :]
    voice = _voice(before, after)
    later, earlier = bool(_LATER.search(query)), bool(_EARLIER.search(query))
    temporal: Direction | None = None
    if later != earlier:
        temporal = "incoming" if later else "outgoing"
    if voice and temporal and voice != temporal:
        return None
    return voice or temporal


def resolve_anchor(
    conn: Connection, named: NamedCase, filters: SearchFilters, limit: int
) -> list[repo.JudgmentRow]:
    """Judgments the named case resolves to, through the search's own lookups.

    A neutral citation is exact. A name goes through ``case_name_matches`` (pg_trgm with
    the per-side party check), keeps the year if one was given, and then the matches tied
    at the best similarity: when name and year do not single out one decision (a merits
    judgment and its reparations ruling), every tied one is returned, at most ``limit``."""
    if named.citation is not None:
        return repo.citation_matches(conn, named.citation, filters)[:limit]
    if not named.name:
        return []
    matches = repo.case_name_matches(conn, named.name, filters, 50)
    if named.year is not None:
        matches = [
            (row, sim)
            for row, sim in matches
            if row.judgment_date is not None and row.judgment_date.year == named.year
        ]
    if not matches:
        return []
    best = max(sim for _, sim in matches)
    return [row for row, sim in matches if sim >= best - 1e-9][:limit]
