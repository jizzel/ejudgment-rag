from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from ejudgment.api.main import create_app
from ejudgment.config import Settings
from ejudgment.domain.schemas import SearchFilters, SearchRequest, SearchResponse
from ejudgment.embeddings.fake import FakeEmbeddingProvider, FakeReranker
from ejudgment.evaluation.retrieval import evaluate, load_gold, run_config, store_run
from ejudgment.ingestion.embed_service import run_embedding
from ejudgment.ingestion.tokenizer import WhitespaceTokenizer
from ejudgment.retrieval.service import search
from tests.integration.test_search import search_engine  # noqa: F401

pytestmark = pytest.mark.integration
TOK = WhitespaceTokenizer()
# "landlord" never occurs in the fixture text; the fake embedder maps it onto "tenancy",
# which every fixture judgment contains. Only the dense channel can make that connection.
# "pupilcase" maps onto one judgment's unique marker word, so only dense search finds it.
EMBEDDER = FakeEmbeddingProvider(
    synonyms={"landlord": "tenancy", "lessor": "lease", "pupilcase": "marker40x3"}
)
RERANKER = FakeReranker()


@pytest.fixture
def embedded_engine(search_engine: Engine) -> Engine:  # noqa: F811
    run_embedding(search_engine, EMBEDDER, TOK)
    return search_engine


def _search(
    engine: Engine, settings: Settings, query: str, *, rerank: bool = False, **kwargs: Any
) -> SearchResponse:
    filters = kwargs.pop("filters", {})
    request = SearchRequest(query=query, filters=SearchFilters(**filters), rerank=rerank, **kwargs)
    with engine.connect() as conn:
        return search(conn, request, settings, embedder=EMBEDDER, reranker=RERANKER)


def _embedding_count(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM chunk_embeddings")).scalar_one())


# --- embedding job -------------------------------------------------------------------------


def test_embedding_twice_is_a_no_op(embedded_engine: Engine) -> None:
    with embedded_engine.connect() as conn:
        chunks = conn.execute(text("SELECT count(*) FROM chunks")).scalar_one()
    assert _embedding_count(embedded_engine) == chunks
    again = run_embedding(embedded_engine, EMBEDDER, TOK)
    assert (again.embedded_new, again.re_embedded) == (0, 0)
    assert again.skipped_unchanged == chunks


def test_metadata_change_re_embeds_only_that_judgment(embedded_engine: Engine) -> None:
    with embedded_engine.begin() as conn:
        conn.execute(
            text("UPDATE judgments SET title = 'Renamed v Party' WHERE citation LIKE 'Party37 %'")
        )
        affected = conn.execute(
            text(
                "SELECT count(*) FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
                "WHERE j.citation LIKE 'Party37 %'"
            )
        ).scalar_one()
    report = run_embedding(embedded_engine, EMBEDDER, TOK)
    assert report.re_embedded == affected > 0
    assert report.embedded_new == 0


def test_model_is_registered(embedded_engine: Engine) -> None:
    with embedded_engine.connect() as conn:
        row = conn.execute(text("SELECT model_id, kind, dimension FROM model_registry")).one()
    assert tuple(row) == ("fake/hashed-bow", "embedding", 384)


# --- dense and hybrid retrieval -----------------------------------------------------------


def test_dense_finds_what_lexical_cannot(embedded_engine: Engine, settings: Settings) -> None:
    lexical = _search(embedded_engine, settings, "landlord", mode="lexical")
    dense = _search(embedded_engine, settings, "landlord", mode="dense")
    hybrid = _search(embedded_engine, settings, "landlord", mode="hybrid")
    assert lexical.cases == []
    assert dense.cases and all(case.match_type == "dense" for case in dense.cases)
    assert dense.passages[0].dense_score is not None
    assert hybrid.cases and hybrid.query_info.mode_used == "hybrid"
    assert not hybrid.query_info.degraded


def test_hybrid_marks_passages_found_by_both_channels(
    embedded_engine: Engine, settings: Settings
) -> None:
    response = _search(embedded_engine, settings, "marker37x3 tenancy", mode="hybrid")
    top = response.passages[0]
    assert top.judgment.title == "Party37 Vrs Other37"
    assert top.match_type == "hybrid"
    assert None not in (top.lexical_score, top.dense_score, top.rrf_score)


def test_dense_respects_strict_filters(embedded_engine: Engine, settings: Settings) -> None:
    only_regional = _search(
        embedded_engine, settings, "landlord", mode="dense", filters={"court": "ghahc"}
    )
    assert {case.judgment.court_code for case in only_regional.cases} == {"ghahc"}
    assert not _search(
        embedded_engine, settings, "landlord", mode="dense", filters={"year_from": 2021}
    ).cases


def test_rerank_orders_the_head_by_reranker_score(
    embedded_engine: Engine, settings: Settings
) -> None:
    response = _search(embedded_engine, settings, "tenancy appellant", rerank=True, top_k=10)
    assert response.query_info.reranked
    scores = [p.rerank_score for p in response.passages]
    assert all(score is not None for score in scores)
    assert scores == sorted(scores, reverse=True)  # type: ignore[type-var]


def test_hybrid_pages_are_stable(embedded_engine: Engine, settings: Settings) -> None:
    seen: list[str] = []
    for offset in range(0, 100, 10):
        page = _search(embedded_engine, settings, "tenancy", rerank=True, offset=offset)
        seen += [case.judgment.canonical_uri for case in page.cases]
    with embedded_engine.connect() as conn:
        total = conn.execute(
            text("SELECT count(DISTINCT source_text_hash) FROM chunks")
        ).scalar_one()
    assert len(seen) == len(set(seen)) == total


# --- API ----------------------------------------------------------------------------------


@pytest.fixture
def client(embedded_engine: Engine, settings: Settings) -> Iterator[TestClient]:
    app = create_app(settings, embedded_engine, embedder=EMBEDDER, reranker=RERANKER)
    with TestClient(app) as test_client:
        yield test_client


def test_api_hybrid_search(client: TestClient) -> None:
    body = client.post("/v1/search", json={"query": "landlord", "top_k": 3}).json()
    assert body["query_info"]["mode_used"] == "hybrid"
    assert body["query_info"]["reranked"] is True
    assert body["cases"]


def test_api_depth_limit(client: TestClient) -> None:
    response = client.post("/v1/search", json={"query": "tenancy", "offset": 145, "top_k": 10})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_missing_models_degrade_visibly(embedded_engine: Engine, settings: Settings) -> None:
    app = create_app(settings, embedded_engine, load_models=False)
    with TestClient(app) as client:
        body = client.post("/v1/search", json={"query": "tenancy"}).json()
    info = body["query_info"]
    assert (info["mode_requested"], info["mode_used"]) == ("hybrid", "lexical")
    assert info["degraded"] is True and info["reranked"] is False
    assert "embedding model unavailable" in info["degraded_reason"]
    assert "reranker unavailable" in info["degraded_reason"]
    assert body["cases"]


# --- evaluation ---------------------------------------------------------------------------


def test_evaluation_run_is_stored_with_metrics(
    embedded_engine: Engine, settings: Settings, tmp_path: Path
) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        "\n".join(
            [
                '{"id": "q1", "category": "issue", "question": "marker37x3", '
                '"gold_canonical_uris": ["/akn/gh/judgment/ghasc/2020/38/eng@2020-02-07"]}',
                '{"id": "q2", "category": "issue", "question": "pupilcase", '
                '"gold_canonical_uris": ["/akn/gh/judgment/ghasc/2020/41/eng@2020-02-10"]}',
                '{"id": "q3", "category": "out_of_corpus", "question": "zzqxv flurbington", '
                '"expect_no_answer": true}',
            ]
        )
    )
    questions = load_gold(gold)
    metrics, per_question = evaluate(
        embedded_engine, settings, questions, embedder=EMBEDDER, reranker=RERANKER
    )
    config = run_config(embedded_engine, settings, gold, questions, EMBEDDER, RERANKER)
    run_id = store_run(embedded_engine, config, metrics, per_question)

    assert set(metrics) == {"lexical", "dense", "hybrid", "hybrid+rerank"}
    assert metrics["lexical"]["recall@20"] == 0.5  # "pupilcase" is invisible to lexical search
    assert metrics["lexical"]["mrr@10"] == 0.5
    assert metrics["dense"]["recall@20"] == 1.0
    assert metrics["hybrid"]["recall@20"] == 1.0
    assert config["provisional"] is True
    assert config["embedding_model"]["model_id"] == "fake/hashed-bow"
    unanswerable = {r["config"]: r for r in per_question if r["id"] == "q3"}
    assert unanswerable["lexical"]["returned_cases"] == 0
    # Dense retrieval always returns nearest neighbours; abstention must rely on scores and
    # the generation step (M3), so the run records what came back and how confidently.
    assert unanswerable["dense"]["returned_cases"] > 0
    assert unanswerable["hybrid+rerank"]["top_rerank_score"] is not None
    with embedded_engine.connect() as conn:
        stored = conn.execute(
            text("SELECT metrics, config FROM evaluation_runs WHERE id = :id"), {"id": run_id}
        ).one()
    assert stored.metrics["hybrid"]["answerable_questions"] == 2
    assert stored.config["gold_sha256"] == config["gold_sha256"]


def test_republished_copies_get_both_channels_credit(
    embedded_engine: Engine, settings: Settings
) -> None:
    # Rows 18 and 19 publish identical text. Shorten one copy's title so its embedding input
    # differs and the dense channel prefers that copy, while lexical keeps the first URI.
    with embedded_engine.begin() as conn:
        conn.execute(text("UPDATE judgments SET title = 'B' WHERE citation LIKE 'Party19 %'"))
    run_embedding(embedded_engine, EMBEDDER, TOK)

    query = "marker18x3"
    lexical = _search(embedded_engine, settings, query, mode="lexical", top_k=1)
    dense = _search(embedded_engine, settings, query, mode="dense", top_k=1)
    assert lexical.passages[0].chunk_id != dense.passages[0].chunk_id  # different copies

    hybrid = _search(embedded_engine, settings, query, mode="hybrid", top_k=5)
    shared = [p for p in hybrid.passages if "marker18x3" in p.excerpt]
    assert len(shared) == 1
    assert shared[0].match_type == "hybrid"
    assert shared[0].lexical_score is not None and shared[0].dense_score is not None
    assert shared[0].chunk_id == lexical.passages[0].chunk_id


def test_run_config_records_every_ranking_input(
    embedded_engine: Engine, settings: Settings, tmp_path: Path
) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        '{"id": "q1", "category": "issue", "question": "x", "gold_canonical_uris": ["/akn/x"]}'
    )
    questions = load_gold(gold)

    def config(current: Settings) -> dict[str, Any]:
        return run_config(embedded_engine, current, gold, questions, EMBEDDER, RERANKER)

    first = config(settings)
    assert first == config(settings)  # deterministic
    assert first["embedding_model"]["dimension"] == 384
    assert first["settings"]["dense_raw_neighbours"] == settings.dense_raw_neighbours
    corpus = first["corpus"]
    assert corpus["alembic_revision"] == "0003"
    assert corpus["pgvector_version"]
    assert "ix_chunk_embeddings_hnsw_bge_small_v15" in corpus["vector_indexes"]
    assert corpus["embeddings"] == corpus["chunks"] > 0

    for change in (
        {"dense_raw_neighbours": 300},
        {"search_max_depth": 100},
        {"embedding_query_instruction": "Query: "},
    ):
        assert config(settings.model_copy(update=change)) != first, change

    # Re-embedding after a metadata change alters the recorded corpus version.
    with embedded_engine.begin() as conn:
        conn.execute(text("UPDATE judgments SET title = 'Renamed' WHERE citation LIKE 'Party37 %'"))
    run_embedding(embedded_engine, EMBEDDER, TOK)
    after = config(settings)["corpus"]
    assert after["embeddings_digest"] != corpus["embeddings_digest"]
    assert after["chunks_digest"] == corpus["chunks_digest"]
