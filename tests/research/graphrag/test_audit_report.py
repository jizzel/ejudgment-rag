"""Audit sampling and coverage aggregates (synthetic records)."""

from typing import Any

from experiments.graphrag.coverage.diff import ADMITTED, diff_builds
from experiments.graphrag.coverage.report import audit_precision, graph_shape
from experiments.graphrag.resolution.audit import (
    changed_sample,
    per_method_sample,
    stratified_sample,
    stratum,
)


def record(n: int, method: str, court: str, decade: str, source: str = "legacy") -> dict[str, Any]:
    return {
        "chunk_id": f"c{n:04d}",
        "start": n,
        "method": method,
        "court": court,
        "decade": decade,
        "source_method": source,
    }


RECORDS = (
    [record(i, "name_only", "ghasc", "2020s") for i in range(50)]
    + [record(100 + i, "name_with_report", "ghadc", "2010s") for i in range(5)]
    + [record(200, "neutral_exact", "ghaca", "2000s")]
    + [record(300, "name_only", "ghahc", "2020s", source="ocr")]
)


def test_sample_is_deterministic_for_a_seed() -> None:
    first = stratified_sample(RECORDS, 6, seed=1)
    assert first == stratified_sample(list(reversed(RECORDS)), 6, seed=1)
    assert first != stratified_sample(RECORDS, 6, seed=2)


def test_sample_covers_every_stratum_before_repeating_one() -> None:
    strata = {stratum(r) for r in RECORDS}
    sample = stratified_sample(RECORDS, len(strata), seed=7)
    assert {stratum(r) for r in sample} == strata  # the single OCR record is included
    assert len(stratified_sample(RECORDS, 1000, seed=7)) == len(RECORDS)  # never repeats


def test_graph_shape_counts_cases_not_references() -> None:
    def ref(source: str, target: str, status: str = "resolved_exact") -> dict[str, Any]:
        return {"group": source, "target_group": target, "status": status}

    shape = graph_shape(
        [
            ref("a", "b"),
            ref("a", "b"),  # cited twice: one edge
            ref("b", "c"),
            ref("d", "c", "resolved_unique_fuzzy"),
            ref("e", "a", "temporal_conflict"),  # a review item, not an edge
            ref("e", "e", "self_reference"),
        ],
        cases=6,
    )
    assert (shape["edges"], shape["cases_with_outgoing"], shape["cases_with_incoming"]) == (3, 3, 2)
    assert shape["cases_with_degree_0"] == 2  # e (only a conflict and itself) and f
    assert shape["cases_starting_a_path_of_length_2"] == 1  # a -> b -> c
    assert shape["max_in_degree"] == 2


def test_audit_precision_is_n_over_n_and_skips_blanks() -> None:
    def row(method: str, *marks: str) -> dict[str, str]:
        keys = ("mention_ok", "target_ok", "evidence_ok", "temporal_ok")
        return {"method": method, **dict(zip(keys, marks, strict=True))}

    result = audit_precision(
        [
            row("name_only", "y", "y", "y", "y"),
            row("name_only", "y", "n", "y", "y"),
            row("neutral_exact", "yes", "YES", "1", "true"),
            row("neutral_exact", "y", "", "y", "y"),  # target not yet checked
        ]
    )
    assert result["overall"]["target_ok"] == {"correct": 2, "audited": 3}
    assert result["overall"]["edge"] == {"correct": 2, "audited": 3}
    assert result["by_method"]["name_only"]["edge"] == {"correct": 1, "audited": 2}


def test_audit_is_reported_per_tier_with_identity_apart_from_span() -> None:
    def row(method: str, target: str, span: str, evidence: str = "") -> dict[str, str]:
        return {
            "method": method,
            "mention_ok": "y",
            "target_ok": target,
            "span_ok": span,
            "evidence_ok": evidence,
            "temporal_ok": "y",
        }

    result = audit_precision(
        [
            row("neutral_exact", "y", "y", "y"),
            row("name_with_report", "y", "n", "y"),  # right decision, imperfect span
            row("name_with_identifier", "y", "y"),
            row("name_only", "n", "y"),
        ]
    )
    tier_b = result["by_tier"]["B"]
    assert tier_b["target_ok"] == {"correct": 2, "audited": 2}
    # The edge is gated on its evidence sentence; an imperfect span is reported only.
    assert tier_b["span_ok"] == {"correct": 1, "audited": 2}
    assert tier_b["edge"] == {"correct": 1, "audited": 1}  # blank evidence: not audited
    assert tier_b["gate"]["target_ok"] is True and tier_b["gate"]["edge"] is True
    assert "span_ok" not in tier_b["gate"]
    assert result["by_tier"]["C"]["gate"]["target_ok"] is False
    assert set(result["by_tier"]) == {"A", "B", "C"}


def test_graph_policies_select_by_tier() -> None:
    from experiments.graphrag.coverage.report import POLICIES, graph_shape, tier

    records = [
        {"group": "a", "target_group": "b", "status": "resolved_exact", "method": "neutral_exact"},
        {
            "group": "b",
            "target_group": "c",
            "status": "resolved_unique_fuzzy",
            "method": "name_with_report",
        },
        {
            "group": "c",
            "target_group": "d",
            "status": "resolved_unique_fuzzy",
            "method": "name_only",
        },
    ]
    edges = {
        policy: graph_shape([r for r in records if tier(r) in tiers], cases=4)["edges"]
        for policy, tiers in POLICIES.items()
    }
    assert edges == {"tier_A": 1, "tiers_A_B": 2, "tiers_A_B_C": 3}


def test_audit_sample_is_drawn_per_tier() -> None:
    from experiments.graphrag.resolution.audit import parse_sizes, per_tier_sample

    records = [{**record(i, "name_only", "ghasc", "2020s"), "tier": "C"} for i in range(50)] + [
        {**record(100 + i, "neutral_exact", "ghaca", "2010s"), "tier": "A"} for i in range(5)
    ]
    sample = per_tier_sample(records, parse_sizes("A=3,C=4"), seed=1)
    assert [r["tier"] for r in sample] == ["A"] * 3 + ["C"] * 4


def test_previously_audited_references_are_excluded(tmp_path: Any) -> None:
    import csv

    from experiments.graphrag.resolution.audit import audited_spans, not_audited

    sheet = tmp_path / "old.csv"
    with sheet.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["chunk_id", "source_start", "source_end"])
        writer.writeheader()
        writer.writerow({"chunk_id": "c1", "source_start": 100, "source_end": 140})
    records = [
        {"chunk_id": "c1", "source_start": 120, "source_end": 160},  # overlaps: excluded
        {"chunk_id": "c1", "source_start": 140, "source_end": 180},  # adjacent: kept
        {"chunk_id": "c2", "source_start": 100, "source_end": 140},  # another chunk: kept
    ]
    kept = not_audited(records, audited_spans([sheet]))
    assert [(r["chunk_id"], r["source_start"]) for r in kept] == [("c1", 140), ("c2", 100)]


def test_a_partly_audited_group_does_not_pass_the_gate() -> None:
    from experiments.graphrag.coverage.report import markdown, meets_gate

    complete = {"mention_ok": "y", "target_ok": "y", "evidence_ok": "y", "temporal_ok": "y"}
    no_temporal = {**complete, "temporal_ok": ""}
    result = audit_precision(
        [{"method": "neutral_exact", **complete}, {"method": "name_with_date", **no_temporal}]
    )
    assert result["by_method"]["neutral_exact"]["meets_gate"] is True
    # Temporal (and therefore the complete edge) was never audited for this method.
    assert result["by_method"]["name_with_date"]["meets_gate"] is None
    assert meets_gate({"edge": True, "target_ok": False, "temporal_ok": None}) is False
    summary = {
        "denominators": {"chunks": 1, "judgments": 1, "cases": 1},
        "references_by_kind": {},
        "chunks_with": {},
        "status_counts": {},
        "status_by_method": {},
        "status_by_tier": {},
        "resolved_by_tier_and_text": {},
        "reasons": {},
        "neutral_name_conflicts": 0,
        "target_absent_foreign": 0,
        "by_court": {},
        "by_decade": {},
        "by_source_method": {},
        "by_ocr": {},
        "graph_shapes": {
            p: {"in_degree_top10": [], "edges": 0} for p in ("tier_A", "tiers_A_B", "tiers_A_B_C")
        },
        "neutral_citation_courts": {},
        "report_series_top20": {},
        "unclassified_tokens_top20": {},
        "target_absent_top20": {},
        "audit": result,
    }
    manifest = {
        "graph_build_id": "b",
        "run_id": "r",
        "git_sha": "abcdef0123",
        "git_dirty": False,
        "timestamp": "t",
        "mention_extractor_versions": {},
        "resolver_versions": {},
    }
    table = markdown(summary, manifest)
    assert "| name_with_date |" in table
    assert next(
        line for line in table.splitlines() if line.startswith("| name_with_date |")
    ).endswith("| incomplete |")


def test_a_build_diff_lists_added_removed_and_retargeted_edges() -> None:
    def occ(chunk: str, method: str, target: str, status: str = "resolved_exact") -> dict[str, Any]:
        return {
            "chunk_id": chunk,
            "start": 1,
            "end": 9,
            "uri": f"/akn/{chunk}",
            "method": method,
            "status": status,
            "target_group": target,
        }

    old = [
        occ("same", "name_with_report", "g1"),
        occ("moved", "name_with_report", "g1"),
        occ("gone", "name_with_date", "g2"),
        occ("ignored", "name_with_identifier", "g3"),  # not an admitted method
    ]
    new = [
        occ("same", "name_with_report", "g1"),
        occ("moved", "name_with_report", "g9"),
        occ("gone", "name_with_date", "g2", status="unresolved"),
        occ("fresh", "neutral_exact", "g4"),
        occ("ignored", "name_with_proceeding", "g3"),
    ]
    summary, rows = diff_builds(old, new, ADMITTED)
    assert {r["chunk_id"]: r["change"] for r in rows} == {
        "moved": "retargeted",
        "gone": "removed",
        "fresh": "added",
    }
    assert summary["by_method"]["name_with_report"] == {
        "added": 0,
        "removed": 0,
        "retargeted": 1,
        "respanned": 0,
    }
    assert (summary["edges_before"], summary["edges_after"]) == (3, 3)


def test_changed_edges_are_sampled_once_and_only_if_resolved() -> None:
    rows = [
        {**record(n, "name_with_date", "ghasc", "2020s"), "end": n + 5, "status": "resolved_exact"}
        for n in range(4)
    ]
    rows[3] = {**rows[3], "status": "unresolved"}
    diff = [
        {
            "change": "added",
            "chunk_id": r["chunk_id"],
            "start": str(r["start"]),
            "end": str(r["end"]),
        }
        for r in rows
    ] + [{"change": "removed", "chunk_id": "c9999", "start": "0", "end": "1"}]
    picked = changed_sample(rows, diff, size=10, seed=1, taken=[rows[0]])
    assert sorted(r["chunk_id"] for r in picked) == ["c0001", "c0002"]


def test_per_method_sizes_give_a_small_method_its_own_rows() -> None:
    big = [record(i, "name_with_dated_proceeding", "ghasc", "2020s") for i in range(50)]
    small = [
        record(100 + i, "name_with_decision_identifier", "ecowascj", "2010s") for i in range(5)
    ]
    picked = per_method_sample(
        big + small, {"name_with_decision_identifier": 4, "name_with_dated_proceeding": 6}, seed=1
    )
    methods = [r["method"] for r in picked]
    assert methods.count("name_with_decision_identifier") == 4
    assert methods.count("name_with_dated_proceeding") == 6


def test_a_reference_that_only_grew_is_respanned_not_added_and_removed() -> None:
    def occ(start: int, end: int, target: str) -> dict[str, Any]:
        return {
            "chunk_id": "c",
            "start": start,
            "end": end,
            "uri": "/akn/c",
            "method": "name_with_report",
            "status": "resolved_exact",
            "target_group": target,
        }

    summary, rows = diff_builds([occ(10, 30, "g1")], [occ(10, 39, "g1")], ADMITTED)
    assert [r["change"] for r in rows] == ["respanned"]
    summary, rows = diff_builds([occ(10, 30, "g1")], [occ(10, 39, "g2")], ADMITTED)
    assert [r["change"] for r in rows] == ["retargeted"]
    summary, rows = diff_builds([occ(10, 30, "g1")], [occ(50, 60, "g1")], ADMITTED)
    assert sorted(r["change"] for r in rows) == ["added", "removed"]


def test_removed_edges_are_sampled_from_the_old_build_on_request() -> None:
    old = [
        {**record(n, "name_with_date", "ghasc", "2020s"), "end": n + 5, "status": "resolved_exact"}
        for n in range(3)
    ]
    diff = [
        {"change": "removed", "chunk_id": "c0000", "start": "0", "end": "5"},
        {"change": "added", "chunk_id": "c0001", "start": "1", "end": "6"},
    ]
    assert [r["chunk_id"] for r in changed_sample(old, diff, 10, 1)] == ["c0001"]
    removed = changed_sample(old, diff, 10, 1, kinds=("removed",))
    assert [r["chunk_id"] for r in removed] == ["c0000"]


def test_a_target_now_a_copy_of_a_decision_is_the_same_edge() -> None:
    def occ(target: str) -> dict[str, Any]:
        return {
            "chunk_id": "c",
            "start": 1,
            "end": 9,
            "uri": "/akn/c",
            "method": "name_with_date",
            "status": "resolved_exact",
            "target_group": target,
        }

    # The old build pointed at text group "g2", the new at decision "g1" (g2 is its copy).
    _, rows = diff_builds([occ("g2")], [occ("g1")], ADMITTED, {"g1": "g1", "g2": "g1"})
    assert rows == []
    _, rows = diff_builds([occ("g2")], [occ("g1")], ADMITTED)
    assert [r["change"] for r in rows] == ["retargeted"]
