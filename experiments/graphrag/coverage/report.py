"""Phase 1 coverage report: aggregate statistics from a profile, no corpus text.

    poetry run python -m experiments.graphrag.coverage.report --build <id> [--audit sheet.csv]

Reads ``artifacts/mentions_<build>.jsonl`` and its ``.meta.json``; writes
``runs/coverage_<build>.json`` and ``runs/coverage_<build>.md``. Both hold only counts,
court codes, citation keys and report-series names, so they may be committed. With
``--audit``, a filled-in edge audit sheet adds edge precision as n/N, per method and per
evidence tier, with target identity reported apart from span and evidence quality.

Resolved references carry an evidence tier (``resolution.resolve.TIERS``): A neutral
citation, B name plus identifier, report or decision date, C name only. Graph policies are
selections by tier from the same records, never separate builds: ``tier_A``, ``tiers_A_B``
(strict) and ``tiers_A_B_C`` (broad, tier C being candidate evidence only).
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from experiments.graphrag.manifest import ARTIFACTS_DIR, RUNS_DIR, write_json
from experiments.graphrag.resolution.resolve import TIERS

RESOLVED = ("resolved_exact", "resolved_unique_fuzzy")
STATUSES = (
    "resolved_exact",
    "resolved_unique_fuzzy",
    "ambiguous",
    "target_absent",
    "unresolved",
    "self_reference",
    "temporal_conflict",
)
# A complete edge needs these: the mention is real, the target is the right decision, the
# evidence sentence the edge points to holds the citation and its context, and the dates
# are plausible. The exact reference span is reported but not required: an edge points to
# its evidence sentence, not to the span (decided 2026-10-28 after the v2 audit).
AUDIT_CHECKS = ("mention_ok", "target_ok", "evidence_ok", "temporal_ok")
OPTIONAL_CHECKS = ("span_ok",)
POLICIES = {"tier_A": {"A"}, "tiers_A_B": {"A", "B"}, "tiers_A_B_C": {"A", "B", "C"}}
# Phase 2 admission gate (docs/graphrag/coverage-report.md), per method / tier.
GATE = {"edge": 0.95, "target_ok": 0.97, "evidence_ok": 0.95, "temporal_ok": 1.0}
_YES = {"y", "yes", "1", "true", "ok"}
_NO = {"n", "no", "0", "false", "wrong"}


def load(path: Path) -> list[dict[str, Any]]:
    with path.open() as handle:
        return [json.loads(line) for line in handle]


def _bucket_table(
    records: list[dict[str, Any]], key: str, denominators: dict[str, int]
) -> dict[str, dict[str, Any]]:
    """Per bucket: chunks scanned, chunks with a reference, references, resolved, rate."""
    refs: Counter[str] = Counter()
    resolved: Counter[str] = Counter()
    chunks_with: dict[str, set[str]] = defaultdict(set)
    for record in records:
        bucket = str(record[key])
        refs[bucket] += 1
        chunks_with[bucket].add(record["chunk_id"])
        if record["status"] in RESOLVED:
            resolved[bucket] += 1
    table: dict[str, dict[str, Any]] = {}
    for bucket in sorted(set(denominators) | set(refs)):
        table[bucket] = {
            "chunks": denominators.get(bucket, 0),
            "chunks_with_reference": len(chunks_with[bucket]),
            "references": refs[bucket],
            "resolved": resolved[bucket],
            "resolved_share": round(resolved[bucket] / refs[bucket], 4) if refs[bucket] else None,
        }
    return table


def graph_shape(records: Iterable[dict[str, Any]], cases: int) -> dict[str, Any]:
    """Degree and reach over distinct resolved case-to-case edges (statistics, not a build).

    Nodes are cases (re-publication groups). Self references never become edges, and
    temporal conflicts are left out: they are review items, not edges.
    """
    edges = {(r["group"], r["target_group"]) for r in records if r["status"] in RESOLVED}
    out_edges: dict[str, set[str]] = defaultdict(set)
    in_edges: dict[str, set[str]] = defaultdict(set)
    for source, target in edges:
        out_edges[source].add(target)
        in_edges[target].add(source)
    nodes = set(out_edges) | set(in_edges)
    two_hop = {s for s, targets in out_edges.items() if any(out_edges.get(t) for t in targets)}
    out_degrees = sorted((len(v) for v in out_edges.values()), reverse=True)
    in_degrees = sorted((len(v) for v in in_edges.values()), reverse=True)
    return {
        "cases": cases,
        "edges": len(edges),
        "cases_with_outgoing": len(out_edges),
        "cases_with_incoming": len(in_edges),
        "cases_with_any_edge": len(nodes),
        "cases_with_degree_0": cases - len(nodes),
        "cases_starting_a_path_of_length_2": len(two_hop),
        "max_out_degree": out_degrees[0] if out_degrees else 0,
        "max_in_degree": in_degrees[0] if in_degrees else 0,
        "in_degree_top10": in_degrees[:10],
    }


def tier(record: dict[str, Any]) -> str:
    """A record's evidence tier ("-" for no method); older profiles carry only the method."""
    return str(record.get("tier") or TIERS.get(record["method"], "-"))


def summarise(records: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    denominators = meta["denominators"]
    by_kind = Counter(r["kind"] for r in records)
    chunks_by_kind: dict[str, set[str]] = defaultdict(set)
    for record in records:
        chunks_by_kind[record["kind"]].add(record["chunk_id"])
        for citation in record["citations"]:
            chunks_by_kind[f"has_{citation['kind']}"].add(record["chunk_id"])
        if record["name"]:
            chunks_by_kind["has_case_name"].add(record["chunk_id"])
    status_by_method: dict[str, Counter[str]] = defaultdict(Counter)
    reasons: Counter[str] = Counter()
    for record in records:
        status_by_method[record["method"]][record["status"]] += 1
        if record["reason"]:
            reasons[f"{record['status']}:{record['reason']}"] += 1
    report_series = Counter(
        c["token"] for r in records for c in r["citations"] if c["kind"] == "law_report"
    )
    unclassified = Counter(
        c["token"] for r in records for c in r["citations"] if c["kind"] == "unclassified"
    )
    neutral_courts = Counter(
        c["token"] for r in records for c in r["citations"] if c["kind"] == "neutral"
    )
    absent = Counter(
        next(c["key"] for c in r["citations"] if c["kind"] == "neutral")
        for r in records
        if r["status"] == "target_absent"
    )
    absent_foreign = sum(1 for r in records if r["status"] == "target_absent" and r["foreign"])
    with_ocr_flag = [
        {**r, "ocr": "ocr" if r["source_method"] == "ocr" else "machine_readable"} for r in records
    ]
    ocr_denominators = {
        "ocr": denominators["chunks_by_source_method"].get("ocr", 0),
        "machine_readable": denominators["chunks"]
        - denominators["chunks_by_source_method"].get("ocr", 0),
    }
    temporal = [r for r in records if r["status"] == "temporal_conflict"]
    return {
        "denominators": {k: v for k, v in denominators.items() if not k.startswith("chunks_by")},
        "references": len(records),
        "references_by_kind": dict(by_kind.most_common()),
        "chunks_with": {k: len(v) for k, v in sorted(chunks_by_kind.items())},
        "status_counts": dict(Counter(r["status"] for r in records).most_common()),
        "status_by_method": {m: dict(c.most_common()) for m, c in sorted(status_by_method.items())},
        "reasons": dict(reasons.most_common()),
        "neutral_citation_courts": dict(neutral_courts.most_common()),
        "target_absent_foreign": absent_foreign,
        "target_absent_top20": dict(absent.most_common(20)),
        "report_series_top20": dict(report_series.most_common(20)),
        "unclassified_tokens_top20": dict(unclassified.most_common(20)),
        "neutral_name_conflicts": sum(
            1 for r in records if r["reason"] == "name_conflicts_with_citation"
        ),
        "temporal_conflicts": {
            "references": len(temporal),
            "by_method": dict(Counter(r["method"] for r in temporal).most_common()),
        },
        "by_court": _bucket_table(records, "court", denominators["chunks_by_court"]),
        "by_decade": _bucket_table(records, "decade", denominators["chunks_by_decade"]),
        "by_source_method": _bucket_table(
            records, "source_method", denominators["chunks_by_source_method"]
        ),
        "by_ocr": _bucket_table(with_ocr_flag, "ocr", ocr_denominators),
        "by_reference_kind": {
            kind: {
                "references": n,
                "resolved": sum(
                    1 for r in records if r["kind"] == kind and r["status"] in RESOLVED
                ),
            }
            for kind, n in by_kind.most_common()
        },
        "status_by_tier": {
            t: dict(Counter(r["status"] for r in records if tier(r) == t).most_common())
            for t in sorted({tier(r) for r in records})
        },
        "resolved_by_tier_and_text": {
            t: dict(
                Counter(
                    "ocr" if r["source_method"] == "ocr" else "machine_readable"
                    for r in records
                    if tier(r) == t and r["status"] in RESOLVED
                )
            )
            for t in ("A", "B", "C")
        },
        "graph_shapes": {
            policy: graph_shape((r for r in records if tier(r) in tiers), denominators["cases"])
            for policy, tiers in POLICIES.items()
        },
    }


def _mark(value: str) -> bool | None:
    value = value.strip().lower()
    if value in _YES:
        return True
    if value in _NO:
        return False
    return None


def audit_precision(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    """Precision per check as n/N over the rows the auditor marked (blanks are skipped), per
    method and per tier. ``target_ok`` is identity precision; ``edge`` needs every required
    check; ``gate`` compares point estimates with the Phase 2 thresholds (``GATE``)."""

    def tally(subset: Sequence[dict[str, str]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for check in (*AUDIT_CHECKS, *OPTIONAL_CHECKS):
            marks = [m for row in subset if (m := _mark(row.get(check, ""))) is not None]
            result[check] = {"correct": sum(marks), "audited": len(marks)}
        # An edge is correct only when every check passed.
        complete = [
            row for row in subset if all(_mark(row.get(c, "")) is not None for c in AUDIT_CHECKS)
        ]
        result["edge"] = {
            "correct": sum(all(_mark(row[c]) for c in AUDIT_CHECKS) for row in complete),
            "audited": len(complete),
        }
        result["gate"] = {
            check: (
                result[check]["correct"] / result[check]["audited"] >= threshold
                if result[check]["audited"]
                else None
            )
            for check, threshold in GATE.items()
        }
        result["meets_gate"] = meets_gate(result["gate"])
        return result

    by_method: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_tier: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_method[row["method"]].append(row)
        by_tier[row.get("tier") or TIERS.get(row["method"]) or "-"].append(row)
    return {
        "rows": len(rows),
        "overall": tally(rows),
        "by_method": {method: tally(subset) for method, subset in sorted(by_method.items())},
        "by_tier": {t: tally(subset) for t, subset in sorted(by_tier.items())},
    }


def meets_gate(gate: dict[str, bool | None]) -> bool | None:
    """True only when every gate check was audited and passed; None when any check is
    unaudited (blank in the sheet) and none failed; False when one failed."""
    if any(ok is False for ok in gate.values()):
        return False
    if any(ok is None for ok in gate.values()):
        return None
    return True


def _fraction(cell: dict[str, int]) -> str:
    return f"{cell['correct']}/{cell['audited']}" if cell["audited"] else "–"


def markdown(summary: dict[str, Any], manifest: dict[str, Any]) -> str:
    def table(rows: dict[str, dict[str, Any]], label: str) -> list[str]:
        lines = [
            f"| {label} | Chunks | Chunks with a reference | References | Resolved "
            "| Resolved share |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for bucket, row in rows.items():
            share = f"{row['resolved_share']:.1%}" if row["resolved_share"] is not None else "–"
            lines.append(
                f"| {bucket} | {row['chunks']:,} | {row['chunks_with_reference']:,} | "
                f"{row['references']:,} | {row['resolved']:,} | {share} |"
            )
        return lines

    def counts(values: dict[str, int], label: str) -> list[str]:
        lines = [f"| {label} | Count |", "|---|---:|"]
        lines += [f"| {key} | {value:,} |" for key, value in values.items()]
        return lines

    shapes = summary["graph_shapes"]
    out = [
        f"# Coverage profile `{manifest['graph_build_id']}`",
        "",
        f"Generated by `experiments/graphrag/coverage/report.py` from run `{manifest['run_id']}` "
        f"(git `{manifest['git_sha'][:10]}`{', dirty tree' if manifest['git_dirty'] else ''}, "
        f"{manifest['timestamp']}). Corpus: {summary['denominators']['chunks']:,} chunks, "
        f"{summary['denominators']['judgments']:,} judgments, {summary['denominators']['cases']:,} "
        "cases. Extractors and resolver: "
        + ", ".join(
            f"`{v}`"
            for v in {
                **manifest["mention_extractor_versions"],
                **manifest["resolver_versions"],
            }.values()
        )
        + ".",
        "",
        "## References",
        "",
        *counts(summary["references_by_kind"], "Kind"),
        "",
        *counts(summary["chunks_with"], "Chunks containing"),
        "",
        "## Resolution",
        "",
        *counts(summary["status_counts"], "Status"),
        "",
        "| Method | " + " | ".join(STATUSES) + " |",
        "|---|" + "---:|" * len(STATUSES),
    ]
    for method, row in summary["status_by_method"].items():
        out.append(f"| {method} | " + " | ".join(f"{row.get(s, 0):,}" for s in STATUSES) + " |")
    out += ["", "| Tier | " + " | ".join(STATUSES) + " |", "|---|" + "---:|" * len(STATUSES)]
    for name, row in summary["status_by_tier"].items():
        out.append(f"| {name} | " + " | ".join(f"{row.get(s, 0):,}" for s in STATUSES) + " |")
    out += [
        "",
        "| Tier | Resolved, machine-readable text | Resolved, OCR text |",
        "|---|---:|---:|",
    ]
    for name, row in summary["resolved_by_tier_and_text"].items():
        out.append(f"| {name} | {row.get('machine_readable', 0):,} | {row.get('ocr', 0):,} |")
    out += [
        "",
        *counts(summary["reasons"], "Status: reason"),
        "",
        "Neutral citations contradicted by their own case name: "
        f"{summary['neutral_name_conflicts']}. Absent neutral citations to courts outside the "
        f"corpus: {summary['target_absent_foreign']} of "
        f"{summary['status_counts'].get('target_absent', 0)}.",
        "",
        "## Coverage by court, decade and source",
        "",
        *table(summary["by_court"], "Court"),
        "",
        *table(summary["by_decade"], "Decade (citing judgment)"),
        "",
        *table(summary["by_source_method"], "Source extraction"),
        "",
        *table(summary["by_ocr"], "Text"),
        "",
        "## Graph shape by policy (resolved edges between cases; statistics, no graph build)",
        "",
        "| | " + " | ".join(shapes) + " |",
        "|---|" + "---:|" * len(shapes),
    ]
    for key in shapes["tiers_A_B_C"]:
        if key == "in_degree_top10":
            continue
        out.append(f"| {key} | " + " | ".join(f"{s[key]:,}" for s in shapes.values()) + " |")
    out += [
        "",
        f"Largest in-degrees (tiers A+B): {shapes['tiers_A_B']['in_degree_top10']}.",
        "",
        "## Citation styles",
        "",
        *counts(summary["neutral_citation_courts"], "Neutral citation court"),
        "",
        *counts(summary["report_series_top20"], "Law-report series (top 20)"),
        "",
        *counts(summary["unclassified_tokens_top20"], "Unclassified bracket token (top 20)"),
        "",
        *counts(summary["target_absent_top20"], "Absent neutral citation (top 20)"),
        "",
    ]
    if "audit" in summary:
        audit = summary["audit"]
        columns = ("target_ok", "span_ok", "evidence_ok", "mention_ok", "temporal_ok", "edge")
        gate = ", ".join(f"{c} ≥ {t:.0%}" for c, t in GATE.items())
        out += [
            "## Edge audit",
            "",
            f"{audit['rows']} sampled edges. n/N = correct / audited; blanks not counted. "
            "`target_ok` is identity precision; `edge` needs mention, target, evidence and "
            f"temporal checks. Phase 2 gate per method: {gate}.",
            "",
            "| Group | " + " | ".join(columns) + " | Meets gate |",
            "|---|" + "---:|" * len(columns) + "---|",
        ]
        groups = [
            ("all", audit["overall"]),
            *((f"tier {t}", cells) for t, cells in audit["by_tier"].items()),
            *audit["by_method"].items(),
        ]
        for label, cells in groups:
            verdict = cells["meets_gate"]
            if all(ok is None for ok in cells["gate"].values()):
                meets = "–"
            elif verdict is None:
                meets = "incomplete"
            else:
                meets = "yes" if verdict else "no"
            out.append(
                f"| {label} | " + " | ".join(_fraction(cells[c]) for c in columns) + f" | {meets} |"
            )
        out.append("")
    return "\n".join(out)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.graphrag.coverage.report")
    parser.add_argument("--build", required=True, help="graph build id from profile_mentions")
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--out-dir", type=Path, default=RUNS_DIR)
    parser.add_argument("--audit", type=Path, help="a filled-in edge audit sheet (CSV)")
    args = parser.parse_args(argv)

    meta = json.loads((args.artifacts / f"mentions_{args.build}.meta.json").read_text())
    records = load(args.artifacts / meta["mentions_file"])
    summary = summarise(records, meta)
    if args.audit:
        with args.audit.open(newline="") as handle:
            summary["audit"] = audit_precision(list(csv.DictReader(handle)))
    manifest = {**meta["manifest"], "metrics": {"coverage": summary}}
    write_json(args.out_dir / f"coverage_{args.build}.json", manifest)
    (args.out_dir / f"coverage_{args.build}.md").write_text(markdown(summary, meta["manifest"]))
    sys.stdout.write(f"wrote {args.out_dir}/coverage_{args.build}.json and .md\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
