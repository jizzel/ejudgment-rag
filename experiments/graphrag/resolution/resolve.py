"""Resolve a reference to a decision in the corpus, or say why it can't be.

The policy is conservative: an edge exists only when exactly one case qualifies *and*
every signal next to the reference agrees with it.

**Methods and evidence tiers** (strongest first; docs/graphrag/coverage-report.md):

- ``neutral_exact`` (tier A): an exact neutral citation. One case: resolved; several
  cases share it (e.g. ``[2023] GHADC 77``): ambiguous; none: ``target_absent``.
- ``name_with_decision_identifier`` (B): a case name plus a number that names one
  *decision* (an ECOWAS judgment number, ``ECW/CCJ/JUD/…``) that a corpus judgment carries.
- ``name_with_dated_proceeding`` (B): a case name plus a *proceeding* number (application,
  communication, suit: ``Communication 224/98``, ``J4/43/2013``) and an explicit decision
  date or stage label that picks one decision of that proceeding.
- ``name_with_proceeding`` (C): a case name plus a proceeding number alone. A proceeding
  can hold several decisions (interlocutory rulings, provisional measures, merits,
  reparations), some of them not in the corpus, so this is candidate evidence only (the
  v4 audit: 36/40, docs/graphrag/phase2-graph.md).
- ``name_with_report`` (B): a case name plus a law-report citation; candidates must be
  decided from two years before the report year to its last year.
- ``name_with_date`` (B): a case name plus an explicit judgment date ("Judgment of 23 June
  2022"); the candidate must carry that date.
- ``name_only`` (C): a case name alone. Candidate evidence only.

**Names.** A title matches a name when two different party sides each match one side of
the name, compared as sets of significant words, in either order (appeals swap the
parties): the name's side is contained in the title's, or the title's side is contained in
the name's *and* holds its anchor, the surname (left: the word nearest the separator;
right: the last word). So "Faisal Mohammed Akilu v The Republic" matches "Akilu Vrs
Republic", but "John Gandonu v Federal Republic of Nigeria …" does not match "Republic Vrs
John", nor "Republic v Philip Afornorpe" "Republic Vrs Philip Addo Teye". Without a
corroborating identifier, report or date, a generic side ("Republic") needs two shared
words on the other side. Names made only of generic words are never resolved.

**Conflicting identifiers.** Two numbers beside one name that belong to different cases
(``ECW/CCJ/APP/08/09 and ECW/CCJ/APP/12/07``) make the pairing unsafe: ``ambiguous``
(``conflicting_identifiers``). Numbers of one joined decision share its cases and are fine.

**Which decision.** Party names identify a litigation; one case family can hold several
decisions (provisional measures, merits, reparations, review). Identifiers, stage words
and a decision date next to the reference must agree with the candidate: a candidate with
a different identifier, an incompatible stage (``extraction.identifiers.stages_compatible``)
or another date is dropped. A neutral citation contradicted by any of these signals is
``ambiguous`` (``<signal>_conflicts_with_citation``): one of the two is wrong.

**Self references.** A reference to the citing judgment's own case, a reference carrying
the judgment's own suit number, and a name in the judgment's caption (caption markers, or
the opening ``CAPTION_ZONE`` characters without a citing cue) are ``self_reference``, not
edges. If the judgment's own case is one candidate among others, the reference is
``ambiguous`` (``includes_own_case``).

A target that is a re-publication of the citing decision under another URI with a
different text (the same parties, and the same date or suit number) is also a
``self_reference`` (``republication_of_citing_case``): a running header naming the
citing case, not a citation.

**Time.** A resolved edge whose target decision is dated after the citing case (its
earliest copy) is ``temporal_conflict``: kept with its target for review, never silently
dropped or accepted (docs/graphrag/AGENTS.md rule 4).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal

from experiments.graphrag.extraction.case_names import CaseName, significant_words
from experiments.graphrag.extraction.citations import CORPUS_COURTS
from experiments.graphrag.extraction.identifiers import identifier_kind, stages_compatible
from experiments.graphrag.extraction.mentions import Reference
from experiments.graphrag.resolution.index import _SIDE_SEPARATOR, CorpusIndex

VERSION = "resolver-v13"

Status = Literal[
    "resolved_exact",
    "resolved_unique_fuzzy",
    "ambiguous",
    "target_absent",
    "unresolved",
    "self_reference",
    "temporal_conflict",
]
Method = Literal[
    "neutral_exact",
    "name_with_decision_identifier",
    "name_with_dated_proceeding",
    "name_with_proceeding",
    "name_with_report",
    "name_with_date",
    "name_only",
    "none",
]
Tier = Literal["A", "B", "C"]
TIERS: dict[str, Tier] = {
    "neutral_exact": "A",
    "name_with_decision_identifier": "B",
    "name_with_dated_proceeding": "B",
    "name_with_proceeding": "C",
    # Before resolver v5 one method covered every identifier; its audit sheets (builds
    # d739505c538f and earlier) still read under the tier they were audited as.
    "name_with_identifier": "B",
    "name_with_report": "B",
    "name_with_date": "B",
    "name_only": "C",
}
RESOLVED: frozenset[Status] = frozenset({"resolved_exact", "resolved_unique_fuzzy"})

# Party words that cannot identify a case on their own.
GENERIC_WORDS = frozenset(
    "REPUBLIC STATE PEOPLE ATTORNEY GENERAL INSPECTOR POLICE COMMISSIONER QUEEN KING "
    "REGINA REX GHANA GOVERNMENT HIGH COURT CIRCUIT DISTRICT TRIBUNAL CHIEF JUSTICE "
    "MINISTER MINISTRY BANK COUNCIL ASSEMBLY AUTHORITY COMMISSION BOARD SERVICE".split()
)
REPORT_YEARS_BEFORE = 2  # a decision is reported in its year or up to two years later
CAPTION_ZONE = 1500  # opening characters of a judgment that hold its caption


@dataclass(frozen=True)
class Source:
    """The citing side of a reference."""

    group: str  # its case (re-publication group)
    date: date | None  # the case's earliest date, so every copy gets the same answer
    identifiers: frozenset[str] = frozenset()  # its own suit/application numbers
    offset: int = CAPTION_ZONE  # where the reference starts in the source text
    judgment_id: str | None = None  # the citing judgment itself


@dataclass(frozen=True)
class Resolution:
    status: Status
    method: Method
    reason: str | None = None
    target_group: str | None = None
    # The judgments that matched, within the target case. A case can hold copies of other
    # judgments (the export's text for one judgment is sometimes another's), so these,
    # not the whole group, say what the reference was resolved to.
    target_ids: tuple[str, ...] = ()
    candidates: int = 0  # candidate cases considered (for ambiguous: how many)
    name_agrees: bool | None = None  # neutral citation with a name: does the title match?
    foreign: bool | None = None  # target_absent neutral citation: a court outside the corpus
    pre_temporal_status: Status | None = None  # for temporal_conflict: the resolved status

    @property
    def tier(self) -> Tier | None:
        return TIERS.get(self.method)


def _nested(name_side: frozenset[str], title_side: frozenset[str], anchor: str) -> bool:
    if name_side <= title_side:
        return True
    return title_side < name_side and anchor in title_side


def _side_pairs(index: CorpusIndex, judgment_id: str, name: CaseName) -> list[tuple[int, int]]:
    sides = index.sides[judgment_id]
    return [
        (a, b)
        for a, side_a in enumerate(sides)
        if _nested(name.left_words, side_a, name.left_word)
        for b, side_b in enumerate(sides)
        if a != b and _nested(name.right_words, side_b, name.right_anchor)
    ]


def _name_matches(index: CorpusIndex, judgment_id: str, name: CaseName, *, strict: bool) -> bool:
    """The title matches the name (module docstring). ``strict``: a generic side must be
    balanced by at least two shared words on the other side."""
    sides = index.sides[judgment_id]
    pairs = _side_pairs(index, judgment_id, name)
    if strict:
        pairs = [
            (a, b)
            for a, b in pairs
            if not (name.left_words <= GENERIC_WORDS and len(name.right_words & sides[b]) < 2)
            and not (name.right_words <= GENERIC_WORDS and len(name.left_words & sides[a]) < 2)
        ]
    if not pairs:
        return False
    return name.ex_parte_word is None or any(name.ex_parte_word in side for side in sides)


def _shares_parties(index: CorpusIndex, judgment_id: str, name: CaseName) -> bool:
    """Looser: each side of the name shares a word with a different side of the title. Used
    only together with a matching identifier, which already singles out the decision."""
    sides = index.sides[judgment_id]
    return any(
        a != b and name.left_words & sides[a] and name.right_words & sides[b]
        for a in range(len(sides))
        for b in range(len(sides))
    )


def _name_candidates(index: CorpusIndex, name: CaseName, *, strict: bool) -> set[str]:
    with_left = set().union(*(index.by_word.get(w, set()) for w in name.left_words))
    with_right = set().union(*(index.by_word.get(w, set()) for w in name.right_words))
    found = {
        jid for jid in with_left & with_right if _name_matches(index, jid, name, strict=strict)
    }
    surname = name.ex_parte_surname
    if not found and name.ex_parte_word and surname and surname != name.ex_parte_word:
        # "Ex parte Benjamin Duffour" titled "Ex Parte: Duffour": only when the first word fits
        # no title, so "Ex parte Kwabena Duffour" still tells Kwabena's case from the others.
        alt = replace(name, ex_parte_word=surname)
        found = {
            jid
            for jid in with_left & with_right
            if _name_matches(index, jid, alt, strict=strict)
            and _title_applicant(index.judgments[jid].title) <= name.ex_parte_words
        }
    return found


_TITLE_EX_PARTE = re.compile(r"\bex[\s\-–—]*parte[:,]?\s*(.*)$", re.IGNORECASE)


def _title_applicant(title: str) -> frozenset[str]:
    """Significant words of the applicant a title names after "Ex parte" (its first party)."""
    match = _TITLE_EX_PARTE.search(title)
    if match is None:
        return frozenset()
    first = re.split(r"\s(?:&|and)\s|,", match.group(1), maxsplit=1, flags=re.IGNORECASE)[0]
    return significant_words(first.split())


def _is_generic(name: CaseName) -> bool:
    words = name.left_words | name.right_words
    if name.ex_parte_word:
        words |= {name.ex_parte_word}
    return words <= GENERIC_WORDS


def _identifier_conflict(index: CorpusIndex, reference: Reference, judgment_id: str) -> bool:
    own = index.identifiers[judgment_id]
    return bool(reference.identifiers and own and not reference.identifiers & own)


def _date_conflict(index: CorpusIndex, reference: Reference, judgment_id: str) -> bool:
    decided = index.judgments[judgment_id].date
    return reference.decision_date is not None and decided != reference.decision_date


def _stage_conflict(index: CorpusIndex, reference: Reference, judgment_id: str) -> bool:
    if stages_compatible(reference.stages, index.stages[judgment_id]):
        return False
    # A decision whose title names no stage, carrying the exact date the reference gives,
    # is the decision meant ("Application No. 008/2020, Judgment of 23 June 2022
    # (jurisdiction and admissibility)" for an unlabelled corpus title).
    exact_date = reference.decision_date == index.judgments[judgment_id].date
    return bool(index.stages[judgment_id]) or not exact_date


def _decide(
    index: CorpusIndex, ids: set[str], source: Source, method: Method, resolved: Status
) -> Resolution:
    groups = {index.judgments[jid].group for jid in ids}
    if source.group in groups:
        if len(groups) == 1:
            return Resolution("self_reference", method, candidates=1)
        return Resolution("ambiguous", method, reason="includes_own_case", candidates=len(groups))
    if len(groups) > 1:
        return Resolution("ambiguous", method, candidates=len(groups))
    if not groups:
        return Resolution("unresolved", method, reason="no_candidate")
    (group,) = groups
    return Resolution(
        resolved, method, target_group=group, target_ids=tuple(sorted(ids)), candidates=1
    )


def _resolve_neutral(index: CorpusIndex, reference: Reference, source: Source) -> Resolution:
    neutral = reference.neutral
    assert neutral is not None
    matches = index.by_neutral.get(neutral.key, [])
    if not matches:
        court = neutral.token.split(" ")[0]
        return Resolution("target_absent", "neutral_exact", foreign=court not in CORPUS_COURTS)
    result = _decide(index, {j.id for j in matches}, source, "neutral_exact", "resolved_exact")
    if result.target_group is None:
        return result
    # Every other signal next to the citation must agree with it.
    name_agrees = None
    if reference.name is not None:
        name = reference.name
        name_agrees = any(_name_agrees(index, jid, name) for jid in result.target_ids)
    adjacent = reference.adjacent_sides
    checks: list[tuple[str, Callable[[str], bool]]] = [
        ("name", lambda jid: name_agrees is False),
        # An unlinked name just before the citation must share words with two different
        # sides of the target's title; otherwise the two may name different cases.
        (
            "adjacent_name",
            lambda jid: (
                adjacent is not None
                and not _sides_share(index.sides[jid], adjacent[0], adjacent[1])
            ),
        ),
        ("identifier", lambda jid: _identifier_conflict(index, reference, jid)),
        ("date", lambda jid: _date_conflict(index, reference, jid)),
        ("stage", lambda jid: _stage_conflict(index, reference, jid)),
    ]
    for signal, conflicts in checks:
        if all(conflicts(jid) for jid in result.target_ids):
            return Resolution(
                "ambiguous",
                "neutral_exact",
                reason=f"{signal}_conflicts_with_citation",
                candidates=2,
                target_ids=result.target_ids,
                name_agrees=name_agrees,
            )
    return replace(result, name_agrees=name_agrees)


def _name_agrees(index: CorpusIndex, judgment_id: str, name: CaseName) -> bool:
    """Is a name beside a neutral citation compatible with the cited judgment? The check is
    there to catch a *different* case (Fuseini v Republic beside Tafali v Yakubu's
    citation), so a name agrees when it matches the title, or when each of its sides shares
    a word with a different side of it: "XTRA GOLD MINING" for "X-tra Gold Mining Ltd",
    "(CLOGSAG)" absent from the title. A title with one side (a truncated corpus title)
    is checked on its one side only."""
    sides = index.sides[judgment_id]
    if len(sides) < 2:
        # A side of initials ("A Vrs ADA", an anonymised title) leaves nothing to compare. A
        # title cut before its "v" ("Emil Touray and Saikou Jammeh") still has a party the
        # name must share a word with ("Miles Investments v Sierra Leone" is another case).
        if _SIDE_SEPARATOR.search(f" {index.judgments[judgment_id].title} "):
            return True
        return any((name.left_words | name.right_words) & side for side in sides)
    if _name_matches(index, judgment_id, name, strict=False):
        return True
    # Shared party words are enough only if the applicants agree too: "Republic v High
    # Court, Accra; Ex parte Owusu" shares Republic and High Court with "… Ex parte Allgate".
    return _shares_parties(index, judgment_id, name) and _applicant_agrees(index, judgment_id, name)


def _applicant_agrees(index: CorpusIndex, judgment_id: str, name: CaseName) -> bool:
    """The reference's ex parte applicant (first word or surname) is among those the title
    names after "Ex parte"; trivially when either side names no applicant."""
    title_applicant = _title_applicant(index.judgments[judgment_id].title)
    if name.ex_parte_word is None or not title_applicant:
        return True
    return bool({name.ex_parte_word, name.ex_parte_surname} & title_applicant)


def _filter(ids: set[str], keep: Callable[[str], bool]) -> set[str]:
    return {jid for jid in ids if keep(jid)}


def _conflicting_identifiers(index: CorpusIndex, reference: Reference) -> bool:
    """Two of the reference's numbers that the corpus knows point to disjoint cases."""
    cases = [
        {index.judgments[jid].group for jid in index.by_identifier[key]}
        for key in sorted(reference.identifiers)
        if index.by_identifier.get(key)
    ]
    return any(not a & b for i, a in enumerate(cases) for b in cases[i + 1 :])


def _by_identifier(index: CorpusIndex, reference: Reference, name: CaseName, kind: str) -> set[str]:
    keys = [k for k in reference.identifiers if identifier_kind(k) == kind]
    found = set().union(*(index.by_identifier.get(k, set()) for k in keys))
    # The number singles out the case, so the parties need only share words.
    return _filter(found, lambda jid: _shares_parties(index, jid, name))


def _one_decision(index: CorpusIndex, reference: Reference, ids: set[str]) -> set[str] | None:
    """The decisions of a proceeding that the reference's explicit date or stage label
    picks; ``None`` when it gives neither (the number alone then names only a proceeding)."""
    if reference.decision_date is not None:
        ids = {jid for jid in ids if index.judgments[jid].date == reference.decision_date}
        # Two decisions of one day (an order and a ruling): the stated stage tells them apart.
        if not reference.stages or len({index.judgments[j].group for j in ids}) <= 1:
            return ids
    if reference.stages:
        # A decision labelled with the stated stage is the one meant ("Ruling on
        # Jurisdiction" among an order, a jurisdiction ruling and a merits judgment). Only
        # when none carries it may the label mean a decision titled without a stage, by the
        # same compatibility as everywhere else (``stages_compatible``).
        labelled = {jid for jid in ids if reference.stages & index.stages[jid]}
        return labelled or {
            jid for jid in ids if stages_compatible(reference.stages, index.stages[jid])
        }
    return None


def _resolve_name(
    index: CorpusIndex, reference: Reference, name: CaseName, source: Source
) -> Resolution:
    years = reference.report_years
    method: Method
    if _conflicting_identifiers(index, reference):
        return Resolution("ambiguous", "name_with_proceeding", reason="conflicting_identifiers")
    # A decision number names the decision; a proceeding number needs a date or stage to.
    ids = _by_identifier(index, reference, name, "decision")
    if ids:
        method = "name_with_decision_identifier"
    elif proceeding := _by_identifier(index, reference, name, "proceeding"):
        picked = _one_decision(index, reference, proceeding)
        if picked is None:
            method, ids = "name_with_proceeding", proceeding
        elif not picked:
            # Never the proceeding's other decision: the one cited may not be in the corpus.
            return Resolution(
                "unresolved",
                "name_with_dated_proceeding",
                reason="no_decision_matches_date_or_stage",
            )
        else:
            method, ids = "name_with_dated_proceeding", picked
    else:
        if _is_generic(name):
            return Resolution("unresolved", "name_only", reason="generic_names")
        if years is not None:
            method = "name_with_report"
        elif reference.decision_date is not None:
            method = "name_with_date"
        else:
            method = "name_only"
        ids = _name_candidates(index, name, strict=method == "name_only")
        if not ids:
            return Resolution("unresolved", method, reason="no_candidate")
        if years is not None:
            first, last = years[0] - REPORT_YEARS_BEFORE, years[1]
            ids = _filter(
                ids,
                lambda jid: (
                    (d := index.judgments[jid].date) is not None and first <= d.year <= last
                ),
            )
            if not ids:
                return Resolution("unresolved", method, reason="no_candidate_in_report_years")
    # Which decision of the case family: identifiers, date and stage must not contradict.
    checks: list[tuple[str, Callable[[CorpusIndex, Reference, str], bool]]] = [
        ("identifier_mismatch", _identifier_conflict),
        ("decision_date_mismatch", _date_conflict),
        ("procedural_stage_mismatch", _stage_conflict),
    ]
    for reason, conflicts in checks:
        ids = {jid for jid in ids if not conflicts(index, reference, jid)}
        if not ids:
            return Resolution("unresolved", method, reason=reason)
    return _decide(index, ids, source, method, "resolved_unique_fuzzy")


def _resolve_unchecked(index: CorpusIndex, reference: Reference, source: Source) -> Resolution:
    name = reference.name
    if not reference.citations and name is not None:
        in_caption_zone = source.offset < CAPTION_ZONE and not reference.cue_before
        if reference.caption_marker or in_caption_zone:
            return Resolution("self_reference", "name_only", reason="caption")
    if reference.identifiers & source.identifiers:
        method: Method = "neutral_exact" if reference.neutral else "name_with_proceeding"
        return Resolution("self_reference", method, reason="own_identifier")
    if reference.neutral is not None:
        return _resolve_neutral(index, reference, source)
    if name is None:
        reason = "report_without_name" if reference.kind == "report_only" else "unclassified"
        return Resolution("unresolved", "none", reason=reason)
    return _resolve_name(index, reference, name, source)


def target_date(index: CorpusIndex, result: Resolution) -> date | None:
    dates = [d for jid in result.target_ids if (d := index.judgments[jid].date) is not None]
    return min(dates) if dates else None


def _sides_share(sides: list[frozenset[str]], left: frozenset[str], right: frozenset[str]) -> bool:
    """Each of two word sets shares a word with a different side of a title."""
    return any(
        a != b and left & sides[a] and right & sides[b]
        for a in range(len(sides))
        for b in range(len(sides))
    )


def _republishes_citing_case(
    index: CorpusIndex, source: Source, target_ids: tuple[str, ...]
) -> bool:
    if source.judgment_id is None:
        return False
    citing = index.judgments[source.judgment_id]
    own_sides = set(index.sides[source.judgment_id])
    for jid in target_ids:
        same_date = citing.date is not None and index.judgments[jid].date == citing.date
        if own_sides and set(index.sides[jid]) == own_sides:
            if same_date or index.identifiers[jid] & index.identifiers[source.judgment_id]:
                return True
        # The same parties decided the same day: the citing decision under another URI,
        # even when one title has a slip ("Retired Majot" for "Retired Major").
        if same_date and _sides_share(index.sides[jid], *_two_sides(index, source.judgment_id)):
            return True
    return False


def _two_sides(index: CorpusIndex, judgment_id: str) -> tuple[frozenset[str], frozenset[str]]:
    sides = index.sides[judgment_id]
    return (sides[0], sides[1]) if len(sides) >= 2 else (frozenset(), frozenset())


def resolve(index: CorpusIndex, reference: Reference, source: Source) -> Resolution:
    result = _resolve_unchecked(index, reference, source)
    if result.status not in RESOLVED:
        return result
    if _republishes_citing_case(index, source, result.target_ids):
        return Resolution(
            "self_reference", result.method, reason="republication_of_citing_case", candidates=1
        )
    target = target_date(index, result)
    if source.date is not None and target is not None and target > source.date:
        return replace(
            result,
            status="temporal_conflict",
            reason="target_after_source",
            pre_temporal_status=result.status,
        )
    return result
