"""What changed between two resolution builds, for the methods a graph already admits.

    python -m experiments.graphrag.coverage.diff --old 3325b81913b3 --new <build>
        [--methods neutral_exact,name_with_report,name_with_date]

A resolver change aimed at one method can move others too (v5's identifier binding also
feeds the ``identifier_mismatch`` filter every name method applies). Edges of an admitted
method that a new build adds, drops or retargets were never audited as such, so they are
listed for the next audit sheet. An occurrence is keyed by its chunk and offsets; an edge
whose reference only grew or shrank (an overlapping span in the same chunk) is
``respanned`` when its target is unchanged, ``retargeted`` when not. With ``--decisions``
(the new build's ``decisions_<build>.jsonl``) targets are compared as decisions: an old
edge to a text group that is now a copy of decision D is the same edge as one to D.

Writes ``runs/resolution_diff_<old>_<new>.json`` (counts only, committable) and
``artifacts/resolution_diff_<old>_<new>.csv`` (one row per changed occurrence; identifiers
and offsets, no corpus text, but it sits with the other per-reference artifacts).
"""

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from experiments.graphrag.manifest import ARTIFACTS_DIR, RUNS_DIR, write_json
from experiments.graphrag.resolution.resolve import RESOLVED

ADMITTED = ("neutral_exact", "name_with_report", "name_with_date")
Key = tuple[str, int, int]


def _edges(records: Iterable[dict[str, Any]], methods: frozenset[str]) -> dict[Key, dict[str, Any]]:
    """Resolved occurrences of the given methods, by (chunk, start, end)."""
    return {
        (r["chunk_id"], int(r["start"]), int(r["end"])): r
        for r in records
        if r["method"] in methods and r["status"] in RESOLVED
    }


def diff_builds(
    old: Iterable[dict[str, Any]],
    new: Iterable[dict[str, Any]],
    methods: Sequence[str],
    decision_of: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Counts of added, removed and retargeted edges per method, and the changed rows.
    ``decision_of`` (text group -> decision) compares targets as decisions."""
    wanted = frozenset(methods)
    case = (lambda g: decision_of.get(g, g)) if decision_of else (lambda g: g)
    before = {
        k: {**r, "target_group": case(r["target_group"])} for k, r in _edges(old, wanted).items()
    }
    after = {
        k: {**r, "target_group": case(r["target_group"])} for k, r in _edges(new, wanted).items()
    }
    # Pair an occurrence that only lost its key with the overlapping one in the same chunk.
    gone = sorted(before.keys() - after.keys())
    fresh = sorted(after.keys() - before.keys())
    paired: dict[Key, Key] = {}
    by_chunk: dict[str, list[Key]] = {}
    for key in fresh:
        by_chunk.setdefault(key[0], []).append(key)
    for key in gone:
        match = next(
            (
                k
                for k in by_chunk.get(key[0], [])
                if k not in paired.values() and k[1] < key[2] and key[1] < k[2]
            ),
            None,
        )
        if match is not None:
            paired[key] = match
    rows: list[dict[str, Any]] = []
    counts: Counter[tuple[str, str]] = Counter()
    keys = sorted((before.keys() & after.keys()) | set(gone) | (set(fresh) - set(paired.values())))
    for key in keys:
        was = before.get(key)
        now = after.get(paired.get(key, key))
        if was is not None and now is not None:
            if (was["method"], was["target_group"]) == (now["method"], now["target_group"]):
                if paired.get(key, key) == key:
                    continue
                change = "respanned"
            else:
                change = "retargeted"
        else:
            change = "added" if was is None else "removed"
        record = now or was
        assert record is not None
        key = paired.get(key, key) if now is not None else key
        counts[(record["method"], change)] += 1
        rows.append(
            {
                "change": change,
                "chunk_id": key[0],
                "start": key[1],
                "end": key[2],
                "uri": record["uri"],
                "old_method": was["method"] if was else "",
                "old_target_group": was["target_group"] if was else "",
                "new_method": now["method"] if now else "",
                "new_target_group": now["target_group"] if now else "",
            }
        )
    summary = {
        "methods": sorted(wanted),
        "edges_before": len(before),
        "edges_after": len(after),
        "changed": len(rows),
        "by_method": {
            method: {
                c: counts[(method, c)] for c in ("added", "removed", "retargeted", "respanned")
            }
            for method in sorted(wanted)
        },
    }
    return summary, rows


def _decision_map(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8") as handle:
        return {
            copy["text_group"]: record["decision"]
            for record in map(json.loads, handle)
            for copy in record["copies"]
        }


def _records(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.graphrag.coverage.diff")
    parser.add_argument("--old", required=True, help="build id")
    parser.add_argument("--new", required=True, help="build id")
    parser.add_argument("--methods", default=",".join(ADMITTED))
    parser.add_argument("--decisions", type=Path, help="the new build's decisions_<build>.jsonl")
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--out-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args(argv)
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    summary, rows = diff_builds(
        _records(args.artifacts / f"mentions_{args.old}.jsonl"),
        _records(args.artifacts / f"mentions_{args.new}.jsonl"),
        methods,
        _decision_map(args.decisions) if args.decisions else None,
    )
    stem = f"resolution_diff_{args.old}_{args.new}"
    write_json(args.out_dir / f"{stem}.json", {"old": args.old, "new": args.new, **summary})
    columns = list(rows[0]) if rows else ["change"]
    with (args.artifacts / f"{stem}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    sys.stdout.write(
        f"{summary['edges_before']} -> {summary['edges_after']} edges of {', '.join(methods)}; "
        f"{summary['changed']} changed -> {args.out_dir / stem}.json\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
