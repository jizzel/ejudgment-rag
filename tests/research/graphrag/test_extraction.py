"""Citation, case-name and reference extraction (synthetic strings only)."""

import pytest

from experiments.graphrag.extraction.case_names import find_case_names
from experiments.graphrag.extraction.citations import find_citations
from experiments.graphrag.extraction.mentions import find_references


@pytest.mark.parametrize(
    ("text", "kind", "key"),
    [
        ("held in [2019] GHASC 12 that", "neutral", "[2019] GHASC 12"),
        ("[2009] AfCHPR 4", "neutral", "[2009] AFCHPR 4"),
        ("Smith [2019] EWCA Civ 12 at", "neutral", "[2019] EWCA CIV 12"),
        ("see 2020 GHASC 104", "neutral", "[2020] GHASC 104"),  # typed without brackets
        ("[1976] 1 GLR 204", "law_report", "[1976] 1 GLR 204"),
        ("Appiah[1981]GLR752where", "law_report", "[1981] GLR 752"),  # spaces lost
        ("[2013-2014]1 SCGLR 534", "law_report", "[2013-2014] 1 SCGLR 534"),
        ("[1995-96]1 GLR 598", "law_report", "[1995-1996] 1 GLR 598"),
        ("[1984 -86] GLR 697", "law_report", "[1984-1986] GLR 697"),
        ("(1957) 3 WALR 12", "law_report", "[1957] 3 WALR 12"),
        ("[1951] A.C. 123", "law_report", "[1951] AC 123"),
        ("[2008] 1 All ER 5", "law_report", "[2008] 1 ALLER 5"),
        ("Ampah v The Republic 1977 2 GLR 171", "law_report", "[1977] 2 GLR 171"),
        ("Kotei v. Kotei [1 974] 2 GLR 172; Ash", "law_report", "[1974] 2 GLR 172"),  # OCR space
        ("Wade v. Senegal (2013) CCJELR page 257 paragraph", "law_report", "[2013] CCJELR 257"),
        ("Tagoe (2012 ) 48 G. M.J at page 44.", "law_report", "[2012] 48 GMJ 44"),
        ("Boateng v Ntim [1961] GLR (Pt,II) 671 at 674", "law_report", "[1961] GLR 671"),
        ("[2011] ISCGLR 466", "law_report", "[2011] ISCGLR 466"),  # "1" read as "I"
        ("(1992) Article 19", "unclassified", "[1992] ARTICLE 19"),
    ],
)
def test_citation_kinds_and_keys(text: str, kind: str, key: str) -> None:
    (citation,) = find_citations(text)
    assert (citation.kind, citation.key) == (kind, key)
    assert text[citation.start : citation.end] == citation.text


@pytest.mark.parametrize(
    "text",
    [
        "the year [2019] was a hard one",  # no court or series
        "the 1992 Constitution 19 says",  # unbracketed and not a known series
        "section 5(v) of Act 29",
        "paid GH¢ 2019 GLR",  # no page number
    ],
)
def test_not_citations(text: str) -> None:
    assert find_citations(text) == []


def test_neutral_needs_a_known_court_and_no_volume() -> None:
    # A volume number makes it a report; a court outside both lists is unclassified.
    assert [c.kind for c in find_citations("[2019] 1 GHASC 12; [2019] XYZQ 3")] == [
        "unclassified",
        "unclassified",
    ]


@pytest.mark.parametrize(
    ("text", "span", "left", "right"),
    [
        (
            "in the case of Knudsen V Knudsen [1976] 1 GLR 204",
            "Knudsen V Knudsen",
            "KNUDSEN",
            "KNUDSEN",
        ),
        (
            "case of Mahama Hausa v rs Baako Hausa [1972]",
            "Mahama Hausa v rs Baako Hausa",
            "HAUSA",
            "BAAKO",
        ),
        (
            "See Behome vrs The Republic [1979] GLR 112",
            "Behome vrs The Republic",
            "BEHOME",
            "REPUBLIC",
        ),
        (
            "Commissioner of Police v Antwi, the court",
            "Commissioner of Police v Antwi",
            "POLICE",
            "ANTWI",
        ),
        ("13\nIgola Iguna v. Tanzania said", "Igola Iguna v. Tanzania", "IGUNA", "TANZANIA"),
        ("OWUSU V ARHIN & ANOR[1967] GLR 114", "OWUSU V ARHIN & ANOR", "OWUSU", "ARHIN"),
        ("ARTHUR VRS ARTHUR (J4/20/2013) [2014]", "ARTHUR VRS ARTHUR", "ARTHUR", "ARTHUR"),
        (
            "Communication 308/2005-Michael Majuru v Zimbabwe- (2008)",
            "Majuru v Zimbabwe",
            "MAJURU",
            "ZIMBABWE",
        ),
        (
            "Equality Now and Ethiopian Women 61 Doebbler v Sudan (2003)",
            "Doebbler v Sudan",
            "DOEBBLER",
            "SUDAN",
        ),
        (
            "Joseph Nyarko & 3 Ors v Paul Addy [2019]",
            "Joseph Nyarko & 3 Ors v Paul Addy",
            "NYARKO",
            "PAUL",
        ),
        ("Kenya. 2° Cudjoe v Ghana (2000) AHRLR 127", "Cudjoe v Ghana", "CUDJOE", "GHANA"),
        (
            "case of JIBRIL MAHAMA V AKWASI MENSAH CA NO, J4/45/2019 in",
            "JIBRIL MAHAMA V AKWASI MENSAH",
            "MAHAMA",
            "AKWASI",
        ),
        (
            "4 AfCLR 49, Â§ 158 and Sébastien Germain Ajavon v. Republic of Benin (reparations)",
            "Sébastien Germain Ajavon v. Republic of Benin",
            "AJAVON",
            "REPUBLIC",
        ),
    ],
)
def test_case_names(text: str, span: str, left: str, right: str) -> None:
    (name,) = find_case_names(text)
    assert (name.text, name.left_word, name.right_word) == (span, left, right)
    assert text[name.start : name.end] == name.text


def test_case_name_sides_hold_every_significant_word() -> None:
    (name,) = find_case_names("as in Faisal Mohammed Akilu v. The Republic [2017] held")
    assert name.left_words == {"FAISAL", "MOHAMMED", "AKILU"}
    assert name.right_words == {"REPUBLIC"}


def test_ex_parte_with_a_dash_and_a_bracketed_division() -> None:
    (name,) = find_case_names(
        "and the REPUBLIC VRS HIGH COURT AND ANOTHER ; EX – PARTE OHENE [1995 –96] GLR 1"
    )
    assert name.ex_parte_word == "OHENE"


def test_ex_parte_applicant() -> None:
    (name,) = find_case_names(
        "held in Republic v. High Court, Accra; Ex parte Allgate Co. Ltd. [2007]"
    )
    assert name.text == "Republic v. High Court, Accra; Ex parte Allgate Co. Ltd."
    assert (name.left_word, name.right_word, name.ex_parte_word) == ("REPUBLIC", "HIGH", "ALLGATE")


@pytest.mark.parametrize(
    "text",
    [
        "He said that section 5(v) applies.",  # (v) is a paragraph number
        "The plaintiff v the defendant.",  # lowercase sides
        "& Ors vs Akyea",  # no significant word on the left
        "Woodv Smith",  # no separator
    ],
)
def test_not_case_names(text: str) -> None:
    assert find_case_names(text) == []


def test_left_side_stops_at_an_earlier_citation() -> None:
    text = "(2012) 1 SCGLR 417 COLEMAN v TRIPOLLEN & OTHERS"
    (reference,) = [r for r in find_references(text) if r.name]
    assert reference.name is not None
    assert reference.name.text == "COLEMAN v TRIPOLLEN & OTHERS"


def test_reference_links_name_suit_number_and_parallel_citations() -> None:
    text = "REPUBLIC VRS NSOR (BR/SY/CT/195/2024) [2011] 1 SCGLR 466; [2011] GHASC 3 held"
    (reference,) = find_references(text)
    assert reference.name is not None and reference.name.text == "REPUBLIC VRS NSOR"
    assert [c.key for c in reference.citations] == ["[2011] 1 SCGLR 466", "[2011] GHASC 3"]
    assert reference.kind == "neutral"
    assert text[reference.start : reference.end] == text[: text.index(" held")]


def test_reference_kinds() -> None:
    text = (
        "Odoi vs Hammond [1971] 2 GLR 375 and later [1971] 1 GLR 242, then Asamoah vs Marfo, "
        "and [1992] XYZQ 3."
    )
    assert [r.kind for r in find_references(text)] == [
        "name_with_report",
        "report_only",
        "name_only",
        "unclassified_only",
    ]
    assert find_references(text)[0].report_years == (1971, 1971)


def test_offsets_slice_back_to_the_matched_text() -> None:
    text = "x " * 40 + "Tetteh v Hayford [2012] 1 SCGLR 417 at 420"
    for reference in find_references(text):
        assert text[reference.start : reference.end] == "Tetteh v Hayford [2012] 1 SCGLR 417"
