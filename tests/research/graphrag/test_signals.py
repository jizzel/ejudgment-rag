"""v2 extraction signals: identifiers, stages, decision dates, caption flags, evidence spans."""

from datetime import date

import pytest

from experiments.graphrag.extraction.identifiers import (
    decision_date,
    identifiers,
    stages,
    stages_compatible,
)
from experiments.graphrag.extraction.mentions import evidence_span, find_references


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Communication 224/98 (2000) AHRLR 262", {"COMM 224/98"}),
        ("CRP v Nigeria Comm. 60/91 (1995)", {"COMM 60/91"}),
        ("(Communication 147 of 1995; Communication 149 of 1996)", {"COMM 147/95", "COMM 149/96"}),
        ("ACtHPR, Application No. 008/2020, Judgment", {"APP 8/20"}),
        ("(ECW/CCJ/APP/55/18; ECW/CCJ/JUD/13/19)", {"ECW-APP 55/18", "ECW-JUD 13/19"}),
        ("Fuseini v. Rep. (J4/32/2014) [2018]", {"SUIT J4/32/14"}),
        ("Abdul v Republic - H2/17/19 The", {"SUIT H2/17/19"}),  # short year: equal to 2019
        ("judgment of 12/05/2019 and Act 29", set()),  # a date, not a suit number
    ],
)
def test_identifiers(text: str, expected: set[str]) -> None:
    assert identifiers(text) == expected


def test_stages_and_compatibility() -> None:
    assert stages("Guehi v Tanzania (merits and reparations)") == {"merits", "reparations"}
    assert stages("(Order for Provisional Measures)") == {"provisional_measures"}
    assert stages("Judgment of 23 June 2022 (jurisdiction and admissibility)") == {"jurisdiction"}
    assert stages("Judgment on Reparations") == {"reparations"}
    # In running prose they are ordinary words, not a decision's stage.
    assert stages("the interpretation of Article 2 was, on review, merits-based") == set()
    order = frozenset({"provisional_measures"})
    assert not stages_compatible(frozenset({"merits"}), order)
    assert not stages_compatible(frozenset(), order)  # an unlabelled reference
    assert not stages_compatible(frozenset({"reparations"}), frozenset())  # not the merits
    assert stages_compatible(frozenset({"merits"}), frozenset())
    assert stages_compatible(frozenset(), frozenset())
    # A combined "merits and reparations" judgment is the main judgment.
    assert stages_compatible(frozenset(), frozenset({"merits", "reparations"}))
    # An admissibility ruling is often a case's final decision, titled without a stage.
    assert stages_compatible(frozenset({"jurisdiction"}), frozenset())
    assert not stages_compatible(frozenset(), frozenset({"jurisdiction"}))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Application No. 008/2020, Judgment of 23 June 2022 (jurisdiction)", date(2022, 6, 23)),
        ("judgment delivered on the 28th June 2007 held", date(2007, 6, 28)),
        ("[2018] GHASC 28 (09 May, 2018) , that", date(2018, 5, 9)),
        ("Suit No. J1/5/2021, delivered on 11th day of February, 2021, where", date(2021, 2, 11)),
        ("the Rules of Court of 1 September 2020 say", None),  # not the decision's date
        ("Judgment of 31 February 2020", None),
    ],
)
def test_decision_date(text: str, expected: date | None) -> None:
    assert decision_date(text) == expected


def test_signals_stop_at_the_sentence_end() -> None:
    text = (
        "17 Communication 299/05 – Anuak Justice Council v Ethiopia (2006) para. 58. 18 "
        "Communication 275/2003, Article 19 v The State of Eritrea (2007), para 65."
    )
    anuak = next(r for r in find_references(text) if r.name and "Anuak" in r.name.text)
    # Its own number comes first in the footnote; 275/2003 belongs to the next footnote.
    assert anuak.identifiers == {"COMM 299/05"}


def test_identifiers_before_a_citation_in_text_without_spaces() -> None:
    text = (
        "SuleimanvSudan(2003)ACHPR. 8Id,para39. 9Communications64/92,68/92and78/92–Krischna"
        "Achuthan(onbehalfofAlekeBanda)vMalawiACHPR(1994)ACHPR. 7Submissionsofthe"
    )
    first, second = find_references(text)
    assert first.identifiers == frozenset()  # nothing before it in its sentence
    assert second.identifiers == {"COMM 64/92", "COMM 68/92", "COMM 78/92"}


def test_running_header_with_suit_number_and_page_count() -> None:
    (reference,) = find_references(
        "even on a mere CHANCELLOR OPPONG KYEKYEKU KOHL V. CONSOLIDATED BANK GHANA (CBG) SUIT "
        "NO.:H1/95/2021 DATED 28TH NOVEMBER, 2022 Page 26 of 28 public policy grounds"
    )
    assert reference.caption_marker


def test_signals_stop_at_the_next_reference() -> None:
    text = (
        "Armand Guehi v. Tanzania, § 177, Christopher Jonas v. United Republic of Tanzania "
        "(reparations), § 24."
    )
    guehi, jonas = find_references(text)
    assert (guehi.stages, jonas.stages) == (frozenset(), {"reparations"})


@pytest.mark.parametrize(
    ("text", "caption"),
    [
        ("AZZ AR : PLAINTIFF/RESPONDENT/APPELLANT VERSUS ADH AD : DEFENDANT", True),
        ("GASPER ADOM ---- 2ND PLAINTIFF/APPLICANT VRS. NII MENSAH ---- 1ST DEFENDANT", True),
        ("(Represented by John Gerry Emmanuel) v The Republic of South Sudan Summary", True),
        ("robbery. 2 | Abdul Raman Watara Benjamin vrs The Republic - H2/17/19 The", True),
        ("The court held in Tetteh v Hayford that the plaintiff must prove his case.", False),
        ("Mary Quartey v. Francis Nutsugah Page 6 of 19 (3) notwithstanding", True),
        ("has no merit pg. 18 Majid SEIDU v. The REPUBLIC – JUDGMENT and ought", True),
        # Pinpoints and footnote rules are not headers.
        ("MALI (2007) @ pg. 72 para 26; DR. JERRY UGOKWE V. FRN & 1 OR, (2005) held", False),
        ("------------ [FN17] El Hadj Boubacar Diawara v Benin , July 1988", False),
        ("and the Republic v Ohene at pages 6 -7, the Supreme Court", False),
    ],
)
def test_caption_markers(text: str, caption: bool) -> None:
    (reference,) = [r for r in find_references(text) if r.name]
    assert reference.caption_marker is caption


def test_citing_cue_before_a_reference() -> None:
    cued, plain = (
        find_references("As held in Tetteh v Hayford, so.")[0],
        find_references("TETTEH V HAYFORD")[0],
    )
    assert (cued.cue_before, plain.cue_before) == (True, False)


def test_evidence_span_is_the_sentence_holding_the_reference() -> None:
    text = (
        "The court said so. In the case of Mensah v. Mensah [2012] 1 SCGLR 391 the Supreme "
        "Court held that property is shared. Next sentence here."
    )
    start, end = text.index("Mensah v."), text.index("391") + 3
    begin, finish = evidence_span(text, start, end)
    assert text[begin:finish] == (
        "In the case of Mensah v. Mensah [2012] 1 SCGLR 391 the Supreme Court held that "
        "property is shared."
    )
    assert begin <= start and finish >= end


def test_evidence_span_is_bounded() -> None:
    text = "x " * 500 + "Tetteh v Hayford" + " y" * 500
    start = text.index("Tetteh")
    begin, finish = evidence_span(text, start, start + 16, limit=50)
    assert start - begin <= 50 and finish - (start + 16) <= 50


def test_evidence_sentence_does_not_end_at_an_initial() -> None:
    text = (
        "uced by another party. See the case of ACCRA BREWERY LTD V JOHN TAGOE (2012 ) 48 G. "
        "M.J at page 44. Similarly in the case of"
    )
    (reference, *_) = find_references(text)
    begin, finish = evidence_span(text, reference.start, reference.end)
    assert text[begin:finish] == (
        "See the case of ACCRA BREWERY LTD V JOHN TAGOE (2012 ) 48 G. M.J at page 44."
    )


def test_evidence_sentence_keeps_initials_before_the_reference() -> None:
    text = (
        "Earlier text ends here. It was held per S. K. Date-Bah JSC in Tetteh v Hayford that "
        "costs follow the event. Next."
    )
    (reference,) = find_references(text)
    begin, finish = evidence_span(text, reference.start, reference.end)
    assert text[begin:finish].startswith("It was held per S. K. Date-Bah JSC")
