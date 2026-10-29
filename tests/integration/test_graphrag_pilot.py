"""Phase 3 pilot end to end on the synthetic fixture: gold finder and runner (fake models)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from ejudgment.config import Settings
from ejudgment.embeddings.fake import FakeEmbeddingProvider, FakeReranker
from ejudgment.evaluation.retrieval import GoldPassage
from ejudgment.ingestion.embed_service import run_embedding
from ejudgment.ingestion.tokenizer import WhitespaceTokenizer
from ejudgment.retrieval.coverage import clear_cache
from experiments.graphrag.coverage.profile_mentions import profile
from experiments.graphrag.graph.build import build_graph
from experiments.graphrag.graph.policy import PHASE2_V1
from experiments.graphrag.manifest import research_manifest
from experiments.graphrag.pilot.gold_finder import (
    _anchor,
    import_gold,
    import_lineage,
    incoming_rows,
)
from experiments.graphrag.pilot.questions import PilotQuestion, lock_gold, lock_intents
from experiments.graphrag.pilot.run import GraphView, RunConfig, run_question
from experiments.graphrag.resolution.index import load_index
from tests.integration.test_search import search_engine  # noqa: F401

pytestmark = pytest.mark.integration
EMBEDDER = FakeEmbeddingProvider()


def test_pilot_finds_gold_without_the_graph_and_runs_every_system(
    search_engine: Engine,  # noqa: F811
    settings: Settings,
    tmp_path: Path,
) -> None:
    with search_engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT j.canonical_uri AS uri, j.title, j.neutral_citation, "
                "min(c.id::text) AS chunk "
                "FROM judgments j JOIN chunks c ON c.judgment_id = j.id "
                "WHERE j.eligibility_status = 'eligible' AND j.neutral_citation IS NOT NULL "
                "AND j.judgment_date IS NOT NULL AND j.title ~* ' v(s|rs)?\\.? ' "
                "GROUP BY j.id ORDER BY j.judgment_date, j.id"
            )
        ).all()
        cited, citing = rows[0], rows[-1]
        conn.execute(
            text("UPDATE chunks SET content = content || :p WHERE id::text = :id"),
            {
                "p": (
                    f" The tenancy rule was applied as held in {cited.title} "
                    f"{cited.neutral_citation}."
                ),
                "id": citing.chunk,
            },
        )
    run_embedding(search_engine, EMBEDDER, WhitespaceTokenizer())
    clear_cache()

    with search_engine.connect() as conn, conn.begin():
        out = tmp_path / "mentions.jsonl"
        profile(conn, out)
        index = load_index(conn)
        graph = build_graph(
            (json.loads(line) for line in out.read_text().splitlines()), index, PHASE2_V1
        )
        # The gold finder works from text alone: no profile, resolver or graph input.
        anchor = _anchor(conn, cited.uri)
        found = incoming_rows(conn, anchor, [])
        assert any(r["chunk_id"] == citing.chunk for r in found)

        question = PilotQuestion(
            id="inc-1",
            question_class="incoming",
            query=cited.title,  # a case-name search for the anchor
            anchor_uris=[cited.uri],
            sampling="fixture",
        )
        assert lock_intents([question], datetime.now(UTC)) == []
        marked = [
            {**r, "row": str(i), "relevant": "y", "on_issue": "y", "cited_uri": "", "gold_text": ""}
            for i, r in enumerate(found, start=1)
            if r["chunk_id"] == citing.chunk
        ]
        absent = [
            {**marked[0], "row": "9", "cited_uri": "/akn/gh/judgment/ghasc/1901/1/eng@1901-01-01"}
        ]
        strict = question.model_copy(deep=True)
        assert import_gold(conn, strict, absent) == [
            "row 9: /akn/gh/judgment/ghasc/1901/1/eng@1901-01-01 is not an eligible judgment"
        ]
        corpus_only = question.model_copy(deep=True)
        excluded: list[dict[str, str]] = []
        assert import_gold(conn, corpus_only, absent, excluded) == []
        assert corpus_only.gold_case_uris == [] and [r["row"] for r in excluded] == ["9"]
        # A quote cut short (e.g. at "v.") is reported with its row, not a crash.
        content = conn.execute(
            text("SELECT content FROM chunks WHERE id::text = :id"), {"id": citing.chunk}
        ).scalar_one()
        cut = " ".join(content.split())[:12]
        short = [{**marked[0], "gold_text": cut}]
        assert import_gold(conn, question.model_copy(deep=True), short) == [
            f"row {marked[0]['row']}: gold_text {cut!r} is shorter than 20 characters "
            "(too short to identify a passage)"
        ]
        assert import_gold(conn, question, marked) == []
        assert lock_gold([question], datetime.now(UTC)) == []

        # Lineage: a chain needs an accepted first hop and must not revisit a case.
        lineage = PilotQuestion(
            id="lin-1",
            question_class="lineage",
            direction="incoming",
            query="q",
            anchor_uris=[cited.uri],
            sampling="fixture",
        )
        other = rows[1].uri
        second = [{**marked[0], "judgment_uri": other, "first_hop_uri": citing.uri, "row": "1"}]
        assert import_lineage(conn, lineage, [], marked, second) == [
            f"row 1: first hop {citing.uri} was not accepted",
            "no complete chain was marked",
        ]
        looped = [{**second[0], "judgment_uri": citing.uri}]
        assert import_lineage(conn, lineage, [citing.uri], marked, looped)[0].endswith(
            f"a chain does not revisit {citing.uri}"
        )
        assert import_lineage(conn, lineage, [citing.uri], marked, second) == []
        assert lineage.gold_paths == [[cited.uri, citing.uri, other]]
        assert lineage.gold_case_uris == sorted({citing.uri, other})
        # A passage of an accepted first hop that no chain continues is not gold.
        dead_end = rows[2].uri
        chunk_id, content = conn.execute(
            text(
                "SELECT c.id::text, c.content FROM chunks c JOIN judgments j "
                "ON j.id = c.judgment_id WHERE j.canonical_uri = :uri ORDER BY c.ordinal LIMIT 1"
            ),
            {"uri": dead_end},
        ).one()
        quote = " ".join(content.split())[:40]
        first = [
            *marked,
            {
                **marked[0],
                "row": "5",
                "judgment_uri": dead_end,
                "chunk_id": chunk_id,
                "gold_text": quote,
            },
        ]
        assert import_lineage(conn, lineage, [citing.uri, dead_end], first, second) == []
        assert lineage.gold_paths == [[cited.uri, citing.uri, other]]
        assert lineage.gold_passages == []

        view = GraphView()
        for (source, target), occurrences in graph.edges.items():
            view.outgoing[source].add(target)
            view.incoming[target].add(source)
            view.occurrences[(source, target)] = [o["chunk_id"] for o in occurrences]
        for case, node in graph.nodes.items():
            for judgment in node["judgments"]:
                view.group_of_uri[judgment["uri"]] = case
        records = run_question(
            conn, question, view, settings, EMBEDDER, FakeReranker(), RunConfig(seed_k=5)
        )
        # Outgoing: "what did the citing case rely on". The gold passage is the anchor's own
        # citing passage, so it must be judged in the anchor, not in the case it ranks.
        outgoing = PilotQuestion(
            id="out-1",
            question_class="outgoing",
            query=citing.title,
            anchor_uris=[citing.uri],
            sampling="fixture",
            gold_case_uris=[cited.uri],
            gold_passages=[
                GoldPassage(
                    canonical_uri=citing.uri, text="The tenancy rule was applied as held in"
                )
            ],
        )
        out_records = run_question(
            conn, outgoing, view, settings, EMBEDDER, FakeReranker(), RunConfig(seed_k=5)
        )
        # The run's manifest fingerprints the vectors that served it, not only the text.
        manifest = research_manifest(conn, kind="graphrag_pilot", embedder=EMBEDDER)
        assert manifest["corpus_fingerprint"]["embeddings"] > 0
        assert manifest["corpus_fingerprint"]["embeddings_digest"]

    by_system = {r["system"]: r for r in records}
    assert set(by_system) == {"B0", "B0R", "G1-oracle", "G1-both", "G2-oracle"}
    citing_case = view.group_of_uri[citing.uri]
    oracle = by_system["G1-oracle"]
    assert view.group_of_uri[cited.uri] in oracle["seeds"]  # the named case is a seed
    assert citing_case in [h["case"] for h in oracle["hops"]]  # reached: it cites the anchor
    assert all(h["direction"] == "incoming" for h in oracle["hops"])
    assert citing_case in [c["case"] for c in oracle["ranked"]]
    assert oracle["metrics"]["hit@20"] is True
    assert oracle["metrics"]["seed_recall"] == 1.0
    assert by_system["B0"]["hops"] == [] and by_system["B0R"]["hops"] == []
    assert all(r["latency_ms"] > 0 for r in records)

    out = {r["system"]: r for r in out_records}["G1-oracle"]
    cited_case = view.group_of_uri[cited.uri]
    reached = next(c for c in out["ranked"] if c["case"] == cited_case)
    edge_passages = [p for p in reached["passages"] if p["role"] == "citing_outgoing"]
    assert edge_passages and all(p["source_case"] == citing_case for p in edge_passages)
    assert out["metrics"]["passage_recall@20"] == 1.0
