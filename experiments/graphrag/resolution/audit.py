"""Audit sheets: a seeded, stratified random sample of resolved edges for a person to check.

    python -m experiments.graphrag.resolution.audit --build <id> [--per-tier A=40,B=60,C=20]

Writes, into ``artifacts/`` (gitignored: the sheets quote passages):

- ``edge_audit_<build>.csv``: resolved references with their context, evidence sentence,
  tier, decision signals and target, and blank columns ``mention_ok``, ``target_ok``
  (the right *decision*, not just the right parties), ``span_ok`` (the reference span),
  ``evidence_ok`` (the evidence sentence holds the citation and its context),
  ``temporal_ok`` and ``note`` for the auditor (y/n). ``coverage.report --audit`` turns
  them into precision n/N.
- ``review_<build>.csv``: ambiguous, unresolved, absent and temporal-conflict references,
  with an ``error_class`` column for the resolver error taxonomy.

The Phase 2 gate is judged per tier and method, so edges are sampled per tier (default 40
from tier A, 60 from B, 20 from C). Within a tier, strata are method × court × decade ×
OCR/machine-readable, visited in a seeded random order with one reference drawn from each
in turn, so every stratum present is represented once the sample is at least as large as
the number of strata.

``--exclude`` leaves out references that an earlier sheet already audited (same chunk,
overlapping span): rules tuned on an audit's errors must be checked on new references.
"""

import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from experiments.graphrag.manifest import ARTIFACTS_DIR

RESOLVED = ("resolved_exact", "resolved_unique_fuzzy")
REVIEW = ("ambiguous", "unresolved", "target_absent", "temporal_conflict")
GHALII = "https://ghalii.org"
AUDIT_COLUMNS = ("mention_ok", "target_ok", "span_ok", "evidence_ok", "temporal_ok", "note")


def stratum(record: dict[str, Any]) -> str:
    ocr = "ocr" if record["source_method"] == "ocr" else "text"
    return f"{record['method']}|{record['court']}|{record['decade']}|{ocr}"


def stratified_sample(
    records: Sequence[dict[str, Any]], size: int, seed: int
) -> list[dict[str, Any]]:
    """Round-robin over strata in a seeded order; deterministic for the same input and seed."""
    rng = random.Random(seed)
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in sorted(records, key=lambda r: (r["chunk_id"], r["start"])):
        strata[stratum(record)].append(record)
    order = sorted(strata)
    rng.shuffle(order)
    for key in order:
        rng.shuffle(strata[key])
    sample: list[dict[str, Any]] = []
    while len(sample) < size and any(strata[k] for k in order):
        for key in order:
            if strata[key] and len(sample) < size:
                sample.append(strata[key].pop())
    return sample


def per_tier_sample(
    records: Sequence[dict[str, Any]], sizes: dict[str, int], seed: int
) -> list[dict[str, Any]]:
    """``stratified_sample`` within each tier, in tier order."""
    sample: list[dict[str, Any]] = []
    for tier, size in sorted(sizes.items()):
        sample += stratified_sample([r for r in records if r.get("tier") == tier], size, seed)
    return sample


def audited_spans(paths: Sequence[Path]) -> dict[str, list[tuple[int, int]]]:
    """Chunk id -> source spans of the references earlier sheets audited or reviewed."""
    spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for path in paths:
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                spans[row["chunk_id"]].append((int(row["source_start"]), int(row["source_end"])))
    return spans


def not_audited(
    records: Sequence[dict[str, Any]], spans: dict[str, list[tuple[int, int]]]
) -> list[dict[str, Any]]:
    return [
        r
        for r in records
        if not any(
            start < r["source_end"] and r["source_start"] < end
            for start, end in spans.get(r["chunk_id"], [])
        )
    ]


def parse_sizes(value: str) -> dict[str, int]:
    """ "A=40,B=60,C=20" -> {"A": 40, "B": 60, "C": 20}."""
    sizes = {}
    for part in value.split(","):
        tier, _, size = part.partition("=")
        sizes[tier.strip().upper()] = int(size)
    return sizes


def _context(record: dict[str, Any]) -> str:
    return " ".join(
        f"{record['context_before']}[[{record['text']}]]{record['context_after']}".split()
    )


def _row(record: dict[str, Any], number: int) -> dict[str, Any]:
    return {
        "audit_id": number,
        "stratum": stratum(record),
        "method": record["method"],
        "tier": record.get("tier") or "",
        "status": record["status"],
        "reason": record["reason"] or "",
        "citing_judgment": record["citation"],
        "citing_date": record["date"] or "",
        "citing_link": GHALII + record["uri"],
        "reference": " ".join(record["text"].split()),
        "context": _context(record),
        "evidence": " ".join(record.get("evidence", "").split()),
        "identifiers": " ".join(record.get("identifiers", [])),
        "stages": " ".join(record.get("stages", [])),
        "decision_date": record.get("decision_date") or "",
        "ocr": "yes" if record.get("ocr") else "",
        "target_citation": record["target_citation"] or "",
        "target_date": record["target_date"] or "",
        "target_links": " ".join(GHALII + uri for uri in record["target_uris"]),
        "candidates": record["candidates"],
        "chunk_id": record["chunk_id"],
        "source_start": record["source_start"],
        "source_end": record["source_end"],
    }


def write_sheet(path: Path, rows: list[dict[str, Any]], extra: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*rows[0].keys(), *extra] if rows else extra)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, **{column: "" for column in extra}})


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.graphrag.resolution.audit")
    parser.add_argument("--build", required=True)
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--per-tier", type=parse_sizes, default=parse_sizes("A=40,B=60,C=20"))
    parser.add_argument("--review", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20261022)
    parser.add_argument(
        "--methods",
        type=lambda v: set(v.split(",")),
        default=None,
        help="sample only these resolution methods (a targeted re-audit)",
    )
    parser.add_argument(
        "--exclude", type=Path, action="append", default=[], help="an earlier audit or review sheet"
    )
    args = parser.parse_args(argv)

    meta = json.loads((args.artifacts / f"mentions_{args.build}.meta.json").read_text())
    with (args.artifacts / meta["mentions_file"]).open() as handle:
        records = [json.loads(line) for line in handle]
    records = not_audited(records, audited_spans(args.exclude))
    if args.methods:
        records = [r for r in records if r["method"] in args.methods]
    edges = per_tier_sample(
        [r for r in records if r["status"] in RESOLVED], args.per_tier, args.seed
    )
    review = stratified_sample(
        [r for r in records if r["status"] in REVIEW and r["method"] != "none"],
        args.review,
        args.seed,
    )
    edge_path = args.artifacts / f"edge_audit_{args.build}.csv"
    review_path = args.artifacts / f"review_{args.build}.csv"
    write_sheet(edge_path, [_row(r, i + 1) for i, r in enumerate(edges)], AUDIT_COLUMNS)
    write_sheet(
        review_path, [_row(r, i + 1) for i, r in enumerate(review)], ("error_class", "note")
    )
    sys.stdout.write(f"wrote {edge_path} ({len(edges)} edges) and {review_path} ({len(review)})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
