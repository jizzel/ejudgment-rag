import uuid
from collections import Counter
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from ejudgment.api.main import create_app
from ejudgment.config import Settings
from ejudgment.domain.schemas import ATTRIBUTION, SearchFilters, SearchRequest, SearchResponse
from ejudgment.ingestion.chunk_service import run_chunking
from ejudgment.ingestion.hashing import sha256_text
from ejudgment.ingestion.normalize import normalize_citation
from ejudgment.ingestion.service import run_legacy_import
from ejudgment.ingestion.tokenizer import WhitespaceTokenizer
from ejudgment.retrieval.service import search
from tests.fixtures import legacy_fixture as fx

pytestmark = pytest.mark.integration
TOK = WhitespaceTokenizer()


@pytest.fixture
def search_engine(
    legacy_fixture: fx.LegacyFixture, settings: Settings, migrated_engine: Engine
) -> Engine:
    run_legacy_import(
        legacy_fixture.db_path, legacy_fixture.base_dir, settings, engine=migrated_engine
    )
    run_chunking(migrated_engine, TOK, settings)
    return migrated_engine


def _search(engine: Engine, settings: Settings, query: str, **filters: Any) -> SearchResponse:
    with engine.connect() as conn:
        return search(
            conn, SearchRequest(query=query, filters=SearchFilters(**filters), top_k=5), settings
        )


def _number(index: int) -> int:
    return index + 1


# --- chunking ------------------------------------------------------------------------------


def _chunk_snapshot(engine: Engine) -> list[tuple[Any, ...]]:
    with engine.connect() as conn:
        return [
            tuple(row)
            for row in conn.execute(
                text(
                    "SELECT id, judgment_id, content_hash, chunker_version FROM chunks ORDER BY id"
                )
            )
        ]


def test_chunking_is_idempotent(search_engine: Engine, settings: Settings) -> None:
    snapshot = _chunk_snapshot(search_engine)
    assert snapshot
    report = run_chunking(search_engine, TOK, settings)
    assert report.chunked == 0
    assert report.skipped_unchanged == report.judgments_seen - report.no_text
    assert _chunk_snapshot(search_engine) == snapshot


def test_budget_change_rechunks_everything(search_engine: Engine, settings: Settings) -> None:
    smaller = settings.model_copy(update={"chunk_target_tokens": 20, "chunk_max_tokens": 30})
    report = run_chunking(search_engine, TOK, smaller)
    assert report.skipped_unchanged == 0
    assert report.max_tokens_seen <= 30
    with search_engine.connect() as conn:
        versions = conn.execute(text("SELECT DISTINCT chunker_version FROM chunks")).scalars()
        assert list(versions) == [f"para-v2-t20-m30-{TOK.name}"]


def test_only_eligible_judgments_are_chunked(search_engine: Engine) -> None:
    with search_engine.connect() as conn:
        ineligible = conn.execute(
            text(
                "SELECT count(*) FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
                "WHERE j.eligibility_status <> 'eligible'"
            )
        ).scalar_one()
        spans_ok = conn.execute(
            text("SELECT bool_and(char_end > char_start AND token_count > 0) FROM chunks")
        ).scalar_one()
    assert ineligible == 0
    assert spans_ok


def test_page_references_follow_the_source(search_engine: Engine) -> None:
    with search_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.page_reference_status, c.page_start, c.page_end, s.kind "
                "FROM chunks c JOIN document_sources s ON s.id = c.source_id"
            )
        ).all()
    pdf = [row for row in rows if row.kind == "pdf"]
    other = [row for row in rows if row.kind != "pdf"]
    # The readable PDF (verified by its citation) keeps real page numbers.
    assert pdf and all(r.page_reference_status == "verified" for r in pdf)
    assert all(r.page_start == 0 and r.page_end is not None for r in pdf)
    assert all(r.page_reference_status == "unknown" and r.page_start is None for r in other)


# --- search --------------------------------------------------------------------------------


def test_lexical_search_finds_unique_words(search_engine: Engine, settings: Settings) -> None:
    response = _search(search_engine, settings, "marker37x3")
    assert response.cases[0].judgment.citation.startswith("Party37 Vrs Other37")
    assert response.cases[0].match_type == "lexical"
    passage = response.passages[0]
    assert "marker37x3" in passage.excerpt
    assert passage.page_reference_status == "unknown" and passage.page_start is None
    assert passage.judgment.source_url == (
        "https://ghalii.org/akn/gh/judgment/ghasc/2020/38/eng@2020-02-07"
    )
    assert response.attribution == ATTRIBUTION


def test_stemmed_words_match(search_engine: Engine, settings: Settings) -> None:
    # Fixture text says "Judgment delivered"; the English config stems "delivering".
    response = _search(search_engine, settings, "delivering synthetic matter")
    assert response.cases


@pytest.mark.parametrize("query", ["[2020] GHASC 38", "what did 2020 GHASC 38 say"])
def test_citation_query_ranks_exact_match_first(
    search_engine: Engine, settings: Settings, query: str
) -> None:
    response = _search(search_engine, settings, query)
    assert response.query_info.detected_citation == "[2020] GHASC 38"
    first = response.cases[0]
    assert first.match_type == "citation"
    assert first.judgment.citation.startswith("Party37 Vrs Other37")
    # "GHASC 38" must not also match "GHASC 380"-style citations as exact hits.
    assert sum(case.match_type == "citation" for case in response.cases) == 1


def test_case_name_query(search_engine: Engine, settings: Settings) -> None:
    response = _search(search_engine, settings, "Party40 Vrs Other40")
    assert response.query_info.looks_like_case_name
    assert response.cases[0].match_type == "case_name"
    assert response.cases[0].judgment.title == "Party40 Vrs Other40"


def test_filters_are_strict(search_engine: Engine, settings: Settings) -> None:
    assert _search(search_engine, settings, "marker37x3", court="ghasc").cases
    assert not _search(search_engine, settings, "marker37x3", court="ghahc").cases
    assert not _search(search_engine, settings, "marker37x3", year_from=2021).cases
    assert _search(search_engine, settings, "marker37x3", year_from=2020, year_to=2020).cases
    assert _search(search_engine, settings, "marker37x3", judge="judge37a").cases
    assert not _search(search_engine, settings, "marker37x3", judge="Nobody").cases
    # Exact citation hits obey the filters too.
    assert not _search(search_engine, settings, "[2020] GHASC 38", court="ghahc").cases
    au = _search(search_engine, settings, f"marker{fx.ROW_AU}x3", jurisdiction="aa-au")
    assert au.cases[0].judgment.court_code == "afchpr"
    response = _search(search_engine, settings, "marker37x3", court="ghahc")
    assert response.query_info.filters_applied == {"court": "ghahc"}


def test_republished_judgment_is_one_case(search_engine: Engine, settings: Settings) -> None:
    response = _search(search_engine, settings, f"marker{fx.ROW_TEXT_TWIN_A}x3")
    twins = [
        case
        for case in response.cases
        if case.judgment.citation.startswith(("Party18 ", "Party19 "))
    ]
    assert len(twins) == 1
    (case,) = twins
    assert len(case.also_published_as) == 1
    uris = {case.judgment.canonical_uri, case.also_published_as[0].canonical_uri}
    assert uris == {
        f"/akn/gh/judgment/ghasc/2020/{_number(fx.ROW_TEXT_TWIN_A)}/eng@2020-01-19",
        f"/akn/gh/judgment/ghasc/2020/{_number(fx.ROW_TEXT_TWIN_B)}/eng@2020-01-20",
    }
    excerpts = [p.excerpt for p in response.passages]
    assert len(excerpts) == len(set(excerpts))  # identical passages are not repeated


def test_quarantined_judgments_are_never_returned(
    search_engine: Engine, settings: Settings
) -> None:
    other = _number(fx.ROW_SAME_PARTIES_OTHER)  # quarantined: its only file is someone else's
    response = _search(search_engine, settings, f"[2020] GHASC {other}")
    assert all(case.match_type != "citation" for case in response.cases)
    returned = {case.judgment.canonical_uri for case in response.cases} | {
        ref.canonical_uri for case in response.cases for ref in case.also_published_as
    }
    assert not any(f"/ghasc/2020/{other}/" in uri for uri in returned)


def test_verified_pdf_passages_carry_pages(search_engine: Engine, settings: Settings) -> None:
    response = _search(search_engine, settings, f"marker{fx.ROW_READABLE_PDF_NO_TEXT}x3")
    passage = response.passages[0]
    assert passage.page_reference_status == "verified"
    assert passage.page_start is not None and passage.page_end is not None


def test_nonsense_query_returns_nothing(search_engine: Engine, settings: Settings) -> None:
    response = _search(search_engine, settings, "zzqxv flurbington")
    assert response.cases == [] and response.passages == []


# --- API -----------------------------------------------------------------------------------


@pytest.fixture
def client(search_engine: Engine, settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, search_engine)) as test_client:
        yield test_client


def test_healthz(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_search_endpoint(client: TestClient, search_engine: Engine) -> None:
    response = client.post(
        "/v1/search", json={"query": "marker37x3", "filters": {"court": "ghasc"}, "top_k": 3}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["cases"][0]["judgment"]["citation"].startswith("Party37 Vrs Other37")
    assert body["attribution"] == ATTRIBUTION
    assert "not legal advice" in body["notice"]
    assert body["passages"][0]["page_start"] is None

    with search_engine.connect() as conn:
        audit = conn.execute(text("SELECT query_hash, query_text, filters FROM query_audit")).one()
    assert len(audit.query_hash) == 64
    assert audit.query_text is None  # raw queries are not stored by default
    assert audit.filters == {"court": "ghasc"}


def test_raw_query_audit_is_opt_in(search_engine: Engine, settings: Settings) -> None:
    opted_in = settings.model_copy(update={"audit_store_raw_queries": True})
    with TestClient(create_app(opted_in, search_engine)) as client:
        assert client.post("/v1/search", json={"query": "marker37x3"}).status_code == 200
    with search_engine.connect() as conn:
        stored = conn.execute(text("SELECT query_text FROM query_audit")).scalar_one()
    assert stored == "marker37x3"


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"query": ""}, "query_empty"),
        ({"query": "   "}, "query_empty"),
        ({"query": "x", "filters": {"court": "GHASC!"}}, "invalid_filter"),
        ({"query": "x", "filters": {"colour": "red"}}, "invalid_filter"),
        ({"query": "x", "filters": {"year_from": 2021, "year_to": 2020}}, "invalid_filter"),
        ({"query": "x", "top_k": 0}, "invalid_request"),
    ],
)
def test_search_errors_have_stable_codes(
    client: TestClient, payload: dict[str, Any], code: str
) -> None:
    response = client.post("/v1/search", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_judgment_endpoint(client: TestClient) -> None:
    hit = client.post("/v1/search", json={"query": "marker37x3"}).json()
    judgment_id = hit["cases"][0]["judgment"]["judgment_id"]
    response = client.get(f"/v1/judgments/{judgment_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["judgment"]["judgment_id"] == judgment_id
    assert body["judges"] == ["Judge37A, JSC", "Judge37B, JSC", "Judge37C, JSC"]
    assert body["chunk_count"] >= 1
    assert {source["kind"] for source in body["sources"]} == {"legacy", "pdf"}
    assert body["attribution"] == ATTRIBUTION


def test_judgment_not_found(client: TestClient) -> None:
    response = client.get("/v1/judgments/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "judgment_not_found"
    malformed = client.get("/v1/judgments/not-a-uuid")
    assert malformed.status_code == 422
    assert malformed.json()["error"]["code"] == "invalid_request"


# --- result diversity --------------------------------------------------------------------


def _add_chunks(engine: Engine, citation_prefix: str, contents: list[str]) -> None:
    """Append extra chunks to an existing judgment (same source and source text hash)."""
    with engine.begin() as conn:
        base = conn.execute(
            text(
                "SELECT c.judgment_id, c.source_id, c.source_text_hash, "
                "(SELECT max(ordinal) FROM chunks x WHERE x.judgment_id = c.judgment_id) AS last "
                "FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
                "WHERE j.citation LIKE :p AND c.ordinal = 0"
            ),
            {"p": f"{citation_prefix} %"},
        ).one()
        conn.execute(
            text(
                "INSERT INTO chunks (id, judgment_id, source_id, ordinal, page_reference_status, "
                "paragraph_refs, char_start, char_end, content, content_hash, token_count, "
                "chunker_version, source_text_hash) VALUES (:id, :judgment_id, :source_id, "
                ":ordinal, 'unknown', '[]', 0, :end, :content, :hash, :tokens, 'test', :text_hash)"
            ),
            [
                {
                    "id": uuid.uuid4(),
                    "judgment_id": base.judgment_id,
                    "source_id": base.source_id,
                    "ordinal": base.last + 1 + offset,
                    "end": len(content),
                    "content": content,
                    "hash": sha256_text(content),
                    "tokens": len(content.split()),
                    "text_hash": base.source_text_hash,
                }
                for offset, content in enumerate(contents)
            ],
        )


def test_identical_passage_in_different_judgments_gives_each_a_case(
    search_engine: Engine, settings: Settings
) -> None:
    quoted = "Section 10 of the Limitations Act sharedprovisionxyz extinguishes the title."
    _add_chunks(search_engine, "Party30 Vrs Other30", [quoted])
    _add_chunks(search_engine, "Party31 Vrs Other31", [quoted])
    response = _search(search_engine, settings, "sharedprovisionxyz")
    titles = {case.judgment.title for case in response.cases}
    assert titles == {"Party30 Vrs Other30", "Party31 Vrs Other31"}
    assert all(not case.also_published_as for case in response.cases)


def test_one_long_judgment_cannot_crowd_out_other_cases(
    search_engine: Engine, settings: Settings
) -> None:
    # One judgment with 120 strongly matching chunks, twelve others with one weak match each.
    _add_chunks(
        search_engine,
        "Party40 Vrs Other40",
        [f"monopolyterm monopolyterm monopolyterm paragraph {n}" for n in range(120)],
    )
    for index in range(50, 62):
        _add_chunks(search_engine, f"Party{index} Vrs Other{index}", [f"a monopolyterm {index}"])
    with search_engine.connect() as conn:
        response = search(conn, SearchRequest(query="monopolyterm", top_k=10), settings)
    assert len(response.cases) == 10
    assert response.cases[0].judgment.title == "Party40 Vrs Other40"
    assert len(response.cases[0].passages) == settings.passages_per_case
    per_case = Counter(p.judgment.judgment_id for p in response.passages)
    assert max(per_case.values()) <= settings.passages_per_case


def _rename(engine: Engine, citation_prefix: str, citation: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE judgments SET citation = :c, title = :t, citation_normalized = :n "
                "WHERE citation LIKE :p"
            ),
            {
                "c": citation,
                "t": citation.split(" [")[0],
                "n": normalize_citation(citation),
                "p": f"{citation_prefix} %",
            },
        )


def test_case_name_not_lost_behind_similar_non_matching_names(
    search_engine: Engine, settings: Settings
) -> None:
    # Six names that fail the party check ("REPUBLICAN" is not "REPUBLIC") outrank the real
    # case on trigram similarity alone (word_similarity ~0.94 vs ~0.81).
    for index in range(60, 66):
        _rename(
            search_engine,
            f"Party{index} Vrs Other{index}",
            f"Acquah V Republican [2020] GHASC {index + 1} (x)",
        )
    _rename(search_engine, "Party66 Vrs Other66", "Acquah Vrs Republic [2020] GHASC 67 (x)")
    with search_engine.connect() as conn:
        response = search(conn, SearchRequest(query="Acquah v Republic", top_k=1), settings)
    assert response.cases[0].match_type == "case_name"
    assert response.cases[0].judgment.citation == "Acquah Vrs Republic [2020] GHASC 67 (x)"


def test_deep_offsets_still_return_cases(search_engine: Engine, settings: Settings) -> None:
    # Every eligible case gets many strongly matching chunks, so each fills its per-case quota.
    per_case = settings.model_copy(update={"passages_per_case": 10})
    with search_engine.connect() as conn:
        prefixes = (
            conn.execute(
                text(
                    "SELECT DISTINCT split_part(j.title, ' ', 1) || ' ' || "
                    "split_part(j.title, ' ', 2) || ' ' || split_part(j.title, ' ', 3) "
                    "FROM judgments j JOIN chunks c ON c.judgment_id = j.id "
                    "WHERE j.title LIKE 'Party% Vrs Other%'"
                )
            )
            .scalars()
            .all()
        )
    # A distinct score per case (more repetitions rank higher) keeps each case's chunks
    # together in the ranking, as in real data; tied scores would interleave the cases.
    for rank, prefix in enumerate(sorted(prefixes)):
        term = " ".join(["deepterm"] * (rank + 1))
        _add_chunks(search_engine, prefix, [f"{term} clause {n}" for n in range(12)])
    with search_engine.connect() as conn:
        # Re-published judgments share one source text and count as one case.
        total = conn.execute(
            text(
                "SELECT count(DISTINCT source_text_hash) FROM chunks WHERE content LIKE 'deepterm%'"
            )
        ).scalar_one()
    assert total > 80

    seen: list[str] = []
    with search_engine.connect() as conn:
        for offset in range(0, total, 10):
            page = search(conn, SearchRequest(query="deepterm", top_k=10, offset=offset), per_case)
            assert len(page.cases) == min(10, total - offset), offset
            seen += [case.judgment.canonical_uri for case in page.cases]
    assert len(seen) == len(set(seen)) == total  # pages neither overlap nor skip cases


def test_pages_are_stable_when_scores_tie(search_engine: Engine, settings: Settings) -> None:
    # Identical scores everywhere: page boundaries must still be consistent across requests.
    with search_engine.connect() as conn:
        prefixes = (
            conn.execute(
                text(
                    "SELECT DISTINCT split_part(j.title, ' ', 1) || ' ' || "
                    "split_part(j.title, ' ', 2) || ' ' || split_part(j.title, ' ', 3) "
                    "FROM judgments j JOIN chunks c ON c.judgment_id = j.id "
                    "WHERE j.title LIKE 'Party% Vrs Other%'"
                )
            )
            .scalars()
            .all()
        )
    for prefix in prefixes:
        _add_chunks(search_engine, prefix, [f"tieterm clause {n}" for n in range(4)])
    with search_engine.connect() as conn:
        total = conn.execute(
            text(
                "SELECT count(DISTINCT source_text_hash) FROM chunks WHERE content LIKE 'tieterm%'"
            )
        ).scalar_one()
        seen: list[str] = []
        for offset in range(0, total, 10):
            page = search(conn, SearchRequest(query="tieterm", top_k=10, offset=offset), settings)
            seen += [case.judgment.canonical_uri for case in page.cases]
    assert len(seen) == len(set(seen)) == total
