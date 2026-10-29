"""Seed sheet for the pilot question writer: candidate anchor cases, sampled blind.

    python -m experiments.graphrag.pilot.seeds [--policy phase2-v1] [--size 80]

Writes ``artifacts/pilot_seeds.csv`` (what the writer sees: citation, court, date, GhaLII
link) and ``artifacts/pilot_seeds_key.csv`` (stratum and graph degrees, for the analysis
only). Strata are court × incoming-degree band × period. Cases the graph never reaches
(in-degree 0) are a band of their own, so anchors are not chosen to suit the graph
(docs/graphrag/AGENTS.md rule 6); the writer never sees a case's degree.
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

GHALII = "https://ghalii.org"
IN_DEGREE_BANDS = ((0, 0), (1, 5), (6, 20), (21, 10**9))
WRITER_COLUMNS = ("seed_id", "citation", "court", "date", "ghalii_link")


def band(degree: int) -> str:
    for low, high in IN_DEGREE_BANDS:
        if low <= degree <= high:
            return (
                f"in{low}" if low == high else f"in{low}+" if high >= 10**9 else f"in{low}-{high}"
            )
    raise ValueError(degree)


def period(date: str | None) -> str:
    if not date:
        return "unknown"
    year = int(date[:4])
    return "before-2010" if year < 2010 else "2010s" if year < 2020 else "2020s"


def seed_rows(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], size: int, seed: int
) -> list[dict[str, Any]]:
    """Round-robin over strata in a seeded order, one case at a time; deterministic."""
    incoming: dict[str, int] = defaultdict(int)
    outgoing: dict[str, int] = defaultdict(int)
    for edge in edges:
        incoming[edge["target_case"]] += 1
        outgoing[edge["source_case"]] += 1
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in sorted(nodes, key=lambda n: n["case"]):
        first = node["judgments"][0]
        dates = sorted(j["date"] for j in node["judgments"] if j["date"])
        row = {
            "case": node["case"],
            "citation": first["citation"],
            "court": first["court"],
            "date": dates[0] if dates else "",
            "ghalii_link": GHALII + first["uri"],
            "uri": first["uri"],
            "in_degree": incoming[node["case"]],
            "out_degree": outgoing[node["case"]],
        }
        row["stratum"] = f"{row['court']}|{band(row['in_degree'])}|{period(row['date'] or None)}"
        strata[row["stratum"]].append(row)
    rng = random.Random(seed)
    order = sorted(strata)
    rng.shuffle(order)
    for key in order:
        rng.shuffle(strata[key])
    sample: list[dict[str, Any]] = []
    while len(sample) < size and any(strata[k] for k in order):
        for key in order:
            if strata[key] and len(sample) < size:
                sample.append(strata[key].pop())
    for number, row in enumerate(sample, start=1):
        row["seed_id"] = f"s-{number:03d}"
    return sample


def _write(path: Path, rows: list[dict[str, Any]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.graphrag.pilot.seeds")
    parser.add_argument("--policy", default="phase2-v1")
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--size", type=int, default=120)
    parser.add_argument("--seed", type=int, default=20261029)
    args = parser.parse_args(argv)
    stem = args.artifacts / f"graph_{args.policy}"
    with Path(f"{stem}_nodes.jsonl").open() as handle:
        nodes = [json.loads(line) for line in handle]
    with Path(f"{stem}_edges.jsonl").open() as handle:
        edges = [json.loads(line) for line in handle]
    rows = seed_rows(nodes, edges, args.size, args.seed)
    _write(args.artifacts / "pilot_seeds.csv", rows, WRITER_COLUMNS)
    _write(
        args.artifacts / "pilot_seeds_key.csv",
        rows,
        ("seed_id", "case", "uri", "stratum", "in_degree", "out_degree"),
    )
    sys.stdout.write(
        f"wrote {len(rows)} seeds from {len({r['stratum'] for r in rows})} strata to "
        f"{args.artifacts / 'pilot_seeds.csv'} (and the key file)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
