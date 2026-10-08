import uuid

import pytest
from pydantic import ValidationError

from ejudgment.api.errors import _validation_code
from ejudgment.config import Settings
from ejudgment.domain.enums import PageReferenceStatus
from ejudgment.domain.schemas import SearchFilters, SearchRequest
from ejudgment.ingestion.chunk_service import _PageRow, select_source
from ejudgment.ingestion.tokenizer import HfTokenizer, TokenizerUnavailable
from ejudgment.retrieval.query import escape_like, names_every_party, parse_query, party_words


@pytest.mark.parametrize(
    ("query", "citation"),
    [
        ("[2020] GHASC 104", "[2020] GHASC 104"),
        ("what did 2020 GHASC 104 decide", "[2020] GHASC 104"),
        ("Ramadhani [2018] AfCHPR 11", "[2018] AfCHPR 11"),
        ("2018 AfCHPR 11", "[2018] AfCHPR 11"),
    ],
)
def test_citation_detection(query: str, citation: str) -> None:
    parsed = parse_query(query)
    assert parsed.neutral_citation is not None
    assert str(parsed.neutral_citation) == citation


@pytest.mark.parametrize(
    "query", ["contract signed in 2020 between 3 parties", "Act 29 of 1960", "2020 Ghana 12"]
)
def test_no_false_citation(query: str) -> None:
    assert parse_query(query).neutral_citation is None


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Mensah v Owusu", True),
        ("Republic vrs High Court", True),
        ("Lomotey v. Richardson", True),
        ("versus in a sentence", False),
        ("negligence and damages", False),
    ],
)
def test_case_name_detection(query: str, expected: bool) -> None:
    assert parse_query(query).looks_like_case_name is expected


def test_query_whitespace_is_normalized() -> None:
    assert parse_query("  land \n  title  ").text == "land title"


def test_escape_like() -> None:
    assert escape_like("50%_a\\b") == "50\\%\\_a\\\\b"


def test_filters_are_validated_strictly() -> None:
    assert SearchFilters(court="ghasc", year_from=2010, year_to=2020).applied() == {
        "court": "ghasc",
        "year_from": 2010,
        "year_to": 2020,
    }
    with pytest.raises(ValidationError):
        SearchFilters(court="GHASC; DROP TABLE")
    with pytest.raises(ValidationError):
        SearchFilters(year_from=2021, year_to=2020)
    with pytest.raises(ValidationError):
        SearchFilters.model_validate({"unknown_filter": "x"})
    with pytest.raises(ValidationError):
        SearchRequest(query="")


def test_validation_error_codes() -> None:
    assert _validation_code([{"loc": ["body", "filters", "court"], "type": "x"}]) == (
        "invalid_filter"
    )
    assert _validation_code([{"loc": ["body", "query"], "type": "string_too_short"}]) == (
        "query_empty"
    )
    assert _validation_code([{"loc": ["body", "top_k"], "type": "less_than_equal"}]) == (
        "invalid_request"
    )


def _row(kind: str, verification: str, page_index: int | None, text: str, method: str) -> _PageRow:
    return _PageRow(
        uuid.uuid5(uuid.NAMESPACE_URL, kind), kind, verification, page_index, method, text
    )


def test_select_source_prefers_pdf_pages_then_legacy_then_html() -> None:
    html = _row("html", "not_applicable", None, "html text", "legacy")
    legacy = _row("legacy", "not_applicable", None, "legacy text", "legacy")
    pdf_pages = [
        _row("pdf", "verified", 1, "second", "pdf_text"),
        _row("pdf", "verified", 0, "first", "pdf_text"),
    ]
    selected = select_source([html, legacy, *pdf_pages])
    assert selected is not None
    _, kind, source = selected
    assert kind == "pdf"
    assert source.text == "first\n\nsecond"  # pages in physical order
    assert source.page_reference_status is PageReferenceStatus.VERIFIED

    selected = select_source([html, legacy])
    assert selected is not None and selected[1] == "legacy"
    assert selected[2].page_reference_status is PageReferenceStatus.UNKNOWN
    selected = select_source([html])
    assert selected is not None and selected[1] == "html"
    assert select_source([]) is None


def test_unverified_pdf_pages_are_pending() -> None:
    pages = [_row("pdf", "unverified", 0, "text", "pdf_text")]
    selected = select_source(pages)
    assert selected is not None
    assert selected[2].page_reference_status is PageReferenceStatus.PENDING


def test_real_tokenizer_when_cached() -> None:
    settings = Settings()
    try:
        tokenizer = HfTokenizer(settings.tokenizer_model_id, settings.tokenizer_revision)
    except TokenizerUnavailable:
        pytest.skip("bge tokenizer not in the local HF cache (run fetch-tokenizer)")
    assert tokenizer.count(["", "the court", "appellant"]) == [0, 2, 2]  # app ##ellant
    text = "Mensah v. Owusu [2019] GHASC 12"
    assert all(text[s:e] for s, e in tokenizer.offsets(text))


def test_party_words() -> None:
    assert party_words("Mensah & Anor v. Owusu and Others") == [{"MENSAH"}, {"OWUSU"}]
    assert party_words("Republic vrs High Court, Accra ex parte Asiedu") == [
        {"REPUBLIC"},
        {"HIGH", "COURT", "ACCRA", "ASIEDU"},
    ]


@pytest.mark.parametrize(
    ("query", "citation", "expected"),
    [
        ("Juma v Tanzania", "Juma and Another v United Republic of Tanzania", True),
        ("Juma v Tanzania", "Nganyi and Others v Tanzania (Judgment - Reparations)", False),
        ("Showumi Williams v Sister Sheila", "Alhaji Showumi Williams Vrs Sister Sheila A", True),
        ("Mensah v Owusu", "Mensah Vrs Boateng", False),
    ],
)
def test_names_every_party(query: str, citation: str, expected: bool) -> None:
    assert names_every_party(query, citation) is expected
