from datetime import date

import pytest

from ejudgment.ingestion.normalize import (
    clean_value,
    derive_title,
    normalize_case_number,
    normalize_citation,
    parse_akn_uri,
    parse_judgment_date,
    parse_neutral_citation,
    split_judges,
    strip_copy_suffix,
)


@pytest.mark.parametrize("value", [None, "", "  ", "N/A", "n/a", "NaN", "None", float("nan")])
def test_clean_value_maps_missing_markers_to_none(value: object) -> None:
    assert clean_value(value) is None


def test_clean_value_removes_nul_characters() -> None:
    assert clean_value("COUNSEL\x00\t23") == "COUNSEL\t23"
    assert clean_value("\x00") is None


def test_clean_value_strips_but_keeps_real_values() -> None:
    assert clean_value("  Supreme Court ") == "Supreme Court"
    assert clean_value(0) == 0


def test_strip_copy_suffix() -> None:
    assert strip_copy_suffix("[2022] GHASC 65Copy") == "[2022] GHASC 65"
    assert strip_copy_suffix("Lomotey v Richardson (15 June 2022)Copy ") == (
        "Lomotey v Richardson (15 June 2022)"
    )
    assert strip_copy_suffix("Copy") is None
    assert strip_copy_suffix(None) is None
    # Only a trailing UI label is removed, never the word inside a citation.
    assert strip_copy_suffix("Copyright Board v Asante") == "Copyright Board v Asante"


def test_normalize_citation() -> None:
    assert normalize_citation("Lomotey & Anor Vrs Richardson [2022] GHASC 65 (15 June 2022)") == (
        "LOMOTEY ANOR VRS RICHARDSON 2022 GHASC 65 15 JUNE 2022"
    )
    assert normalize_citation("[2019]  ghasc 12") == "2019 GHASC 12"


def test_parse_neutral_citation() -> None:
    parsed = parse_neutral_citation(
        "Ramadhani v Tanzania (Application No. 010/2015) [2018] AfCHPR 11"
    )
    assert parsed is not None
    assert (parsed.year, parsed.court, parsed.number) == (2018, "AfCHPR", 11)
    assert str(parsed) == "[2018] AfCHPR 11"
    assert parse_neutral_citation("no citation here") is None


@pytest.mark.parametrize(
    ("citation", "title"),
    [
        (
            "CHARLES AMPONSAH VRS ALICE DUAH (C5/185/2022) [2023] GHACC 1010 (10 March 2023)",
            "CHARLES AMPONSAH VRS ALICE DUAH",
        ),
        (
            "Lomotey & Anor Vrs Richardson & 3 Ors [2022] GHASC 65 (15 June 2022)",
            "Lomotey & Anor Vrs Richardson & 3 Ors",
        ),
        (
            "XYZ v Republic of Benin (Application No. 009/2020) [2025] AfCHPR 26 (26 June 2025)",
            "XYZ v Republic of Benin",
        ),
    ],
)
def test_derive_title(citation: str, title: str) -> None:
    assert derive_title(citation) == title


def test_normalize_case_number_collapses_multiline_lists() -> None:
    raw = "ECW/CCJ/APP/18/18\n          ;\n        \n          ECW/CCJ/JUD/33/19"
    assert normalize_case_number(raw) == "ECW/CCJ/APP/18/18; ECW/CCJ/JUD/33/19"
    assert normalize_case_number(None) is None


def test_parse_judgment_date_never_guesses() -> None:
    assert parse_judgment_date("17 June 1963") == date(1963, 6, 17)
    assert parse_judgment_date(" 5  July 1963 ") == date(1963, 7, 5)
    assert parse_judgment_date("3 March 201120 July 20113 March 2011") is None
    assert parse_judgment_date("sometime in 1999") is None
    assert parse_judgment_date(None) is None


def test_split_judges() -> None:
    raw = "Adumua-Bossman, JSC,\n                    \n   Akufo-Addo, JSC,\n\n   Crabbe, JSC"
    assert split_judges(raw) == ["Adumua-Bossman, JSC", "Akufo-Addo, JSC", "Crabbe, JSC"]
    assert split_judges(None) == []


def test_parse_akn_uri() -> None:
    identity = parse_akn_uri(
        "https://ghalii.org/akn/gh-hr-accra/judgment/ghahc/2020/10/eng@2020-01-10"
    )
    assert identity is not None
    assert identity.canonical_uri == "/akn/gh-hr-accra/judgment/ghahc/2020/10/eng@2020-01-10"
    assert identity.work_uri == "/akn/gh-hr-accra/judgment/ghahc/2020/10"
    assert identity.jurisdiction == "gh-hr-accra"
    assert identity.court_code == "ghahc"
    assert (identity.year, identity.number, identity.language) == (2020, "10", "eng")
    assert identity.expression_date == date(2020, 1, 10)


def test_parse_akn_uri_is_host_independent() -> None:
    a = parse_akn_uri("https://ghalii.org/akn/gh/judgment/ghasc/1963/1/eng@1963-06-17")
    b = parse_akn_uri("http://mirror.example/akn/gh/judgment/ghasc/1963/1/eng@1963-06-17/")
    assert a is not None and b is not None
    assert a.canonical_uri == b.canonical_uri


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://ghalii.org/judgments/all/2020/",
        "https://ghalii.org/akn/gh/judgment/ghasc/1963/1/eng@1963-13-45",
        "https://ghalii.org/akn/gh/act/1963/1/eng@1963-06-17",
    ],
)
def test_parse_akn_uri_rejects_non_judgment_uris(url: str | None) -> None:
    assert parse_akn_uri(url) is None
