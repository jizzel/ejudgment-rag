"""GraphRAG Phase 1 profiler end to end on the synthetic fixture corpus (read-only)."""

import json
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import InternalError

from ejudgment.config import Settings
from ejudgment.ingestion.chunk_service import run_chunking
from ejudgment.ingestion.service import run_legacy_import
from ejudgment.ingestion.tokenizer import WhitespaceTokenizer
from experiments.graphrag.coverage.profile_mentions import profile
from experiments.graphrag.coverage.report import summarise
from tests.fixtures import legacy_fixture as fx

pytestmark = pytest.mark.integration


@pytest.fixture
def corpus(legacy_fixture: fx.LegacyFixture, settings: Settings, migrated_engine: Engine) -> Engine:
    run_legacy_import(
        legacy_fixture.db_path, legacy_fixture.base_dir, settings, engine=migrated_engine
    )
    run_chunking(migrated_engine, WhitespaceTokenizer(), settings)
    return migrated_engine


def test_profile_resolves_a_citation_between_two_fixture_judgments(
    corpus: Engine, tmp_path: Path
) -> None:
    with corpus.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT j.id::text AS id, j.title, j.neutral_citation, j.judgment_date, "
                "min(c.source_text_hash) AS grp "
                "FROM judgments j JOIN chunks c ON c.judgment_id = j.id "
                "WHERE j.eligibility_status = 'eligible' AND j.neutral_citation IS NOT NULL "
                "AND j.judgment_date IS NOT NULL AND j.title ~* ' v(s|rs)?\\.? ' "
                "GROUP BY j.id ORDER BY j.judgment_date, j.id"
            )
        ).all()
        cited = rows[0]
        citing = next(
            r
            for r in reversed(rows)
            if r.grp != cited.grp and r.judgment_date > cited.judgment_date
        )
        passage = (
            f" As held in {cited.title} {cited.neutral_citation}, and in [2008] UKHL 3,"
            " also [1999] 1 GLR 5."
        )
        chunk_id = conn.execute(
            text(
                "UPDATE chunks SET content = content || :passage WHERE id = ("
                "SELECT id FROM chunks WHERE judgment_id = :jid ORDER BY ordinal LIMIT 1) "
                "RETURNING id::text"
            ),
            {"passage": passage, "jid": citing.id},
        ).scalar_one()
        eligible_chunks = conn.execute(
            text(
                "SELECT count(*) FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
                "WHERE j.eligibility_status = 'eligible'"
            )
        ).scalar_one()

    out = tmp_path / "mentions.jsonl"
    with corpus.connect() as conn, conn.begin():
        meta = profile(conn, out)
        # The whole profile ran in a read-only transaction.
        assert conn.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
        with pytest.raises(InternalError, match="read-only transaction"):
            conn.execute(text("DELETE FROM chunks"))

    records = [json.loads(line) for line in out.read_text().splitlines()]
    mine = [r for r in records if r["chunk_id"] == chunk_id and r["status"] != "self_reference"]

    def cites(key: str) -> dict[str, object]:
        return next(r for r in mine if any(c["key"] == key for c in r["citations"]))

    edge = cites(cited.neutral_citation)
    assert (edge["status"], edge["target_group"], edge["name_agrees"]) == (
        "resolved_exact",
        cited.grp,
        True,
    )
    assert cited.id in edge["target_ids"]
    assert cites("[1999] 1 GLR 5")["reason"] == "report_without_name"
    absent = cites("[2008] UKHL 3")
    assert (absent["status"], absent["foreign"]) == ("target_absent", True)
    # Offsets index the chunk and the source text.
    assert edge["text"].endswith(cited.neutral_citation)
    assert edge["source_start"] - edge["start"] == edge["source_end"] - edge["end"]

    assert meta["denominators"]["chunks"] == eligible_chunks
    assert meta["manifest"]["graph_build_id"]
    assert meta["manifest"]["corpus_fingerprint"]["chunks"] >= eligible_chunks
    summary = summarise(records, meta)
    assert summary["graph_shapes"]["tier_A"]["edges"] >= 1
    assert (edge["tier"], edge["ocr"]) == ("A", False)
    assert edge["text"] in edge["evidence"]
    assert summary["status_counts"]["resolved_exact"] >= 1


def test_graph_provenance_audit_traces_every_occurrence(corpus: Engine, tmp_path: Path) -> None:
    from experiments.graphrag.graph.build import build_graph, edge_rows
    from experiments.graphrag.graph.policy import PHASE2_V1
    from experiments.graphrag.graph.verify import verify_edges
    from experiments.graphrag.resolution.index import load_index

    with corpus.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT j.title, j.neutral_citation, min(c.id::text) AS chunk "
                "FROM judgments j JOIN chunks c ON c.judgment_id = j.id "
                "WHERE j.eligibility_status = 'eligible' AND j.neutral_citation IS NOT NULL "
                "AND j.judgment_date IS NOT NULL AND j.title ~* ' v(s|rs)?\\.? ' "
                "GROUP BY j.id, j.judgment_date ORDER BY j.judgment_date, j.id"
            )
        ).all()
        cited, citing = rows[0], rows[-1]
        conn.execute(
            text("UPDATE chunks SET content = content || :p WHERE id::text = :id"),
            {"p": f" As held in {cited.title} {cited.neutral_citation}.", "id": citing.chunk},
        )
    out = tmp_path / "mentions.jsonl"
    with corpus.connect() as conn, conn.begin():
        profile(conn, out)
        index = load_index(conn)
    records = [json.loads(line) for line in out.read_text().splitlines()]
    edges = edge_rows(build_graph(records, index, PHASE2_V1))
    assert edges, "the fixture should yield at least one admitted edge"

    with corpus.connect() as conn:
        report = verify_edges(conn, edges, PHASE2_V1)
        assert report["passed"], report
        tampered = json.loads(json.dumps(edges))
        tampered[0]["occurrences"][0]["text"] += "x"
        tampered[0]["occurrences"][0]["source_end"] += 1
        tampered[0]["target_case"] = "not-a-case"
        failures = verify_edges(conn, tampered, PHASE2_V1)["failures"]
    assert failures["reference_text_differs"] == 1
    assert failures["source_end_offset_differs"] == 1
    assert failures["target_not_in_target_case"] >= 1
