"""Edge provenance audit: every occurrence traced back to the database, read-only.

    poetry run python -m experiments.graphrag.graph.verify [--policy phase2-v1]

For each occurrence of each edge it checks that:

- the chunk exists, belongs to the citing judgment, and that judgment is eligible;
- the chunk text at the recorded offsets is exactly the recorded reference, and at the
  evidence offsets exactly the recorded evidence sentence;
- the source offsets equal the chunk's ``char_start`` plus the chunk offsets;
- every target judgment exists, is eligible, belongs to the edge's target case, and the
  citing judgment belongs to its source case;
- the occurrence's method is one the policy admits.

A graph that fails any check is not used (docs/graphrag/AGENTS.md, Phase 2 gate:
"provenance can be traced end to end").
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, bindparam, text

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from experiments.graphrag.graph.policy import POLICIES, AdmissionPolicy
from experiments.graphrag.manifest import ARTIFACTS_DIR

BATCH = 500


def _chunks(conn: Connection, ids: list[str]) -> dict[str, Any]:
    rows = conn.execute(
        text(
            "SELECT c.id::text AS id, c.judgment_id::text AS judgment_id, c.char_start, "
            "c.content, c.source_text_hash, j.eligibility_status "
            "FROM chunks c JOIN judgments j ON j.id = c.judgment_id "
            "WHERE c.id::text IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    )
    return {row.id: row for row in rows}


def _judgments(conn: Connection, ids: list[str]) -> dict[str, Any]:
    rows = conn.execute(
        text(
            "SELECT j.id::text AS id, j.eligibility_status, "
            "(SELECT min(source_text_hash) FROM chunks c WHERE c.judgment_id = j.id) AS grp "
            "FROM judgments j WHERE j.id::text IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids},
    )
    return {row.id: row for row in rows}


def verify_edges(
    conn: Connection, edges: Iterable[dict[str, Any]], policy: AdmissionPolicy
) -> dict[str, Any]:
    edges = list(edges)
    occurrences = [(e, o) for e in edges for o in e["occurrences"]]
    chunk_ids = sorted({o["chunk_id"] for _, o in occurrences})
    judgment_ids = sorted(
        {o["judgment_id"] for _, o in occurrences}
        | {t for _, o in occurrences for t in o["target_ids"]}
    )
    chunks: dict[str, Any] = {}
    for i in range(0, len(chunk_ids), BATCH):
        chunks.update(_chunks(conn, chunk_ids[i : i + BATCH]))
    judgments: dict[str, Any] = {}
    for i in range(0, len(judgment_ids), BATCH):
        judgments.update(_judgments(conn, judgment_ids[i : i + BATCH]))

    failures: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}

    def fail(check: str, occurrence: dict[str, Any]) -> None:
        failures[check] += 1
        examples.setdefault(check, [])
        if len(examples[check]) < 5:
            examples[check].append(f"{occurrence['chunk_id']}:{occurrence['start']}")

    for edge, occ in occurrences:
        chunk = chunks.get(occ["chunk_id"])
        if chunk is None:
            fail("chunk_missing", occ)
            continue
        if chunk.judgment_id != occ["judgment_id"]:
            fail("chunk_not_of_citing_judgment", occ)
        if chunk.eligibility_status != "eligible":
            fail("citing_judgment_not_eligible", occ)
        if chunk.source_text_hash != edge["source_case"]:
            fail("citing_judgment_not_in_source_case", occ)
        if chunk.content[occ["start"] : occ["end"]] != occ["text"]:
            fail("reference_text_differs", occ)
        if chunk.content[occ["evidence_start"] : occ["evidence_end"]] != occ["evidence"]:
            fail("evidence_text_differs", occ)
        if not occ["evidence_start"] <= occ["start"] <= occ["end"] <= occ["evidence_end"]:
            fail("evidence_does_not_contain_reference", occ)
        if chunk.char_start + occ["start"] != occ["source_start"]:
            fail("source_offset_differs", occ)
        if chunk.char_start + occ["end"] != occ["source_end"]:
            fail("source_end_offset_differs", occ)
        if occ["method"] not in policy.methods or occ["status"] not in policy.statuses:
            fail("not_admitted_by_policy", occ)
        if not occ["target_ids"]:
            fail("no_target", occ)
        for target in occ["target_ids"]:
            row = judgments.get(target)
            if row is None:
                fail("target_missing", occ)
            elif row.eligibility_status != "eligible":
                fail("target_not_eligible", occ)
            elif row.grp != edge["target_case"]:
                fail("target_not_in_target_case", occ)
    return {
        "edges": len(edges),
        "occurrences": len(occurrences),
        "failures": dict(failures),
        "examples": examples,
        "passed": not failures,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.graphrag.graph.verify")
    parser.add_argument("--policy", default="phase2-v1", choices=sorted(POLICIES))
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR)
    args = parser.parse_args(argv)
    policy = POLICIES[args.policy]
    with (args.artifacts / f"graph_{policy.name}_edges.jsonl").open() as handle:
        edges = [json.loads(line) for line in handle]
    engine = make_engine(get_settings())
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            report = verify_edges(conn, edges, policy)
    finally:
        engine.dispose()
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
