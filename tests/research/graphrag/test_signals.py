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


def test_a_footnote_neighbour_keeps_its_own_application_number() -> None:
    # v5 profile: "…, Application No. 058/2016, …; Ajavon v. Benin, Application No. 065/2019"
    # lent 058/2016 to Ajavon, and the two numbers then looked like a conflict.
    first, second = find_references(
        "See Mtikila v. Tanzania, ACtHPR, Application No. 058/2016, Judgment of 29 March 2019, "
        "para 4; Ajavon v. Republic of Benin, ACtHPR, Application No. 065/2019, Judgment of "
        "29 March 2021 (merits)."
    )
    assert first.identifiers == {"APP 58/16"}
    assert second.identifiers == {"APP 65/19"}


def test_a_decision_number_split_by_the_name_boundary_still_binds() -> None:
    # Review of v5: the name took "ECW", leaving "/CCJ/JUD/16/20" outside it.
    (reference,) = find_references(
        "in MAHAMA V FEDERAL REPUBLIC OF NIGERIA \nECW /CCJ/JUD/16/20, the"
    )
    assert "ECW-JUD 16/20" in reference.identifiers


def test_a_hyphenated_name_spaced_by_ocr_keeps_its_writ_number() -> None:
    # Audit f17184ccb15c row 59: the name stopped at "Attorney", so the writ number that
    # contradicts the target was never read.
    (reference,) = find_references(
        "AND Dr Isaac Annan & Anor v. Attorney -General (Writ No. LL/14/2019, Dated 31ST March "
        "2022). However"
    )
    assert reference.name is not None and reference.name.text.endswith("-General")
    assert reference.identifiers == {"SUIT LL/14/19"}


def test_a_hyphenated_name_ends_after_its_continued_word() -> None:
    # Removal review rows 5, 6, 8: the side ran on into "Writ", "S. C." and "DECEASED".
    (writ,) = find_references(
        "in Kpodo v. Attorney -General Writ No. J1/03/2018; judgment dated 12th June, 2019, x"
    )
    assert writ.name is not None and writ.name.text.endswith("Attorney -General")
    assert writ.identifiers == {"SUIT J1/3/18"}
    (descriptor,) = find_references("In Mfum Farms Ltd Vrs Madam Agnes Gyamfua – Deceased, the")
    assert descriptor.name is not None and descriptor.name.text.endswith("Gyamfua")
    (glued,) = find_references("in Welford Quarcoo v. Attorney -General& Anor (2012) SCGLR 259.")
    assert glued.name is not None and glued.name.text.endswith("Anor")
    assert glued.kind == "name_with_report"
    (applicant,) = find_references(
        "REPUBLIC V BANK OF GHANA AND 5 ORS EX – PARTE BENJAMIN DUFFUOR, x"
    )
    assert applicant.name is not None and "BENJAMIN" in applicant.name.text


def test_a_neighbours_writ_number_does_not_lead_into_the_next_name() -> None:
    # Removal review rows 4 and 7: each writ number belongs to the citation before it.
    agbleze, bomfeh = find_references(
        "Mayor Agbleze v Attorney -General S. C. [Writ No J1/28/2018] dated 28th November 2018 "
        "(Unreported) Bomfeh v Attorney -General S. C. [Writ No J1/14/2017] dated 23rd January "
        "2019 (Unreported)."
    )
    assert agbleze.identifiers == {"SUIT J1/28/18"}
    assert bomfeh.identifiers == {"SUIT J1/14/17"}
    assert bomfeh.decision_date == date(2019, 1, 23)


def test_a_stage_may_stand_between_the_decision_label_and_its_date() -> None:
    assert decision_date("(Ruling on Jurisdiction of 3 June 2016)") == date(2016, 6, 3)
    assert decision_date("Judgment on Reparations of 7 December 2018") == date(2018, 12, 7)


def test_dashed_surnames_and_ex_parte_names_continue() -> None:
    # v7 profile: en dashes join Ghanaian double surnames, and "Ex -parte" leads the applicant.
    (bonnie,) = find_references(
        "Republic Vs. Baffoe – Bonnie And 4 Others (2017 – 2020) 1 SCGLR 322"
    )
    assert bonnie.name is not None and "Bonnie And 4 Others" in bonnie.name.text
    assert bonnie.kind == "name_with_report"
    (osafo,) = find_references("in Republic V. High Court Ex -parte Osafo (2011) 2 SCGLR 966.")
    assert osafo.name is not None and osafo.name.text.endswith("Osafo")
    assert osafo.kind == "name_with_report"


def test_leading_decision_numbers_bind_through_their_label_text() -> None:
    # v7 profile: these were lost by a stricter leading rule, since reverted.
    (bah,) = find_references(
        "Thus, it can be seen from JUDGMENT No. ECW/CCJ/JUD/11/2015, delivered in the case "
        "Mohammed EL Tayyib Bah v. Republic of Sierra Leone, where this Court held"
    )
    assert bah.identifiers == {"ECW-JUD 11/15"}


def test_an_unlinked_neighbour_keeps_its_writ_number() -> None:
    # Removal review row 4: OCR split "Agbleze", so no reference ended where its number did.
    *_, bomfeh = find_references(
        "1 SCGLR 1 Mayor Ag bleze & Ors v Attorney -General S. C. [Writ No J1/28/2018 ] dated "
        "28th November 2018 (Unreported) Bomfeh v Attorney -General S. C. [Writ No J1/14/2017] "
        "dated 23rd January 2019 (Unreported)."
    )
    assert bomfeh.identifiers == {"SUIT J1/14/17"}


def test_a_bulleted_party_keeps_its_name() -> None:
    # v8 profile: a list of authorities, each line led by a dash.
    *_, frimpong = find_references(
        "-DEXTER JOHNSON V THE REPUBLIC [2011] 2 SCGLR 601\n-FRIMPONG A.K.A IBOMAN V REPUBLIC "
        "[2012] 1 SCGLR 297\nAs already indicated"
    )
    assert frimpong.name is not None and "FRIMPONG" in frimpong.name.left_words
