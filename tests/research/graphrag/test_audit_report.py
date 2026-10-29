"""Audit sampling and coverage aggregates (synthetic records)."""

from typing import Any

from experiments.graphrag.coverage.report import audit_precision, graph_shape
from experiments.graphrag.resolution.audit import stratified_sample, stratum


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
