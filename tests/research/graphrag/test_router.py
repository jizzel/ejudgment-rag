"""Deterministic routing (Phase 5 probe), on phrasings that are not in the pilot set."""

import uuid
from datetime import date

import pytest

from ejudgment.domain.schemas import SearchFilters
from ejudgment.retrieval.repository import JudgmentRow
from experiments.graphrag.pilot import router
from experiments.graphrag.pilot.router import named_case, resolve_anchor, route_direction

EXTRACTION = [
    ("Has Mensah v Mensah (2012) been followed?", "Mensah v Mensah", 2012),
    ("What did Tuffuor v Attorney-General rely on?", "Tuffuor v Attorney-General", None),
    ("cases citing In re Asere Stool; Nikoi Olai v Akwei", "Nikoi Olai v Akwei", None),
    (
        "Which cases applied Republic v High Court (Fast Track Division), Ex parte Daley (2011)?",
        "Republic v High Court (Fast Track Division), Ex parte Daley",
        2011,
    ),
    ("How was Agyei & Ors vs Owusu treated afterwards?", "Agyei & Ors vs Owusu", None),
    ("Which later judgments cite Asante Vrs Boateng (2016)?", "Asante Vrs Boateng", 2016),
    ("Has Kofi V Ama been applied?", "Kofi V Ama", None),
    (
        "List authorities relied on by Sam (No 2) v Attorney General",
        "Sam (No 2) v Attorney General",
        None,
    ),
    (
        "Is Ellembelle District Assembly v Mensah still followed today?",
        "Ellembelle District Assembly v Mensah",
        None,
    ),
]


@pytest.mark.parametrize(("query", "name", "year"), EXTRACTION)
def test_the_named_case_is_the_party_span_and_its_year(
    query: str, name: str, year: int | None
) -> None:
    found = named_case(query)
    assert found is not None and (found.name, found.year) == (name, year)
    assert query[found.start : found.end].startswith(name.split(" v")[0])


def test_a_neutral_citation_is_used_and_no_name_means_no_case() -> None:
    cited = named_case("Which later judgments apply [2019] GHASC 41?")
    assert cited is not None and cited.citation is not None and cited.name is None
    assert str(cited.citation).upper().endswith("GHASC 41")
    assert named_case("When may a landlord recover possession for unpaid rent?") is None
    assert named_case("Is a customary marriage dissolved by the death of a spouse?") is None


DIRECTION = [
    ("Has Mensah v Mensah (2012) been followed?", "incoming"),  # passive
    ("Which judgments have applied Boateng v Boateng?", "incoming"),  # active, verb before
    ("Was Quartey v Martey ever overruled?", "incoming"),
    ("What did Tuffuor v Attorney-General rely on?", "outgoing"),  # auxiliary + verb after
    ("Which precedents does Sam v Attorney General cite?", "outgoing"),
    ("List authorities relied on by Sam (No 2) v Attorney General", "outgoing"),
    ("Which cases were cited in Agyei v Owusu (2015)?", "outgoing"),
    ("Show me subsequent cases on Agyei v Owusu", "incoming"),  # temporal only
    ("What prior authority underlies Agyei v Owusu?", "outgoing"),
    ("Tell me about Agyei v Owusu", None),  # no cue
    ("Which earlier decisions applied Agyei v Owusu?", None),  # cues disagree
]


@pytest.mark.parametrize(("query", "direction"), DIRECTION)
def test_direction_comes_from_voice_then_temporal_cues(query: str, direction: str | None) -> None:
    assert route_direction(query, named_case(query)) == direction


@pytest.mark.parametrize(
    ("query", "direction"),
    [
        ("What did [2019] GHASC 41 rely on?", "outgoing"),
        ("Has [2019] GHASC 41 been followed?", "incoming"),
        ("Which judgments applied 2019 GHASC 41?", "incoming"),
    ],
)
def test_a_citation_only_anchor_routes_by_the_words_around_it(query: str, direction: str) -> None:
    named = named_case(query)
    assert named is not None and named.name is None
    assert query[named.start : named.end].replace("[", "").replace("]", "") == "2019 GHASC 41"
    assert route_direction(query, named) == direction


def test_no_named_case_routes_nowhere() -> None:
    assert route_direction("Which later decisions discuss adverse possession?", None) is None


def _row(uri: str, year: int) -> JudgmentRow:
    return JudgmentRow(
        judgment_id=uuid.uuid4(),
        canonical_uri=uri,
        citation=uri,
        title=None,
        court_code=None,
        court_name=None,
        jurisdiction=None,
        judgment_date=date(year, 6, 1),
    )


def test_the_anchor_keeps_the_year_and_the_best_tied_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        (_row("/akn/2018-merits", 2018), 0.9),
        (_row("/akn/2018-reparations", 2018), 0.9),
        (_row("/akn/2018-order", 2018), 0.7),
        (_row("/akn/2016-ruling", 2016), 1.0),
    ]
    monkeypatch.setattr(router.repo, "case_name_matches", lambda *args: rows)
    named = named_case("Which later decisions cite Umuhoza v Rwanda (2018)?")
    assert named is not None
    found = resolve_anchor(None, named, SearchFilters(), limit=5)  # type: ignore[arg-type]
    # The year rules out the closer 2016 ruling; the two tied 2018 decisions are kept.
    assert [r.canonical_uri for r in found] == ["/akn/2018-merits", "/akn/2018-reparations"]
    undated = named_case("Which later decisions cite Umuhoza v Rwanda?")
    assert undated is not None
    assert [r.canonical_uri for r in resolve_anchor(None, undated, SearchFilters(), 5)] == [  # type: ignore[arg-type]
        "/akn/2016-ruling"
    ]
