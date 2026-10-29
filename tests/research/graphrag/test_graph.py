"""Phase 2 graph: admission, structure, fingerprint, traversal, statistics and RDF."""

import re
from datetime import date
from typing import Any

from experiments.graphrag.graph.build import Graph, build_graph
from experiments.graphrag.graph.policy import PHASE2_V1, AdmissionPolicy
from experiments.graphrag.graph.rdf import turtle
from experiments.graphrag.graph.stats import graph_statistics
from experiments.graphrag.graph.traverse import distances, expand
from experiments.graphrag.resolution.index import CorpusIndex, Judgment

INDEX = CorpusIndex.build(
    [
        Judgment(
            f"j{c}",
            f"/akn/gh/judgment/ghasc/2020/{i}/eng@2020-01-0{i}",
            f"g{c}",
            f"P{c} Vrs Q{c}",
            f"P{c} Vrs Q{c} [2020] GHASC {i}",
            None,
            date(2020, 1, i),
            "ghasc",
        )
        for i, c in enumerate("abcde", start=1)
    ]
)


def ref(source: str, target: str, method: str = "name_with_report", **extra: Any) -> dict[str, Any]:
    record = {
        "chunk_id": f"chunk-{source}-{target}-{method}",
        "judgment_id": f"j{source}",
        "uri": INDEX.judgments[f"j{source}"].uri,
        "court": "ghasc",
        "date": "2020-01-05",
        "group": f"g{source}",
        "target_group": f"g{target}",
        "start": 10,
        "end": 30,
        "source_start": 110,
        "source_end": 130,
        "evidence_start": 0,
        "evidence_end": 60,
        "text": 'Q v "R" \\ [2020] GHASC 1',
        "evidence": "In Q v R the court held.",
        "kind": "name_with_report",
        "method": method,
        "tier": {"neutral_exact": "A", "name_only": "C"}.get(method, "B"),
        "status": "resolved_exact" if method == "neutral_exact" else "resolved_unique_fuzzy",
        "reason": None,
        "target_ids": [f"j{target}"],
        "target_uris": [INDEX.judgments[f"j{target}"].uri],
        "target_date": "2020-01-01",
        "source_method": "legacy",
        "ocr": False,
    }
    return {**record, **extra}


RECORDS = [
    ref("e", "d"),
    ref("e", "d", "neutral_exact"),  # the same edge, a second occurrence
    ref("d", "c", "name_with_date"),
    ref("c", "a", "name_only"),  # not admitted: candidate evidence only
    ref("b", "a", "name_with_identifier"),  # not admitted yet
    ref("d", "a", "name_with_report", status="temporal_conflict"),  # a review item
    ref("e", "a", "name_with_report", status="ambiguous"),  # not an edge, not review
]


def graph() -> Graph:
    return build_graph(RECORDS, INDEX, PHASE2_V1)


def test_policy_admits_only_its_methods_and_resolved_statuses() -> None:
    built = graph()
    assert set(built.edges) == {("ge", "gd"), ("gd", "gc")}
    assert len(built.edges[("ge", "gd")]) == 2
    assert [o["method"] for o in built.review] == ["name_with_report"]
    assert set(built.nodes) == {"ga", "gb", "gc", "gd", "ge"}  # isolated cases are nodes


def test_fingerprint_is_stable_and_tracks_content() -> None:
    assert (
        graph().fingerprint()
        == build_graph(list(reversed(RECORDS)), INDEX, PHASE2_V1).fingerprint()
    )
    fewer = build_graph(RECORDS[1:], INDEX, PHASE2_V1)
    assert fewer.fingerprint() != graph().fingerprint()
    other = AdmissionPolicy(**{**PHASE2_V1.__dict__, "name": "other"})
    assert build_graph(RECORDS, INDEX, other).fingerprint() != graph().fingerprint()


def test_outgoing_is_authority_and_incoming_is_later_treatment() -> None:
    built = graph()
    assert built.outgoing()["ge"] == {"gd"}  # e relied on d
    assert built.incoming()["gd"] == {"ge"}  # d was cited later by e
    assert distances(built.outgoing(), "ge") == {"gd": 1, "gc": 2}


def test_bounded_expansion() -> None:
    adjacency = {
        "s": {"a", "b", "hub"},
        "a": {"c"},
        "hub": {f"x{i}" for i in range(10)},
        "c": {"s"},
    }
    one = expand(adjacency, "s", max_depth=1)
    assert [h.case for h in one] == ["a", "b", "hub"]
    two = expand(adjacency, "s", max_depth=2, hub_degree=5)
    assert "c" in {h.case for h in two}  # reached through a
    assert not any(h.case.startswith("x") for h in two)  # the hub is not expanded
    assert all(h.case != "s" for h in expand(adjacency, "s", max_depth=4))  # cycles stop
    assert len(expand(adjacency, "s", max_depth=2, max_branching=1)) == 2  # a, then c
    assert len(expand(adjacency, "s", max_depth=3, max_nodes=2)) == 2
    assert next(h for h in two if h.case == "c").path == ("s", "a", "c")


def test_statistics() -> None:
    stats = graph_statistics(graph())
    assert stats["edges"]["edges"] == 2 and stats["edges"]["occurrences"] == 3
    assert stats["components"]["with_an_edge"] == 1
    assert stats["components"]["isolated_cases"] == 2  # a and b
    assert stats["components"]["largest"] == 3
    assert stats["paths"]["length_histogram"] == {"1": 2, "2": 1}
    assert stats["degree"]["out_histogram"]["0"] == 3
    assert stats["temporal"]["review_items"] == 1
    assert stats["temporal"]["edges_whose_target_case_is_later"] == 0


def test_rdf_uses_cito_citation_nodes_and_holds_no_corpus_text() -> None:
    built = graph()
    out = turtle(
        built, built.fingerprint(), {"git_sha": "abc", "resolver_versions": {"resolver": "r3"}}
    )
    assert out.count("a cito:Citation") == 3
    assert "cito:hasCitationCharacterization cito:cites" in out
    citing, cited = INDEX.judgments["je"].uri, INDEX.judgments["jd"].uri
    assert f"<https://ghalii.org{citing}> cito:cites <https://ghalii.org{cited}> ." in out
    assert "court held" not in out and "[2020]" not in out  # no passage or reference text
    assert "Vrs" not in out  # no titles
    assert "ejg:referenceSha256" in out and 'ejg:resolutionMethod "neutral_exact"' in out
    for iri in re.findall(r"<([^>]*)>", out):
        assert not re.search(r"[\s<>\"{}|\\^`]", iri), iri


def test_a_changed_corpus_is_refused() -> None:
    from experiments.graphrag.graph.build import corpus_mismatches

    stored = {"eligible_judgments": 5, "judgments_digest": "j", "chunks": 9, "chunks_digest": "c"}
    assert corpus_mismatches(stored, {**stored, "embeddings_digest": "other"}) == []
    assert corpus_mismatches(stored, {**stored, "chunks_digest": "c2", "chunks": 10}) == [
        "chunks",
        "chunks_digest",
    ]


def test_each_graph_build_gets_its_own_manifest() -> None:
    from experiments.graphrag.graph.build import graph_manifest
    from experiments.graphrag.graph.rdf import RDF_SCHEMA_VERSION

    profile = {
        "run_id": "profile-run",
        "timestamp": "2026-10-22T00:00:00+00:00",
        "rdf_schema_version": None,
        "graph_build_id": "3325b81913b3",
        "corpus_fingerprint": {"chunks": 9},
    }
    git = {"git_sha": "abc", "git_branch": "x", "git_dirty": False}
    first = graph_manifest(profile, PHASE2_V1, "fp", {}, git=git)
    second = graph_manifest(profile, PHASE2_V1, "fp", {}, git=git)
    assert first["run_id"] != second["run_id"] != "profile-run"
    assert first["timestamp"] != profile["timestamp"]
    assert first["rdf_schema_version"] == RDF_SCHEMA_VERSION
    assert (first["profile_run_id"], first["profile_timestamp"]) == (
        "profile-run",
        profile["timestamp"],
    )
    assert first["corpus_fingerprint"] == {"chunks": 9}
