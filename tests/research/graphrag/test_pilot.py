"""Phase 3 pilot: question locks, seed sheet, expansion, ranking and metrics (no database)."""

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ejudgment.embeddings.fake import FakeReranker
from ejudgment.evaluation.retrieval import GoldPassage
from experiments.graphrag.graph.build import Graph
from experiments.graphrag.graph.policy import POLICIES
from experiments.graphrag.graph.traverse import Hop
from experiments.graphrag.pilot.questions import (
    PilotQuestion,
    draw_locals,
    gold_problems,
    import_intents,
    intent_problems,
    lock_gold,
    lock_intents,
    mark_stress_test,
    retire,
    run_problems,
)
from experiments.graphrag.pilot.report import paired, summarise
from experiments.graphrag.pilot.run import (
    GraphArtifactError,
    GraphView,
    RunConfig,
    case_metrics,
    evidence_hit,
    expand_seeds,
    hop_candidates,
    load_view,
    path_metrics,
    plan,
    rank_cases,
    returned_passages,
)
from experiments.graphrag.pilot.seeds import WRITER_COLUMNS, seed_rows

NOW = datetime(2026, 10, 29, tzinfo=UTC)


def incoming(qid: str = "inc-1", **extra: Any) -> PilotQuestion:
    fields: dict[str, Any] = {
        "id": qid,
        "question_class": "incoming",
        "query": "Which later decisions applied Mensah v Mensah on spousal property?",
        "anchor_uris": ["/akn/a"],
        "sampling": "seed s-001",
        "written_by": "Lexi",
    }
    return PilotQuestion.model_validate({**fields, **extra})


# --- questions and locks -------------------------------------------------------------------


def test_intent_rules() -> None:
    assert intent_problems(incoming()) == []
    assert intent_problems(incoming(anchor_uris=[])) == [
        "a relational question names its anchor case(s)"
    ]
    lineage = incoming(question_class="lineage")
    assert "a lineage question states its direction" in intent_problems(lineage)
    assert "direction contradicts the class" in intent_problems(incoming(direction="outgoing"))
    assert (
        incoming(question_class="lineage", direction="outgoing").traversal_direction() == "outgoing"
    )


def test_locks_freeze_intent_then_gold() -> None:
    question = incoming()
    assert lock_gold([question], NOW) == ["inc-1: intent not locked", "inc-1: no gold cases"]
    assert lock_intents([question], NOW) == []
    assert question.intent_hash == question.intent_digest()
    assert run_problems([question]) == ["inc-1: gold not locked, or changed since it was locked"]
    question.gold_case_uris = ["/akn/b"]
    question.gold_passages = [GoldPassage(canonical_uri="/akn/b", text="x" * 30)]
    assert lock_gold([question], NOW) == []
    assert run_problems([question]) == []
    question.query += " (edited)"  # an edit after locking is caught
    assert run_problems([question]) == ["inc-1: intent not locked, or changed since it was locked"]
    assert lock_intents([question], NOW) == ["inc-1: intent changed after it was locked"]


def test_gold_rules() -> None:
    passage = GoldPassage(canonical_uri="/akn/a", text="the anchor's own citing passage")
    outgoing = incoming(
        question_class="outgoing", gold_case_uris=["/akn/c"], gold_passages=[passage]
    )
    assert gold_problems(outgoing) == []  # a citing passage may lie in the anchor
    stray = incoming(
        gold_case_uris=["/akn/c"],
        gold_passages=[passage.model_copy(update={"canonical_uri": "/akn/z"})],
    )
    assert gold_problems(stray) == ["gold passage of /akn/z is not in a gold or anchor case"]
    lineage = incoming(
        question_class="lineage", direction="incoming", gold_case_uris=["/akn/b", "/akn/c"]
    )
    assert "a lineage question has at least one complete chain" in gold_problems(lineage)
    lineage.gold_paths = [["/akn/a", "/akn/b"]]
    assert gold_problems(lineage) == [
        "chain ['/akn/a', '/akn/b']: a lineage chain has at least three cases"
    ]
    lineage.gold_paths = [["/akn/a", "/akn/b", "/akn/c"], ["/akn/a", "/akn/c", "/akn/b"]]
    assert gold_problems(lineage) == []
    # Earlier records with a single gold_path still load.
    old = PilotQuestion.model_validate(
        {**lineage.model_dump(exclude={"gold_paths"}), "gold_path": ["/akn/a", "/akn/b", "/akn/c"]}
    )
    assert old.gold_paths == [["/akn/a", "/akn/b", "/akn/c"]]


def test_import_intents_and_draw_locals(tmp_path: Path) -> None:
    sheet = tmp_path / "intents.csv"
    with sheet.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "class",
                "query",
                "anchor_uris",
                "anchor_citations",
                "direction",
                "sampling",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "id": "lin-1",
                "class": "lineage",
                "query": "q",
                "anchor_uris": "/akn/a; /akn/b",
                "anchor_citations": "[2012] 1 SCGLR 391",
                "direction": "incoming",
                "sampling": "seed s-002",
            }
        )
    (question,) = import_intents(sheet)
    assert (question.anchor_uris, question.direction) == (["/akn/a", "/akn/b"], "incoming")
    first = draw_locals(Path("evals/gold.jsonl"), 8, seed=1)
    assert [q.id for q in first] == [q.id for q in draw_locals(Path("evals/gold.jsonl"), 8, seed=1)]
    assert len(first) == 8 and all(q.question_class == "local" and q.gold_case_uris for q in first)
    assert all(q.provisional for q in first)  # the gold set is unreviewed


# --- seed sheet ----------------------------------------------------------------------------


def test_seed_sheet_is_deterministic_and_reaches_beyond_the_graph() -> None:
    nodes = [
        {
            "case": f"g{i}",
            "judgments": [
                {
                    "uri": f"/akn/{i}",
                    "citation": f"C{i}",
                    "court": "ghasc" if i % 2 else "ghadc",
                    "date": f"20{10 + i % 12}-01-01",
                }
            ],
        }
        for i in range(40)
    ]
    edges = [{"source_case": f"g{i}", "target_case": "g1"} for i in range(2, 30)]
    rows = seed_rows(nodes, edges, 10, seed=3)
    assert [r["case"] for r in rows] == [r["case"] for r in seed_rows(nodes, edges, 10, seed=3)]
    assert any(r["in_degree"] == 0 for r in rows)  # cases the graph never reaches
    assert not {"in_degree", "out_degree", "stratum", "case"} & set(WRITER_COLUMNS)


# --- expansion and ranking -----------------------------------------------------------------


def view() -> GraphView:
    v = GraphView()
    # a cites b and c; d and e cite a; b cites f. hub cites nothing but is cited by many.
    for source, target in [("a", "b"), ("a", "c"), ("d", "a"), ("e", "a"), ("b", "f")]:
        v.outgoing[source].add(target)
        v.incoming[target].add(source)
        v.occurrences[(source, target)] = [f"chunk-{source}{target}"]
    return v


def test_plan_follows_the_class_or_both_ways() -> None:
    config = RunConfig()
    assert plan("G1-oracle", incoming(), config) == (("incoming",), 1, config.g1_max_nodes)
    assert plan("G1-both", incoming(), config)[0] == ("outgoing", "incoming")
    assert plan("G2-oracle", incoming(), config)[1] == 2
    assert plan("B0R", incoming(), config) == ((), 0, 0)
    local = PilotQuestion(id="l", question_class="local", query="q")
    assert plan("G1-oracle", local, config)[0] == ()  # no direction: the rescoring control


def test_expansion_by_direction_and_depth() -> None:
    config = RunConfig()
    later = expand_seeds(view(), ["a"], ("incoming",), 1, 50, config)
    assert sorted(h.case for h, _ in later) == ["d", "e"]  # who cited a
    relied = expand_seeds(view(), ["a"], ("outgoing",), 2, 50, config)
    assert [(h.case, h.depth) for h, _ in relied] == [("b", 1), ("c", 1), ("f", 2)]
    assert expand_seeds(view(), ["a"], ("outgoing",), 2, 2, config).__len__() == 2  # budget


def test_candidates_are_the_crossed_edges_citing_passages() -> None:
    config = RunConfig()
    assert hop_candidates(view(), Hop("b", 1, ("a", "b")), "outgoing", config) == ["chunk-ab"]
    assert hop_candidates(view(), Hop("d", 1, ("a", "d")), "incoming", config) == ["chunk-da"]


def test_cases_rank_by_their_best_passage() -> None:
    texts = {
        "p1": ("tenancy rent arrears", "a"),
        "p2": ("unrelated text", "b"),
        "p3": ("rent arrears tenancy eviction notice", "b"),
    }
    ranked = rank_cases(
        "tenancy rent arrears",
        [("a", "p1", "b0"), ("b", "p2", "b0"), ("b", "p3", "citing_incoming")],
        texts,
        FakeReranker(),
        top_k=20,
    )
    assert [c["case"] for c in ranked] == ["a", "b"]
    assert ranked[1]["passages"][0]["chunk_id"] == "p3"


# --- metrics -------------------------------------------------------------------------------


def test_case_evidence_and_path_metrics() -> None:
    assert case_metrics(["x", "g1", "y", "g2"], {"g1", "g2", "g3"}, 20) == {
        "recall@20": pytest.approx(2 / 3),
        "hit@20": True,
        "first_rank": 2,
        "rr@10": 0.5,
    }
    hit = evidence_hit(
        [("g1", "In Q v R the court held that costs follow the event.")],
        [("g1", "costs follow the event")],
    )
    assert hit == {"passage_recall@20": 1.0}
    assert evidence_hit([("g2", "costs follow the event")], [("g1", "costs follow the event")]) == {
        "passage_recall@20": 0.0
    }  # the same words in another case are no hit
    hops = [(Hop("b", 1, ("a", "b")), "outgoing"), (Hop("f", 2, ("a", "b", "f")), "outgoing")]
    path = path_metrics(hops, ["a"], [["a", "b", "f"], ["a", "c", "g"]])
    assert (path["gold_chains"], path["complete_paths"], path["complete_path_share"]) == (2, 1, 0.5)
    assert path["gold_edge_recall"] == 0.5  # a-b, b-f of a-b, b-f, a-c, c-g
    assert path["gold_node_recall"] == 3 / 5
    assert path["first_relevant_hop"] == 1 and path["unnecessary_nodes"] == 0


def test_paired_counts_and_summary() -> None:
    def record(qid: str, system: str, hit: bool) -> dict[str, Any]:
        return {
            "id": qid,
            "class": "incoming",
            "system": system,
            "provisional": False,
            "nodes_visited": 1,
            "candidate_cases": 1,
            "latency_ms": 10.0,
            "metrics": {
                "recall@20": float(hit),
                "hit@20": hit,
                "rr@10": float(hit),
                "passage_recall@20": None,
            },
        }

    records = [
        record("q1", "B0R", True),
        record("q1", "G1-oracle", True),
        record("q2", "B0R", False),
        record("q2", "G1-oracle", True),
        record("q3", "B0R", False),
        record("q3", "G1-oracle", False),
    ]
    result = paired(records, "B0R", "G1-oracle")
    assert (result["both"], result["only_B0R"], result["only_G1-oracle"], result["neither"]) == (
        1,
        0,
        1,
        1,
    )
    summary = summarise(records)
    assert summary["by_class"]["incoming"]["G1-oracle"]["hit@20"] == 2
    assert "B0R vs G1-oracle" in summary["paired_hit@20"]["all"]


def test_a_seed_reached_along_an_edge_keeps_its_citing_passage() -> None:
    config = RunConfig()
    hops = expand_seeds(view(), ["a", "d"], ("incoming",), 1, 50, config)
    assert ("d", ("a", "d")) in [(h.case, h.path) for h, _ in hops]


def test_hubs_are_reached_but_not_expanded() -> None:
    v = view()
    for i in range(10):  # a becomes a hub: cited by d, e and ten more cases
        v.outgoing[f"x{i}"].add("a")
        v.incoming["a"].add(f"x{i}")
    # Later treatment of f: b cites f, a cites b, and a's many citers lie beyond.
    capped = expand_seeds(v, ["f"], ("incoming",), 3, 100, RunConfig(hub_degree=5))
    assert {h.case for h, _ in capped} == {"b", "a"}  # a is reached, not expanded
    open_ = expand_seeds(v, ["f"], ("incoming",), 3, 100, RunConfig(hub_degree=None))
    assert {"d", "e", "x0"} <= {h.case for h, _ in open_}


def test_gold_finder_does_not_use_the_resolver_or_the_graph() -> None:
    import ast

    source = Path("experiments/graphrag/pilot/gold_finder.py").read_text()
    imported = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not {m for m in imported if ".resolution" in m or ".graph." in m or ".coverage" in m}


def test_gold_finder_keeps_short_surnames() -> None:
    from experiments.graphrag.pilot.gold_finder import side_patterns

    assert side_patterns("Adu Vrs Acheampong and Another") == [r"\m(ADU)\M", r"\m(ACHEAMPONG)\M"]
    assert side_patterns("Boi and Others Vrs Adjei and Others") == [r"\m(BOI)\M", r"\m(ADJEI)\M"]
    assert side_patterns("Republic Vrs Attorney General") == []  # generic on both sides


def test_a_retired_question_keeps_its_intent_and_is_not_run() -> None:
    kept, gone = incoming("inc-1"), incoming("inc-2")
    assert lock_intents([kept, gone], NOW) == []
    assert retire([kept, gone], "inc-2", "") == ["give the reason for retiring it"]
    assert retire([kept, gone], "inc-2", "no citing decision in the corpus") == []
    assert gone.intent_hash == gone.intent_digest()  # the locked intent is untouched
    kept.gold_case_uris = ["/akn/b"]
    assert lock_gold([kept, gone], NOW) == []  # the retired one needs no gold
    assert gone.gold_locked_at is None
    assert run_problems([kept, gone]) == []


def test_a_stress_test_is_frozen_with_the_gold_and_reported_apart() -> None:
    lineage = PilotQuestion(
        id="lin-1",
        question_class="lineage",
        direction="incoming",
        query="q",
        anchor_uris=["/akn/a"],
        sampling="seed s-002",
        gold_case_uris=["/akn/b"],
    )
    assert gold_problems(lineage) == ["a lineage question has at least one complete chain"]
    before = lineage.gold_digest()
    assert mark_stress_test([lineage], "lin-1", "") == ["give the reason for the stress test"]
    assert mark_stress_test([lineage], "lin-1", "67 first hops") == []
    assert gold_problems(lineage) == []  # its gold may stop at the first hop
    assert lineage.gold_digest() != before  # leaving the primary set changes the gold hash
    assert lock_intents([lineage], NOW) == [] and lock_gold([lineage], NOW) == []
    assert mark_stress_test([lineage], "lin-1", "again") == ["lin-1: its gold is already locked"]

    def record(qid: str, system: str, stress: bool) -> dict[str, Any]:
        return {
            "id": qid,
            "class": "lineage",
            "system": system,
            "provisional": False,
            "stress_test": stress,
            "nodes_visited": 1,
            "candidate_cases": 1,
            "latency_ms": 10.0,
            "metrics": {"recall@20": 1.0, "hit@20": True, "rr@10": 1.0, "passage_recall@20": None},
        }

    summary = summarise([record("lin-1", "B0", True), record("lin-2", "B0", False)])
    assert summary["by_class"]["all"]["B0"]["questions"] == 1
    assert summary["paired_hit@20"]["lineage"] == {}
    assert summary["stress_tests"]["lin-1"]["B0"]["questions"] == 1


def test_locked_gold_cannot_be_edited_and_relocked() -> None:
    question = incoming(gold_case_uris=["/akn/b"])
    assert lock_intents([question], NOW) == [] and lock_gold([question], NOW) == []
    stamp = question.gold_locked_at
    later = datetime(2026, 11, 1, tzinfo=UTC)
    assert lock_gold([question], later) == []  # unchanged: the lock is kept, not re-stamped
    assert question.gold_locked_at == stamp
    question.gold_case_uris = ["/akn/b", "/akn/c"]
    assert lock_gold([question], later) == ["inc-1: gold changed after it was locked"]
    assert question.gold_hash != question.gold_digest() and run_problems([question])


def _graph_files(tmp_path: Path) -> tuple[Path, Path]:
    graph = Graph(POLICIES["phase2-v1"])
    graph.nodes = {
        "g-a": {"case": "g-a", "judgments": [{"id": "j-a", "uri": "/akn/a"}]},
        "g-b": {"case": "g-b", "judgments": [{"id": "j-b", "uri": "/akn/b"}]},
    }
    occurrence = {
        "chunk_id": "c-1",
        "start": 1,
        "end": 9,
        "method": "neutral_exact",
        "target_ids": ["j-a"],
    }
    graph.edges = {("g-b", "g-a"): [occurrence]}
    artifacts, runs = tmp_path / "artifacts", tmp_path / "runs"
    artifacts.mkdir()
    runs.mkdir()
    (artifacts / "graph_phase2-v1_nodes.jsonl").write_text(
        "".join(json.dumps(n) + "\n" for n in graph.nodes.values())
    )
    (artifacts / "graph_phase2-v1_edges.jsonl").write_text(
        json.dumps({"source_case": "g-b", "target_case": "g-a", "occurrences": [occurrence]}) + "\n"
    )
    manifest = {"graph_fingerprint": graph.fingerprint(), "corpus_fingerprint": {"chunks": 1}}
    (runs / "graph_phase2-v1.json").write_text(json.dumps(manifest))
    return artifacts, runs


def test_the_graph_is_verified_against_its_manifest(tmp_path: Path) -> None:
    artifacts, runs = _graph_files(tmp_path)
    view = load_view(artifacts, "phase2-v1", runs)
    assert view.incoming["g-a"] == {"g-b"} and view.corpus == {"chunks": 1}
    edges = artifacts / "graph_phase2-v1_edges.jsonl"
    edges.write_text(edges.read_text().replace('"end": 9', '"end": 10'))  # rebuilt files
    with pytest.raises(GraphArtifactError, match="differs from the manifest"):
        load_view(artifacts, "phase2-v1", runs)
    (runs / "graph_phase2-v1.json").unlink()
    with pytest.raises(GraphArtifactError, match="no build manifest"):
        load_view(artifacts, "phase2-v1", runs)


def test_an_outgoing_citing_passage_is_evidence_of_the_citing_case() -> None:
    view = GraphView(group_of_uri={"/akn/anchor": "g-anchor", "/akn/cited": "g-cited"})
    citing = "In this case we follow the holding of Mensah v Mensah on spousal property."
    texts = {"c-1": (citing, "/akn/anchor")}
    ranked = [
        {"case": "g-cited", "score": 1.0, "passages": [{"chunk_id": "c-1", "role": "citing"}]}
    ]
    returned = returned_passages(ranked, texts, view)
    assert returned == [("g-anchor", citing)]
    assert ranked[0]["passages"][0]["source_case"] == "g-anchor"
    gold = [("g-anchor", "we follow the holding of Mensah v Mensah")]
    assert evidence_hit(returned, gold) == {"passage_recall@20": 1.0}
