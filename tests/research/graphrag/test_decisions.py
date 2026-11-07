"""Canonical decisions: copies of one decision stored as several text groups (no database)."""

from datetime import date
from typing import Any

from experiments.graphrag.coverage.report import decision_precision
from experiments.graphrag.extraction.mentions import find_references
from experiments.graphrag.resolution.decision_audit import (
    LOWEST,
    merged_pairs,
    risky_non_merges,
    sample_merges,
)
from experiments.graphrag.resolution.decisions import (
    TEXT_THRESHOLD,
    _complete_link,
    canonicalize,
    case_numbers,
)
from experiments.graphrag.resolution.index import CorpusIndex, Judgment, neutral_key
from experiments.graphrag.resolution.resolve import Source, resolve

DAY = date(2020, 6, 26)
BODY = (
    "The appellant was convicted of armed robbery and sentenced to thirty years. On appeal he "
    "argued that the identification parade was irregular and that his defence of alibi was "
    "never investigated by the police. The Court finds that the trial court properly "
    "evaluated the evidence of the two eyewitnesses, who knew the appellant before the "
    "incident, and that the failure to investigate the alibi did not occasion a miscarriage "
    "of justice in the circumstances. The appeal is dismissed in its entirety. "
) * 3
OTHER = (
    "This ruling concerns only the application for leave to adduce fresh evidence. The "
    "applicant seeks to tender a medical report obtained after the trial. The Court is not "
    "satisfied that the report could not have been obtained with reasonable diligence, nor "
    "that it would probably have an important influence on the result. Leave is refused. "
) * 3


def judgment(
    jid: str, group: str, title: str, neutral: str, extra: str = "", day: date = DAY
) -> Judgment:
    return Judgment(
        id=jid,
        uri=f"/akn/aa-au/judgment/afchpr/2020/{jid}",
        group=group,
        title=title,
        citation=f"{title} {extra} {neutral}",
        neutral=neutral_key(neutral),
        date=day,
        court="afchpr",
    )


def index_of(*judgments: Judgment) -> CorpusIndex:
    return CorpusIndex.build(judgments)


def test_copies_with_near_identical_text_are_one_decision_whatever_their_citations() -> None:
    index = index_of(
        judgment("a", "g-a", "Elisamehe v United Republic of Tanzania", "[2020] AfCHPR 6"),
        judgment("b", "g-b", "Elisamehe v Tanzania", "[2020] AfCHPR 40"),
    )
    # The second copy's extraction lost a few words: still near-identical.
    decisions = canonicalize(index, {"g-a": BODY, "g-b": BODY.replace("in its entirety", "")})
    assert decisions.decision_of == {"g-a": "g-a", "g-b": "g-a"}
    (evidence,) = decisions.evidence
    assert evidence.same_decision and evidence.similarity >= TEXT_THRESHOLD
    assert decisions.merged() == {"g-a": ("g-a", "g-b")}


def test_two_decisions_of_one_day_that_share_a_caption_stay_apart() -> None:
    caption = "IN THE AFRICAN COURT ON HUMAN AND PEOPLES' RIGHTS Elisamehe v Tanzania " * 3
    index = index_of(
        judgment("a", "g-a", "Elisamehe v Tanzania", "[2020] AfCHPR 6"),
        judgment("b", "g-b", "Elisamehe v Tanzania", "[2020] AfCHPR 7"),
    )
    decisions = canonicalize(index, {"g-a": caption + BODY, "g-b": caption + OTHER})
    assert decisions.decision_of == {"g-a": "g-a", "g-b": "g-b"}
    assert not decisions.evidence[0].same_decision


def test_a_contradicting_proceeding_number_or_stage_blocks_a_merge() -> None:
    numbered = index_of(
        judgment("a", "g-a", "Elisamehe v Tanzania", "[2020] AfCHPR 6", "(Application 028/2015)"),
        judgment("b", "g-b", "Elisamehe v Tanzania", "[2020] AfCHPR 7", "(Application 014/2015)"),
    )
    blocked = canonicalize(numbered, {"g-a": BODY, "g-b": BODY}).evidence[0]
    assert blocked.blocked_by == ("proceeding_number", "case_number")
    assert not blocked.same_decision
    staged = index_of(
        judgment("a", "g-a", "Elisamehe v Tanzania", "[2020] AfCHPR 6", "(Reparations)"),
        judgment("b", "g-b", "Elisamehe v Tanzania", "[2020] AfCHPR 7"),
    )
    assert canonicalize(staged, {"g-a": BODY, "g-b": BODY}).evidence[0].blocked_by == ("stage",)


def test_a_registry_prefixed_suit_number_blocks_and_spelling_variants_agree() -> None:
    # Two suits with near-identical judgments; identifiers do not parse this suit format.
    suits = index_of(
        judgment("a", "g-a", "Agu v Aseda Company Ltd", "[2024] GHADC 445", "(NR/DC/KPA/A2/7/24)"),
        judgment("b", "g-b", "Agu v Aseda Company Ltd", "[2024] GHADC 443", "(NR/DC/KPA/A2/6/24)"),
    )
    assert canonicalize(suits, {"g-a": BODY, "g-b": BODY}).evidence[0].blocked_by == (
        "case_number",
    )
    assert case_numbers("Apeh v Dawuno (A9/01/2022) [2023] GHADC 1") == {("A9", "1", "22")}
    assert case_numbers("X v Y (A2/62/23; A2/62/23) [2023] GHADC 1") == {("A2", "62", "23")}
    assert case_numbers("Amare v Mozambique (Application No. 005/2011) [2011] AfCHPR 51") == (
        case_numbers("Amare v Mozambique (Application 5 of 2011) [2011] AfCHPR 39")
    )
    assert case_numbers("X v Y (Reparations) [2020] AfCHPR 6 (26 June 2020)") == frozenset()


def test_a_chain_of_passing_pairs_is_not_enough_every_pair_must_pass() -> None:
    # a~b and b~c pass, a~c does not: one decision {a, b}, and {c} apart.
    passing = {("a", "b"), ("b", "c")}

    def passes(x: str, y: str) -> bool:
        return (min(x, y), max(x, y)) in passing

    assert _complete_link(["a", "b", "c"], passes) == [["a", "b"], ["c"]]
    assert _complete_link(["a", "b", "c"], lambda x, y: True) == [["a", "b", "c"]]


def test_other_parties_or_other_days_are_never_candidates() -> None:
    index = index_of(
        judgment("a", "g-a", "Elisamehe v Tanzania", "[2020] AfCHPR 6"),
        judgment("b", "g-b", "Thomas v Tanzania", "[2020] AfCHPR 7"),
        judgment("c", "g-c", "Elisamehe v Tanzania", "[2021] AfCHPR 1", day=date(2021, 3, 1)),
    )
    decisions = canonicalize(index, {"g-a": BODY, "g-b": BODY, "g-c": BODY})
    assert decisions.evidence == [] and decisions.merged() == {}


def _copies_index() -> CorpusIndex:
    return index_of(
        judgment("a", "g-a", "Elisamehe v United Republic of Tanzania", "[2020] AfCHPR 6"),
        judgment("b", "g-b", "Elisamehe v Tanzania", "[2020] AfCHPR 40"),
    )


def test_copies_of_one_decision_are_one_candidate_with_both_in_provenance() -> None:
    reference = next(
        r
        for r in find_references("see Kalebi Elisamehe v. Tanzania, Judgment of 26 June 2020, x")
        if r.name
    )
    source = Source(group="g-x", date=date(2023, 1, 1))
    index = _copies_index()
    # Without a decision map the two copies are two candidates.
    assert resolve(index, reference, source).status == "ambiguous"
    index.use_decisions({"g-a": "g-a", "g-b": "g-a"})
    result = resolve(index, reference, source)
    assert (result.status, result.target_group, result.target_ids) == (
        "resolved_unique_fuzzy",
        "g-a",
        ("a", "b"),
    )
    # A copy of the citing decision is the citing decision: a self-reference.
    own = resolve(index, reference, Source(group="g-b", date=date(2023, 1, 1)))
    assert own.status == "self_reference"


def test_a_stated_stage_picks_the_labelled_decision_of_a_case_family() -> None:
    index = index_of(
        judgment(
            "jur",
            "g-jur",
            "Umuhoza v Republic of Rwanda",
            "[2016] AfCHPR 30",
            "(Ruling on Jurisdiction)",
            day=date(2016, 6, 3),
        ),
        judgment(
            "order",
            "g-order",
            "Umuhoza v Republic of Rwanda",
            "[2016] AfCHPR 32",
            day=date(2016, 3, 18),
        ),
    )
    reference = next(
        r
        for r in find_references("see Umuhoza v. Rwanda (Jurisdiction) (2016) 1 AfCLR 540, x")
        if r.name
    )
    result = resolve(index, reference, Source(group="g-x", date=date(2023, 1, 1)))
    assert (result.status, result.target_ids) == ("resolved_unique_fuzzy", ("jur",))


def _pair(
    first: str, second: str, similarity: float, court: str = "ghasc", **extra: Any
) -> dict[str, Any]:
    return {
        "first": first,
        "second": second,
        "court": court,
        "date": "2020-06-26",
        "similarity": similarity,
        "blocked_by": [],
        **extra,
    }


def test_the_decision_sheet_takes_the_lowest_merges_every_court_and_the_risky_non_merges() -> None:
    merges = [_pair(f"a{i}", f"b{i}", 0.99 - i / 100, "ghasc") for i in range(10)]
    merges += [_pair("c0", "d0", 0.95, "ghadc"), _pair("c1", "d1", 0.81, "afchpr")]
    split = _pair("s1", "s2", 0.9)  # passes, but complete link kept it apart
    blocked = _pair("x1", "x2", 0.99, blocked_by=["proceeding_number"])
    borderline, low = _pair("y1", "y2", 0.6), _pair("z1", "z2", 0.2)
    pairs = [*merges, split, blocked, borderline, low]
    decision_of = {p[k]: p["first"] for p in merges for k in ("first", "second")}
    decision_of |= {g: g for g in ("s1", "s2", "x1", "x2", "y1", "y2", "z1", "z2")}

    assert merged_pairs(pairs, decision_of) == merges
    sample = sample_merges(merges, 6, seed=1)
    lowest = sorted(merges, key=lambda p: p["similarity"])[:LOWEST]
    assert sample[:LOWEST] == lowest and len(sample) == 6
    assert {p["court"] for p in sample} == {"ghasc", "ghadc", "afchpr"}
    assert risky_non_merges(pairs, decision_of, 10) == [blocked, split, borderline]


def test_the_decision_audit_scores_merge_precision_and_missed_merges() -> None:
    rows = [
        {"kind": "merge", "same_decision": "y"},
        {"kind": "merge", "same_decision": "n"},
        {"kind": "merge", "same_decision": ""},
        {"kind": "non_merge", "same_decision": "y"},
        {"kind": "non_merge", "same_decision": "n"},
    ]
    result = decision_precision(rows)
    assert result["merge"] == {"correct": 1, "audited": 2}
    assert result["non_merge"] == {"correct": 1, "audited": 2}
    assert result["meets_gate"] is False
    assert decision_precision(rows[:1])["meets_gate"] is True
