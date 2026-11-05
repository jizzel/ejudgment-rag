"""Resolution policy against a hand-built corpus index (no database)."""

from datetime import date

from experiments.graphrag.extraction.mentions import Reference, find_references
from experiments.graphrag.resolution.index import CorpusIndex, Judgment, neutral_key, title_sides
from experiments.graphrag.resolution.resolve import Resolution, Source, resolve

SOURCE_GROUP = "g-source"
SOURCE_DATE = date(2023, 5, 1)
SOURCE = Source(group=SOURCE_GROUP, date=SOURCE_DATE)  # a reference deep in the judgment


def judgment(
    jid: str, title: str, neutral: str, day: date, group: str | None = None, extra: str = ""
) -> Judgment:
    return Judgment(
        id=jid,
        uri=f"/akn/gh/judgment/{jid}",
        group=group or f"g-{jid}",
        title=title,
        citation=f"{title} {extra} {neutral}",
        neutral=neutral_key(neutral),
        date=day,
        court="ghasc",
    )


INDEX = CorpusIndex.build(
    [
        judgment("tetteh", "Tetteh and Another Vrs Hayford", "[2012] GHASC 12", date(2012, 2, 22)),
        # A re-publication of the same judgment under another URI: one case.
        judgment(
            "tetteh2",
            "Tetteh and Another Vrs Hayford",
            "[2012] GHASC 13",
            date(2012, 2, 22),
            "g-tetteh",
        ),
        # Two different judgments published under one citation (the [2023] GHADC 77 trap).
        judgment("dup-a", "Boateng Vrs Mensah", "[2023] GHADC 77", date(2023, 1, 5)),
        judgment("dup-b", "Ofori Vrs Ade", "[2023] GHADC 77", date(2023, 1, 9)),
        judgment("akilu", "Akilu Vrs Republic", "[2017] GHASC 11", date(2017, 7, 5)),
        judgment("addo", "Republic Vrs Philip Addo Teye", "[2023] GHACC 921", date(2023, 3, 24)),
        judgment("mensa", "Republic Vrs Mensa and Other", "[2022] GHAHC 5", date(2022, 3, 1)),
        judgment("asamoah1", "Asamoah Vrs Marfo", "[2011] GHASC 40", date(2011, 6, 1)),
        judgment("asamoah2", "Asamoah Vrs Marfo and Another", "[2016] GHACA 3", date(2016, 6, 1)),
        judgment("mensah", "Ama Mensah Vrs Kofi Owusu", "[2015] GHASC 7", date(2015, 1, 1)),
        judgment("later", "Kotei Vrs Kotei", "[2024] GHACC 1", date(2024, 6, 16)),
        judgment("self", "Sugone Vrs Bonful", "[2023] GHACC 330", SOURCE_DATE, SOURCE_GROUP),
        judgment(
            "allgate",
            "Republic Vrs High Court Accra Ex Parte Allgate",
            "[2008] GHASC 1",
            date(2008, 1, 1),
        ),
        # Decisions told apart by identifiers, stage and date (v2).
        judgment(
            "guehi-pm",
            "Guehi v United Republic of Tanzania",
            "[2016] AfCHPR 1",
            date(2016, 3, 18),
            extra="(Order for Provisional Measures) (Application 001/2015)",
        ),
        judgment(
            "mtikila-2011",
            "Mtikila v United Republic of Tanzania",
            "[2011] AfCHPR 53",
            date(2011, 9, 30),
            extra="(Application No. 011/2011)",
        ),
        judgment(
            "kodeih",
            "Kodeih and Another v Republic of Benin",
            "[2022] AfCHPR 17",
            date(2022, 6, 23),
            extra="(Application No. 008/2020)",
        ),
        judgment(
            "mra-224",
            "Media Rights Agenda v Nigeria",
            "[2000] ACHPR 24",
            date(2000, 11, 6),
            extra="(Communication 224 of 1998)",
        ),
        judgment(
            "mra-105",
            "Media Rights Agenda and Others v Nigeria",
            "[1998] ACHPR 18",
            date(1998, 10, 31),
            extra="(Communication 105 of 1993)",
        ),
        judgment(
            "fuseini",
            "Fuseini Vrs Republic",
            "[2018] GHASC 30",
            date(2018, 5, 9),
            extra="(J4/32/2014)",
        ),
        judgment(
            "tafali", "Tafali Vrs Yakubu", "[2018] GHASC 28", date(2018, 5, 9), extra="(J4/1/2017)"
        ),
        judgment(
            "john",
            "Republic Vrs John",
            "[2022] GHACC 332",
            date(2022, 11, 26),
            extra="(D21/031/24)",
        ),
        judgment("mensah-sc", "Mensah Vrs Mensah", "[2012] GHASC 8", date(2012, 2, 22)),
        judgment(
            "aryee", "Aryee Vrs Shell Ghana Ltd and Another", "[2015] GHASC 102", date(2015, 10, 22)
        ),
        judgment("frimpong", "Frimpong Vrs The Republic", "[2012] GHASC 3", date(2012, 1, 18)),
        # The citing case's own decision under another URI, with another text.
        judgment("kwaw-self", "Kwaw Vrs Duah", "[2023] GHACC 998", SOURCE_DATE, SOURCE_GROUP),
        judgment(
            "boateng-self",
            "Collins Boateng -vrs- Retired Majot Agyenim Boateng",
            "[2023] GHACA 11",
            SOURCE_DATE,
            SOURCE_GROUP,
        ),
        judgment(
            "boateng-copy",
            "COLLINS BOATENG VS RETIRED MAJOR AGYENIM BOATENG",
            "[2023] GHACA 12",
            SOURCE_DATE,
            extra="(H1/21/2023)",
        ),
        judgment(
            "jajah", "Republic Vrs Jajah Ex Parte Asafo Adjei", "[2023] GHAHC 31", date(2023, 1, 30)
        ),
        judgment("own-copy", "Kwaw Vrs Duah", "[2023] GHACC 999", SOURCE_DATE),
        # The citing case's own decision, and an earlier case with the same parties.
        judgment("adom-self", "Adom Vrs Badu", "[2023] GHACC 331", SOURCE_DATE, SOURCE_GROUP),
        judgment("adom-other", "Adom Vrs Badu and Another", "[2010] GHACC 2", date(2010, 1, 1)),
        judgment(
            "other-hc",
            "Republic Vrs High Court Accra Ex Parte Owusu",
            "[2009] GHASC 2",
            date(2009, 1, 1),
        ),
        # One proceeding (writ J1/5/2021), two decisions: a ruling and the final judgment (v5).
        judgment(
            "osei-ruling",
            "Osei Vrs Electoral Commission",
            "[2021] GHASC 4",
            date(2021, 2, 16),
            extra="(J1/5/2021)",
        ),
        judgment(
            "osei-judgment",
            "Osei Vrs Electoral Commission",
            "[2021] GHASC 9",
            date(2021, 3, 4),
            extra="(J1/5/2021)",
        ),
        # ECOWAS: an application number names the proceeding, a judgment number the decision.
        judgment(
            "kuma-jud",
            "Kuma Vrs Republic of Ghana",
            "[2018] ECOWASCJ 4",
            date(2018, 6, 1),
            extra="(ECW/CCJ/APP/08/09; ECW/CCJ/JUD/04/18)",
        ),
        judgment("kunutsor", "Kunutsor Vrs Tetteh", "[2008] GHACA 35", date(2008, 6, 12)),
        judgment(
            "sefa", "Rev. Sefa and Others Vrs Bank Of Ghana", "[2015] GHASC 109", date(2015, 11, 19)
        ),
        judgment(
            "duffour",
            "Republic Vrs Bank Of Ghana and Others; Ex Parte: Duffour",
            "[2018] GHASC 33",
            date(2018, 6, 6),
        ),
        # v10 audit: a one-sided title of another case under the cited number, and an
        # applicant who shares only a surname with the one cited.
        judgment("touray", "Emil Touray and Saikou Jammeh", "[2020] ACHPR 5", date(2020, 3, 1)),
        judgment("ada", "A Vrs ADA", "[2005] GHACA 7", date(2005, 5, 18)),
        judgment(
            "hansen-koduah",
            "Republic Vrs High Court, Judge Kumasi - Ex Parte: Hansen Kwadwo Koduah",
            "[2015] GHASC 125",
            date(2015, 7, 1),
        ),
        # Titles as the corpus prints them: one side only, and a hyphenated party.
        judgment(
            "jusag",
            "Judicial Service Staff Association Of Ghana",
            "[2016] GHASC 63",
            date(2016, 6, 1),
        ),
        judgment(
            "xtra",
            "X-tra Gold Mining Ltd Vrs Attorney General",
            "[2016] GHASC 57",
            date(2016, 7, 28),
        ),
        judgment(
            "duffour-8",
            "The Republic Vrs High Court, Commercial Division, Ex Parte Duffour & 8 Ors",
            "[2019] GHASC 5",
            date(2019, 1, 9),
        ),
        judgment(
            "kwabena",
            "Republic Vrs High Court, Commercial Division Accra, Ex Parte Kwabena Duffour",
            "[2021] GHASC 8",
            date(2021, 2, 10),
        ),
        judgment(
            "ampong",
            "Republic Vrs High Court, Sekondi; Ex Parte Ampong",
            "[2004] GHASC 9",
            date(2004, 3, 3),
        ),
        # An order of the same day as the jurisdiction ruling below.
        judgment(
            "umuhoza-order",
            "Umuhoza v Republic of Rwanda",
            "[2016] AfCHPR 32",
            date(2016, 6, 3),
            extra="(Order) (Application 003/2014)",
        ),
        # One application, a labelled jurisdiction ruling and an unlabelled merits judgment.
        judgment(
            "umuhoza-jur",
            "Umuhoza v Republic of Rwanda",
            "[2016] AfCHPR 30",
            date(2016, 6, 3),
            extra="(Ruling on Jurisdiction) (Application 003/2014)",
        ),
        judgment(
            "umuhoza-merits",
            "Umuhoza v Republic of Rwanda",
            "[2017] AfCHPR 13",
            date(2017, 11, 24),
            extra="(Application 003/2014)",
        ),
        judgment(
            "annan",
            "Annan and Another Vrs The Attorney-General",
            "[2022] GHASC 116",
            date(2022, 3, 31),
            extra="(J1/14/2020)",
        ),
        judgment(
            "badu-app",
            "Badu Vrs Republic of Ghana",
            "[2009] ECOWASCJ 2",
            date(2009, 1, 1),
            extra="(ECW/CCJ/APP/12/07)",
        ),
    ]
)


def run(text: str) -> Resolution:
    (reference,) = [r for r in find_references(text) if r.name or r.citations]
    return resolve(INDEX, reference, SOURCE)


def test_title_sides() -> None:
    assert title_sides("MAINOO  AND ANOTHER VRS. ATAA AND OTHERS") == [
        frozenset({"MAINOO"}),
        frozenset({"ATAA"}),
    ]


def test_neutral_exact_resolves_to_the_case() -> None:
    result = run("held in [2012] GHASC 12 that")
    assert (result.status, result.method, result.target_group) == (
        "resolved_exact",
        "neutral_exact",
        "g-tetteh",
    )
    assert result.target_ids == ("tetteh",)


def test_a_republication_is_one_case_not_two() -> None:
    # Both copies of Tetteh v Hayford answer to the name: one case, so it resolves.
    result = run("as in Tetteh v Hayford, the court")
    assert result.status == "resolved_unique_fuzzy"
    assert set(result.target_ids) == {"tetteh", "tetteh2"}


def test_one_citation_two_cases_is_ambiguous() -> None:
    assert run("see [2023] GHADC 77").status == "ambiguous"


def test_absent_neutral_citations() -> None:
    corpus_court = run("see [2021] GHASC 27")
    foreign = run("see [2008] UKHL 3")
    assert (corpus_court.status, corpus_court.foreign) == ("target_absent", False)
    assert (foreign.status, foreign.foreign) == ("target_absent", True)


def test_neutral_citation_contradicted_by_its_name_is_not_an_edge() -> None:
    result = run("Amankwah v The Republic [2012] GHASC 12")
    assert (result.status, result.reason, result.name_agrees) == (
        "ambiguous",
        "name_conflicts_with_citation",
        False,
    )
    assert run("Tetteh v Hayford [2012] GHASC 12").name_agrees is True


def test_shortened_title_matches_a_fuller_name() -> None:
    result = run("Faisal Mohammed Akilu v. The Republic [2017-2018] SCGLR 444")
    assert (result.status, result.method, result.target_ids) == (
        "resolved_unique_fuzzy",
        "name_with_report",
        ("akilu",),
    )


def test_a_shared_first_name_is_not_a_match() -> None:
    result = run("THE REPUBLIC VRS PHILIP AFORNORPE said")
    assert (result.status, result.reason) == ("unresolved", "no_candidate")


def test_one_shared_word_per_side_is_not_a_match() -> None:
    # Each side shares a word with the title (MENSAH, KOFI), but neither side contains
    # the other: these are different people.
    result = run("Kwame Mensah v Kofi Boateng [2015] 1 GLR 3")
    assert (result.status, result.reason) == ("unresolved", "no_candidate_in_report_years")


def test_a_lone_surname_against_a_generic_side_needs_a_report_year() -> None:
    # "Republic v Mensa" alone: the corpus's only Mensa case may not be the one cited.
    assert run("in Republic v Mensa the court").status == "unresolved"
    # With a report citation the year is evidence: 2022 lies in [2020, 2022].
    assert run("Republic v Mensa [2022] 1 GLR 5").status == "resolved_unique_fuzzy"
    assert run("Republic v Mensa [1975] 1 GLR 5").reason == "no_candidate_in_report_years"


def test_several_matching_cases_are_ambiguous_until_a_year_decides() -> None:
    assert run("as in Asamoah vs Marfo, the").status == "ambiguous"
    result = run("Asamoah vs Marfo [2011] SCGLR 12")
    assert (result.status, result.target_ids) == ("resolved_unique_fuzzy", ("asamoah1",))


def test_ex_parte_applicant_decides_between_cases() -> None:
    result = run("Republic v High Court, Accra; Ex parte Allgate Co. Ltd. [2008] SCGLR 1")
    assert result.target_ids == ("allgate",)
    assert run("Republic v High Court [2008] SCGLR 1").reason == "generic_names"  # generic


def test_own_case_is_a_self_reference() -> None:
    assert run("SUGONE VRS BONFUL & 2 OTHERS").status == "self_reference"


def test_target_later_than_source_is_kept_for_review() -> None:
    result = run("Christiana Kotei V Pious Kotei said")
    assert result.status == "temporal_conflict"
    assert (result.pre_temporal_status, result.target_ids) == ("resolved_unique_fuzzy", ("later",))


def test_report_without_name_is_never_mapped() -> None:
    result = run("held in [2012] 1 SCGLR 417 that")
    assert (result.status, result.reason, result.target_group) == (
        "unresolved",
        "report_without_name",
        None,
    )


def test_resolution_reads_only_the_reference() -> None:
    # The same name resolves the same way wherever it occurs in a chunk.
    references: list[Reference] = find_references("x. Tetteh v Hayford. y. Tetteh v Hayford.")
    results = {resolve(INDEX, r, SOURCE).target_group for r in references}
    assert results == {"g-tetteh"}


# --- v2: tiers, decision identity, agreement of signals, self references ----------------


def test_tiers_follow_the_evidence() -> None:
    assert run("held in [2012] GHASC 12 that").tier == "A"
    assert run("Faisal Mohammed Akilu v. The Republic [2017-2018] SCGLR 444").tier == "B"
    assert run("as in Tetteh v Hayford, the court").tier == "C"


def test_identifier_selects_the_decision_among_same_party_cases() -> None:
    # The name alone fits two Media Rights Agenda communications; the number decides.
    assert run("in Media Rights Agenda v. Nigeria, the").status == "ambiguous"
    # A proceeding number alone singles out the proceeding, not the decision: tier C.
    result = run("See Media Rights Agenda v. Nigeria Communication 224/98 (2000) AHRLR 262")
    assert (result.status, result.method, result.tier, result.target_ids) == (
        "resolved_unique_fuzzy",
        "name_with_proceeding",
        "C",
        ("mra-224",),
    )
    # With the decision's date beside it, the decision itself: tier B.
    result = run(
        "4 Ghaby Kodeih and Nabih Kodeih v. Republic of Benin, ACtHPR, "
        "Application No. 008/2020, Judgment of 23 June 2022"
    )
    assert (result.method, result.tier, result.target_ids) == (
        "name_with_dated_proceeding",
        "B",
        ("kodeih",),
    )
    # A stage label in the reference does not override an exact date on an unlabelled title.
    labelled = run(
        "4 Ghaby Kodeih and Nabih Kodeih v. Republic of Benin, ACtHPR, Application No. "
        "008/2020, Judgment of 23 June 2022 (jurisdiction and admissibility), § 49"
    )
    assert labelled.target_ids == ("kodeih",)


def test_a_stated_stage_must_match_the_decision() -> None:
    # The corpus holds only Guehi's provisional-measures order.
    merits = run("and Armand Guehi v. Tanzania (merits and reparations), § 177, x")
    assert (merits.status, merits.reason) == ("unresolved", "procedural_stage_mismatch")
    unlabelled = run("and Armand Guehi v. Tanzania said")
    assert unlabelled.reason == "procedural_stage_mismatch"  # not the main judgment
    order = run("and Armand Guehi v. Tanzania (provisional measures), § 3")
    assert order.target_ids == ("guehi-pm",)


def test_a_stated_judgment_date_must_match_the_decision() -> None:
    result = run(
        "Matter of Reverend Christopher Mtikila v. Tanzania (Application 009-001/2011), "
        "Judgment of 14 June 2013 paragraph 82"
    )
    assert (result.status, result.reason) == ("unresolved", "decision_date_mismatch")


def test_every_signal_next_to_a_neutral_citation_must_agree() -> None:
    conflict = run("the case of Fuseini v. Rep. (J4/32/2014) [2018] GHASC 28 (09 May, 2018) held")
    assert (conflict.status, conflict.reason) == ("ambiguous", "name_conflicts_with_citation")
    agrees = run("the case of Fuseini v. Rep. (J4/32/2014) [2018] GHASC 30 (09 May, 2018) held")
    assert (agrees.status, agrees.name_agrees) == ("resolved_exact", True)  # "Rep." = Republic
    wrong_number = run("in [2018] GHASC 30 (J4/99/2016) the")
    assert wrong_number.reason == "identifier_conflicts_with_citation"
    wrong_date = run("in [2018] GHASC 30 (12 January, 2018) the")
    assert wrong_date.reason == "date_conflicts_with_citation"


def test_a_longer_name_side_needs_its_surname_in_the_title() -> None:
    # "John Gandonu …" is not "Republic Vrs John": the surname is missing from the title.
    assert run("26. JOHN GANDONU V. FEDERAL REPUBLIC OF NIGERIA said").status == "unresolved"
    # "Stephen Mensah" is "Mensah": the right side's surname comes last.
    result = run("in Gladys Mensah v Stephen Mensah [2012]1 SCGLR 391 the")
    assert result.target_ids == ("mensah-sc",)


def test_captions_are_self_references() -> None:
    early = Source(group=SOURCE_GROUP, date=SOURCE_DATE, offset=200)

    def at_start(text: str) -> Resolution:
        (reference,) = find_references(text)
        return resolve(INDEX, reference, early)

    marked = run("AZZ AR : PLAINTIFF/RESPONDENT/APPELLANT VERSUS ADH AD : DEFENDANT")
    assert (marked.status, marked.reason) == ("self_reference", "caption")
    assert at_start("KOTEI V KOTEI").reason == "caption"  # the opening caption zone
    assert at_start("held in Kotei v Kotei that").reason != "caption"  # a citing cue
    assert at_start("Tetteh v Hayford [2012] 1 SCGLR 417").reason != "caption"  # a citation


def test_own_suit_number_is_a_self_reference() -> None:
    own = Source(group=SOURCE_GROUP, date=SOURCE_DATE, identifiers=frozenset({"SUIT H2/17/19"}))
    (reference,) = find_references("as stated in Abdul v Mensah (H2/17/19) the court")
    result = resolve(INDEX, reference, own)
    assert (result.status, result.reason) == ("self_reference", "own_identifier")


def test_own_case_among_other_candidates_is_ambiguous() -> None:
    result = run("as held in Adom v Badu, the")
    assert (result.status, result.reason) == ("ambiguous", "includes_own_case")


def test_anchors_with_several_parties_and_aliases() -> None:
    # The right side's first party is "Shell Ghana Ltd"; the second party is not in the title.
    result = run("See also Aryee v Shell Ghana Ltd & Fraga Oil Ltd (2017-2020) SCGLR 721 at 733")
    assert result.target_ids == ("aryee",)
    # "aka Iboman" is an alias: the surname before it is the anchor.
    alias = run("KWAKU FRIMPONG AKA IBOMAN VRS THE REPUBLIC (2012) GHASC 3 (18TH JANUARY 2012)")
    assert (alias.status, alias.name_agrees) == ("resolved_exact", True)


def test_a_republication_of_the_citing_case_is_a_self_reference() -> None:
    citing = Source(group=SOURCE_GROUP, date=SOURCE_DATE, judgment_id="kwaw-self")
    (reference,) = find_references("as stated in [2023] GHACC 999 above")
    result = resolve(INDEX, reference, citing)
    assert (result.status, result.reason) == ("self_reference", "republication_of_citing_case")
    # Without knowing the citing judgment, it is an ordinary edge.
    assert resolve(INDEX, reference, SOURCE).status == "resolved_exact"


def test_hyphenated_title_separator() -> None:
    assert title_sides("Collins Boateng -vrs- Retired Majot Agyenim Boateng") == [
        frozenset({"COLLINS", "BOATENG"}),
        frozenset({"RETIRED", "MAJOT", "AGYENIM", "BOATENG"}),
    ]


def test_same_day_same_parties_is_the_citing_case_despite_a_title_slip() -> None:
    citing = Source(group=SOURCE_GROUP, date=SOURCE_DATE, judgment_id="boateng-self")
    (reference,) = find_references(
        "the length of the trial. SUIT NO: H1/21/2023, COLLINS BOATENG VRS RETIRED MAJOR "
        "AGYENIM BOATENG & ANOR held"
    )
    result = resolve(INDEX, reference, citing)
    assert (result.status, result.reason) == ("self_reference", "republication_of_citing_case")


def test_an_unlinked_adjacent_name_must_agree_with_a_neutral_citation() -> None:
    conflict = run("such as: Adjei v Ak werter [2023] GHAHC 31 , 31/07/2023 and")
    assert (conflict.status, conflict.reason) == (
        "ambiguous",
        "adjacent_name_conflicts_with_citation",
    )
    agrees = run("such as: Republic v Jajah [2023] GHAHC 31 , and")
    assert agrees.status == "resolved_exact"


def test_a_dated_proceeding_resolves_to_that_decision_never_another() -> None:
    # Rows 20 and 34 of the v4 audit: rulings in a writ resolved to its final judgment.
    ruling = run("in Osei v. Electoral Commission, Writ No. J1/5/2021, Dated 2021 -02-16, x")
    assert (ruling.method, ruling.target_ids) == ("name_with_dated_proceeding", ("osei-ruling",))
    worded = run("in Osei v. Electoral Commission, J1/5/2021 ( 16th February, 2021), x")
    assert worded.target_ids == ("osei-ruling",)
    # A ruling the corpus lacks: unresolved, not the proceeding's final judgment.
    missing = run("in Osei v. Electoral Commission, J1/5/2021, dated 11th February, 2021, x")
    assert (missing.status, missing.reason) == ("unresolved", "no_decision_matches_date_or_stage")
    # The number alone names the proceeding: two decisions, so no edge at all.
    alone = run("in Osei v. Electoral Commission, J1/5/2021, the court")
    assert (alone.status, alone.method, alone.tier) == ("ambiguous", "name_with_proceeding", "C")


def test_a_decision_number_names_the_decision() -> None:
    result = run("in Kuma v. Ghana, ECW/CCJ/JUD/04/18, the Court")
    assert (result.status, result.method, result.tier, result.target_ids) == (
        "resolved_unique_fuzzy",
        "name_with_decision_identifier",
        "B",
        ("kuma-jud",),
    )


def test_numbers_of_different_cases_beside_one_name_are_refused() -> None:
    # Row 18 of the v4 audit: two ECOWAS application numbers of two cases, one name.
    result = run("in Kuma v. Ghana ECW/CCJ/APP/08/09 and ECW/CCJ/APP/12/07, the Court")
    assert (result.status, result.reason) == ("ambiguous", "conflicting_identifiers")
    # Numbers of one decision (its application and judgment numbers) are not a conflict.
    same = run("in Kuma v. Ghana ECW/CCJ/APP/08/09 and ECW/CCJ/JUD/04/18, the Court")
    assert same.target_ids == ("kuma-jud",)


def test_an_identifier_later_in_the_sentence_belongs_to_another_authority() -> None:
    # Row 13 of the v4 audit: a suit number of a separate, unnamed authority.
    (reference, *_) = find_references(
        "as held in Osei v. Electoral Commission and the later ruling of this court in "
        "J1/5/2021 that"
    )
    assert reference.identifiers == frozenset()


def test_a_date_before_the_proceeding_number_still_binds_it() -> None:
    # Review of v5: "dated 11 February 2021, Writ No. …" lost the writ number.
    result = run("in Osei v. Electoral Commission, dated 16 February 2021, Writ No. J1/5/2021, x")
    assert (result.method, result.target_ids) == ("name_with_dated_proceeding", ("osei-ruling",))


def test_a_stage_label_may_mean_an_unlabelled_decision_of_the_proceeding() -> None:
    # Review of v5: "(merits)" against a corpus decision titled without a stage.
    result = run("Kodeih v. Republic of Benin, Application No. 008/2020 (merits), § 12")
    assert (result.method, result.target_ids) == ("name_with_dated_proceeding", ("kodeih",))


def test_an_ocr_split_name_still_agrees_with_its_neutral_citation() -> None:
    # Pilot p3-in-11 under phase2-v2: "Kunuts or V Tetteh" was read as a different case.
    result = run("See: Kunuts or V Tetteh (160 of 2006) [2008] GHACA 35 (12 June 2008 CA.")
    assert (result.status, result.target_ids) == ("resolved_exact", ("kunutsor",))


def test_a_contradicting_writ_number_refuses_a_name_and_date_match() -> None:
    # Audit f17184ccb15c row 59: name and date fit, but the writ number is another suit's.
    result = run(
        "AND Dr Isaac Annan & Anor v. Attorney -General (Writ No. LL/14/2019, Dated 31ST March "
        "2022). However"
    )
    assert result.status == "unresolved" and result.reason == "identifier_mismatch"


def test_a_labelled_stage_prefers_the_decision_that_carries_it() -> None:
    # Removal review row 3: "Ruling on Jurisdiction" also fits an unlabelled final decision,
    # but the proceeding has a decision labelled with that very stage.
    result = run("5 Umuhoza v Republic of Rwanda Application No. 003/2014 (Ruling on Jurisdiction)")
    assert (result.method, result.target_ids) == ("name_with_dated_proceeding", ("umuhoza-jur",))
    dated = run(
        "5 Umuhoza v Rwanda Application No. 003/2014 (Ruling on Jurisdiction of 3 June 2016)"
    )
    assert dated.target_ids == ("umuhoza-jur",)


def test_a_hyphenated_forename_the_title_lacks_still_matches() -> None:
    # Removal review row 2: the title is "Rev. Sefa and Others", without "De-Graft".
    result = run(
        "and REV. DE -GRAFT SEFA & Others v BANK OF GHANA (Unreported Judgment of this Court in "
        "Civil Appeal No. J4/51/2014 dated 19th November 2015 )."
    )
    assert result.target_ids == ("sefa",)


def test_an_ex_parte_applicant_matches_by_surname_across_other_respondents() -> None:
    # v8 profile: "Ex – PARTE BENJAMIN DUFFOUR" against a title "Ex Parte: Duffour", and an
    # applicant named after further respondents.
    spaced = run(
        "REPUBLIC V BANK OF GHANA AND 5 ORS  EX – \nPARTE BENJAMIN DUFFOUR, CIVIL APPEAL NO. "
        "J4/34/2018 DATED 6TH \nJUNE , 2018  (unreported) at pages"
    )
    assert spaced.target_ids == ("duffour",)
    after = run(
        "See: The Republic v Bank of Ghana, The Governor (Bank of Ghana) and 4 others Ex-parte "
        "Benjamin Duffour, Civil Appeal No. J4/34/2018, dated 6th June 2018."
    )
    assert after.target_ids == ("duffour",)


def test_an_ex_parte_applicant_is_matched_by_first_word_before_surname() -> None:
    # v8 profile: the surname alone lost "Ex parte Ampong Alias Akrufa Krukoko".
    result = run(
        "Republic v High Court, Sekondi; Ex parte Ampong Alias Akrufa Krukoko [2004] 1 GLR 55"
    )
    assert result.target_ids == ("ampong",)


def test_the_applicants_first_word_tells_same_surname_cases_apart() -> None:
    # v8 profile: by surname alone, "Ex parte Kwabena Duffour" also fit "Ex Parte: Duffour".
    result = run(
        "REPUBLIC VRS HIGH COURT, COMMERCIAL DIVISION, ACCRA; EX PARTE KWABENA DUFFOUR "
        "[2021] 1 SCGLR 100"
    )
    assert result.target_ids == ("kwabena",)


def test_a_name_beside_its_citation_conflicts_only_when_it_names_another_case() -> None:
    # Edges audited correct, refused once v6 linked their names: a one-sided corpus title, and
    # "XTRA" against "X-tra".
    jusag = run(
        "in Judicial Service Staff Association of Ghana v. Attorney -General & Ors [2016] GHASC 63"
    )
    assert (jusag.status, jusag.target_ids) == ("resolved_exact", ("jusag",))
    xtra = run("XTRA GOLD MINING LIMITED VRS ATTORNEY -GENERAL (J1/23/2015) (2016) GHASC 57 held")
    assert (xtra.status, xtra.target_ids) == ("resolved_exact", ("xtra",))
    # A genuinely different case beside a citation is still refused (v1 audit's Fuseini row).
    other = run("in Kofi Mensah v. Ama Owusu [2016] GHASC 57")
    assert (other.status, other.reason) == ("ambiguous", "name_conflicts_with_citation")


def test_a_one_sided_title_must_still_share_a_word_with_the_name() -> None:
    # v10 audit row 2: [2020] ACHPR 5 is Emil Touray, not Miles Investments.
    result = run("in Miles Investments & 2Others v. Republic of Sierra Leone (2020) ACHPR 5, the")
    assert (result.status, result.reason) == ("ambiguous", "name_conflicts_with_citation")


def test_a_surname_fallback_refuses_an_applicant_with_other_names() -> None:
    # v10 audit rows 5, 25, 32: "Ex parte Tweneboah Koduah" is not "Ex Parte: Hansen Kwadwo
    # Koduah"; "Ex parte Benjamin Duffour" still finds "Ex Parte: Duffour".
    result = run(
        "REPUBLIC v HIGH COURT, (FINANCIAL DIVISION) ACCRA; EX PARTE TWENEBOAH KODUAH "
        "[2015] 81 GMJ 191 held"
    )
    assert result.target_ids == ()


def test_an_anonymised_title_gives_no_ground_for_a_conflict() -> None:
    # v11 profile: "Abubakari vs Abubakari [2005] GHACA 7" is titled "A Vrs ADA" in the
    # corpus (audited correct); only a title without its "v" is checked on one side.
    result = run("in Abubakari vs Abubakari [2005] GHACA 7, the court")
    assert (result.status, result.target_ids) == ("resolved_exact", ("ada",))


def test_shared_parties_do_not_excuse_a_different_ex_parte_applicant() -> None:
    # PR #24 review: the looser name check let Owusu's application agree with Allgate's
    # citation, since both name the Republic and the High Court.
    result = run("in Republic v High Court, Accra; Ex parte Owusu [2008] GHASC 1, the court")
    assert (result.status, result.reason) == ("ambiguous", "name_conflicts_with_citation")
    # The right applicant still agrees.
    same = run("in Republic v High Court, Accra; Ex parte Allgate [2008] GHASC 1, the court")
    assert (same.status, same.target_ids) == ("resolved_exact", ("allgate",))
