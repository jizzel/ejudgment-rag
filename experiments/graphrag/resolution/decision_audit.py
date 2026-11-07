"""Decision audit sheet: are the text groups a build merged really copies of one decision?

    python -m experiments.graphrag.resolution.decision_audit --build <id> [--merges 25]

Reads ``decision_pairs_<build>.jsonl`` and ``decisions_<build>.jsonl`` (``coverage.
profile_mentions``) and, read-only from the database, each text group's citations, so the
auditor sees both sides. Writes ``artifacts/decision_audit_<build>.csv`` with a blank
``same_decision`` column (y/n) and ``note``; ``coverage.report --decision-audit`` scores it.

- ``merge`` rows: candidate pairs the build put in one decision. The lowest-similarity
  merges are always included (``LOWEST``); the rest are drawn round-robin over court ×
  similarity band in a seeded order, so every court with merges is represented.
- ``non_merge`` rows: the high-risk pairs the build kept apart, all of them up to
  ``--non-merges``, by falling similarity: near-identical text blocked by an identifier or
  stage conflict, then pairs in [0.5, 0.8). They calibrate the threshold and the blocks.

Merge precision (``same_decision`` y among ``merge`` rows) is judged against the target
identity gate (0.97): a wrong merge makes edges point to the wrong decision.
"""

import argparse
import json
import random
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import text

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from experiments.graphrag.manifest import ARTIFACTS_DIR
from experiments.graphrag.resolution.audit import GHALII, write_sheet
from experiments.graphrag.resolution.decisions import TEXT_THRESHOLD
from experiments.graphrag.resolution.index import CorpusIndex, load_index

LOWEST = 3
BORDERLINE = 0.5
BANDS = ((0.97, "0.97+"), (0.9, "0.90-0.97"), (TEXT_THRESHOLD, "0.80-0.90"))
DECISION_AUDIT_COLUMNS = ("same_decision", "note")


def band(similarity: float) -> str:
    return next((label for floor, label in BANDS if similarity >= floor), "below")


def merged_pairs(
    pairs: Sequence[dict[str, Any]], decision_of: dict[str, str]
) -> list[dict[str, Any]]:
    """Pairs whose two text groups ended in one decision (complete link may split a
    passing pair, and then it is not a merge)."""
    return [
        p
        for p in pairs
        if p["first"] in decision_of and decision_of[p["first"]] == decision_of.get(p["second"])
    ]


def sample_merges(merges: Sequence[dict[str, Any]], size: int, seed: int) -> list[dict[str, Any]]:
    """The ``LOWEST`` lowest-similarity merges, then round-robin over court × band."""
    ordered = sorted(merges, key=lambda p: (p["similarity"], p["first"], p["second"]))
    sample = ordered[: min(LOWEST, size)]
    rng = random.Random(seed)
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pair in ordered[len(sample) :]:
        strata[f"{pair['court']}|{band(pair['similarity'])}"].append(pair)
    order = sorted(strata)
    rng.shuffle(order)
    for key in order:
        rng.shuffle(strata[key])
    while len(sample) < size and any(strata[k] for k in order):
        for key in order:
            if strata[key] and len(sample) < size:
                sample.append(strata[key].pop())
    return sample


def risky_non_merges(
    pairs: Sequence[dict[str, Any]], decision_of: dict[str, str], size: int
) -> list[dict[str, Any]]:
    """Kept-apart pairs with similarity of at least ``BORDERLINE``, by falling similarity."""
    merged = {(p["first"], p["second"]) for p in merged_pairs(pairs, decision_of)}
    risky = [
        p
        for p in pairs
        if (p["first"], p["second"]) not in merged and p["similarity"] >= BORDERLINE
    ]
    risky.sort(key=lambda p: (-p["similarity"], p["first"]))
    return risky[:size]


def _side(index: CorpusIndex, group: str) -> dict[str, str]:
    judgments = sorted(index.groups.get(group, []), key=lambda j: j.uri)
    return {
        "citations": " | ".join(j.citation for j in judgments),
        "links": " ".join(GHALII + j.uri for j in judgments),
        "identifiers": " ".join(sorted({k for j in judgments for k in index.identifiers[j.id]})),
        "stages": " ".join(sorted({s for j in judgments for s in index.stages[j.id]})),
    }


def audit_rows(
    index: CorpusIndex,
    sample: Sequence[tuple[str, dict[str, Any]]],
    copies: dict[str, int],
    decision_of: dict[str, str],
) -> list[dict[str, Any]]:
    rows = []
    for number, (kind, pair) in enumerate(sample, start=1):
        first, second = _side(index, pair["first"]), _side(index, pair["second"])
        decision = decision_of.get(pair["first"], "")
        rows.append(
            {
                "pair_id": number,
                "kind": kind,
                "court": pair["court"],
                "date": pair["date"],
                "similarity": pair["similarity"],
                "blocked_by": " ".join(pair["blocked_by"]),
                "decision_copies": copies.get(decision, 1) if kind == "merge" else "",
                **{f"first_{k}": v for k, v in first.items()},
                **{f"second_{k}": v for k, v in second.items()},
                "first_group": pair["first"],
                "second_group": pair["second"],
            }
        )
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.graphrag.resolution.decision_audit")
    parser.add_argument("--build", required=True)
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--merges", type=int, default=25)
    parser.add_argument("--non-merges", type=int, default=20)
    parser.add_argument("--seed", type=int, default=20261105)
    parser.add_argument(
        "--out", type=Path, help="the sheet's path (default decision_audit_<build>)"
    )
    args = parser.parse_args(argv)

    meta = json.loads((args.artifacts / f"mentions_{args.build}.meta.json").read_text())
    with (args.artifacts / meta["decision_pairs_file"]).open(encoding="utf-8") as handle:
        pairs = [json.loads(line) for line in handle]
    with (args.artifacts / meta["decisions_file"]).open(encoding="utf-8") as handle:
        decisions = [json.loads(line) for line in handle]
    decision_of = {c["text_group"]: d["decision"] for d in decisions for c in d["copies"]}
    copies = {d["decision"]: len(d["copies"]) for d in decisions}
    path = args.out or args.artifacts / f"decision_audit_{args.build}.csv"
    if path.exists():
        sys.stderr.write(f"{path} exists (it may be marked); pass another --out\n")
        return 1
    merges = sample_merges(merged_pairs(pairs, decision_of), args.merges, args.seed)
    others = risky_non_merges(pairs, decision_of, args.non_merges)
    engine = make_engine(get_settings())
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            index = load_index(conn)
    finally:
        engine.dispose()
    sample = [("merge", p) for p in merges] + [("non_merge", p) for p in others]
    write_sheet(path, audit_rows(index, sample, copies, decision_of), DECISION_AUDIT_COLUMNS)
    sys.stdout.write(f"wrote {path} ({len(merges)} merges + {len(others)} non-merges)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
