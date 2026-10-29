"""Phase 3 pilot metrics: per class, per system, paired against the baseline.

Exact counts and descriptive differences only. A 30-question hand-curated pilot is
hypothesis-generating: no significance claims (docs/graphrag/AGENTS.md rule 7). The exact
McNemar p of the paired Hit@20 counts is reported as a number, not as a verdict.
"""

from collections import defaultdict
from statistics import mean
from typing import Any

from ejudgment.evaluation.ghalii_benchmark import mcnemar_p
from ejudgment.evaluation.retrieval import percentile

CLASSES = ("local", "outgoing", "incoming", "lineage")
SYSTEM_ORDER = ("B0", "B0R", "G1-top5-label", "G1-top5-both", "G2-top5-label", "G1-routed")
PAIRS = (
    ("B0", "G1-top5-label"),
    ("B0R", "G1-top5-label"),
    ("B0R", "G1-top5-both"),
    ("B0R", "G2-top5-label"),
    # The routing probe: against the rescoring control, and against the same one hop from
    # B0's top 5 (only the entry point and the routed direction differ).
    ("B0R", "G1-routed"),
    ("G1-top5-label", "G1-routed"),
)
# Names before runner v4: "oracle" described only the direction, the seeds were B0's top 5.
LEGACY_NAMES = {
    "G1-oracle": "G1-top5-label",
    "G1-both": "G1-top5-both",
    "G2-oracle": "G2-top5-label",
}


def current_name(system: str) -> str:
    """A system's name in current runs, for reading older run files side by side."""
    return LEGACY_NAMES.get(system, system)


def _mean(values: list[Any]) -> float | None:
    present = [float(v) for v in values if v is not None]
    return round(mean(present), 4) if present else None


def _block(records: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = [r["metrics"] for r in records]
    latencies = [r["latency_ms"] for r in records]
    return {
        "questions": len(records),
        "recall@20": _mean([m["recall@20"] for m in metrics]),
        "hit@20": sum(bool(m["hit@20"]) for m in metrics),
        "mrr@10": _mean([m["rr@10"] for m in metrics]),
        "passage_recall@20": _mean([m["passage_recall@20"] for m in metrics]),
        "seed_recall": _mean([m.get("seed_recall") for m in metrics]),
        "gold_node_recall": _mean([m.get("gold_node_recall") for m in metrics]),
        "gold_edge_recall": _mean([m.get("gold_edge_recall") for m in metrics]),
        "complete_paths": sum(int(m.get("complete_paths") or 0) for m in metrics),
        "complete_path_share": _mean([m.get("complete_path_share") for m in metrics]),
        "unnecessary_nodes": _mean([m.get("unnecessary_nodes") for m in metrics]),
        "nodes_visited": _mean([r["nodes_visited"] for r in records]),
        "candidate_cases": _mean([r["candidate_cases"] for r in records]),
        "latency_p50_ms": round(percentile(latencies, 0.5), 1) if latencies else None,
        "latency_p95_ms": round(percentile(latencies, 0.95), 1) if latencies else None,
    }


def paired(records: list[dict[str, Any]], a: str, b: str) -> dict[str, Any]:
    """Hit@20 per question, system ``a`` against ``b``."""
    hits: dict[str, dict[str, bool]] = defaultdict(dict)
    for r in records:
        if r["system"] in (a, b):
            hits[r["id"]][r["system"]] = bool(r["metrics"]["hit@20"])
    both_present = [h for h in hits.values() if a in h and b in h]
    only_a = sum(h[a] and not h[b] for h in both_present)
    only_b = sum(h[b] and not h[a] for h in both_present)
    return {
        "questions": len(both_present),
        "both": sum(h[a] and h[b] for h in both_present),
        f"only_{a}": only_a,
        f"only_{b}": only_b,
        "neither": sum(not h[a] and not h[b] for h in both_present),
        "mcnemar_p": round(mcnemar_p(only_a, only_b), 4),
    }


def summarise(all_records: list[dict[str, Any]]) -> dict[str, Any]:
    """Primary scores over every question but the stress tests, which are reported one by
    one beside them."""
    records = [r for r in all_records if not r.get("stress_test")]
    stress: dict[str, dict[str, Any]] = defaultdict(dict)
    for r in all_records:
        if r.get("stress_test"):
            stress[r["id"]][r["system"]] = _block([r])
    by: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by[(r["class"], r["system"])].append(r)
        by[("all", r["system"])].append(r)
    systems = sorted(
        {r["system"] for r in records},
        key=lambda s: SYSTEM_ORDER.index(current_name(s)),
    )
    classes = ["all", *[c for c in CLASSES if any(r["class"] == c for r in records)]]
    return {
        "by_class": {c: {s: _block(by[(c, s)]) for s in systems if by[(c, s)]} for c in classes},
        "paired_hit@20": {
            c: {
                f"{a} vs {b}": paired([r for r in records if c == "all" or r["class"] == c], a, b)
                for a, b in PAIRS
                if a in systems and b in systems
            }
            for c in classes
        },
        "provisional_questions": sorted({r["id"] for r in records if r["provisional"]}),
        "stress_tests": dict(sorted(stress.items())),
        "routing": routing_summary(records),
    }


def routing_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """How the router did, per class: the named case found among its resolved seeds, the
    direction read correctly, and the resolved seeds per question; plus each question's
    routing record. One record per question (the routing is the same for every system)."""
    routed = {r["id"]: r for r in records if "routing" in r}
    out: dict[str, Any] = {}
    for cls in ["all", *CLASSES]:
        group = [r for r in routed.values() if cls == "all" or r["class"] == cls]
        if not group:
            continue
        found = [r["routing"]["anchor_found"] for r in group]
        correct = [r["routing"]["direction_correct"] for r in group]
        out[cls] = {
            "questions": len(group),
            "named_case_extracted": sum(
                r["routing"]["name"] is not None or r["routing"]["citation"] is not None
                for r in group
            ),
            "anchor_found": _mean([f for f in found if f is not None]),
            "direction_correct": _mean([c for c in correct if c is not None]),
            "resolved_seeds": _mean([r["routing"]["resolved_count"] for r in group]),
        }
    out["questions"] = {qid: r["routing"] for qid, r in sorted(routed.items())}
    return out


def markdown(summary: dict[str, Any], manifest: dict[str, Any]) -> str:
    def fmt(value: Any) -> str:
        if value is None:
            return "–"
        return f"{value:.3f}" if isinstance(value, float) else str(value)

    graph = manifest.get("graph_config", {})
    out = [
        "# Phase 3 pilot",
        "",
        f"Run `{manifest['run_id']}` ({manifest['timestamp']}), git `{manifest['git_sha'][:10]}`"
        f"{', dirty tree' if manifest['git_dirty'] else ''}. Question set "
        f"`{manifest['query_set_hash'][:12]}`; graph `{graph.get('policy')}` "
        f"(`{str(graph.get('graph_fingerprint', ''))[:16]}`), seeds {graph.get('seed_k')}.",
        "",
        "Hypothesis-generating: paired counts and descriptive differences only. "
        "`G*-oracle` takes the direction from the question's class label.",
        "",
    ]
    columns = (
        "questions",
        "recall@20",
        "hit@20",
        "mrr@10",
        "passage_recall@20",
        "seed_recall",
        "gold_edge_recall",
        "complete_path_share",
        "nodes_visited",
        "latency_p50_ms",
    )
    for cls, systems in summary["by_class"].items():
        out += [
            f"## {cls}",
            "",
            "| System | " + " | ".join(columns) + " |",
            "|---|" + "---:|" * len(columns),
        ]
        for system, block in systems.items():
            out.append(f"| {system} | " + " | ".join(fmt(block[c]) for c in columns) + " |")
        out.append("")
        pairs = summary["paired_hit@20"].get(cls, {})
        if pairs:
            out += [
                "| Paired Hit@20 | Questions | Both | Only first | Only second | Neither "
                "| McNemar p |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
            for label, p in pairs.items():
                first, second = label.split(" vs ")
                out.append(
                    f"| {label} | {p['questions']} | {p['both']} | {p[f'only_{first}']} | "
                    f"{p[f'only_{second}']} | {p['neither']} | {p['mcnemar_p']} |"
                )
            out.append("")
    if summary["provisional_questions"]:
        out += [
            "Provisional (unreviewed local controls): "
            f"{', '.join(summary['provisional_questions'])}.",
            "",
        ]
    routing = summary.get("routing", {})
    if routing.get("questions"):
        out += [
            "## Routing (G1-routed)",
            "",
            "| Class | Questions | Named case extracted | Anchor found | Direction correct "
            "| Resolved seeds |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for cls, block in routing.items():
            if cls == "questions":
                continue
            out.append(
                f"| {cls} | {block['questions']} | {block['named_case_extracted']} | "
                f"{fmt(block['anchor_found'])} | {fmt(block['direction_correct'])} | "
                f"{fmt(block['resolved_seeds'])} |"
            )
        out += [
            "",
            "| Question | Name | Year | Direction | Resolved | Anchor found |",
            "|---|---|---:|---|---:|---|",
        ]
        for qid, r in routing["questions"].items():
            if r["name"] is None and r["citation"] is None:
                continue
            out.append(
                f"| {qid} | {r['name'] or r['citation']} | {fmt(r['year'])} | "
                f"{r['direction'] or 'both'} | {r['resolved_count']} | {fmt(r['anchor_found'])} |"
            )
        out.append("")
    for question_id, systems in summary.get("stress_tests", {}).items():
        out += [
            f"## Stress test {question_id} (not in the scores above)",
            "",
            "| System | " + " | ".join(columns) + " |",
            "|---|" + "---:|" * len(columns),
        ]
        for system, block in systems.items():
            out.append(f"| {system} | " + " | ".join(fmt(block[c]) for c in columns) + " |")
        out.append("")
    return "\n".join(out)
