"""Phase 2: the deterministic, provenance-preserving citation graph.

    poetry run python -m experiments.graphrag.graph.build [--policy phase2-v1]

**Semantics.** An edge ``A --CITES--> B`` means: a passage of a judgment in case A contains
a case reference that the resolver linked to a judgment in case B, with the recorded
method and status. It does not mean that A followed, applied or approved B, relied on it,
or that B is still good law (docs/graphrag/AGENTS.md, Phase 2). ``CITED_BY`` is the same
edge read backwards and is not stored twice.

**Nodes** are cases: re-publications of one judgment (same ``source_text_hash``) are one
case, as in search, and each node lists its judgments with their AKN URIs. Every eligible
case is a node, so isolated cases count in the statistics.

**Edges** keep every *occurrence* that supports them: citing judgment, chunk, offsets of
the reference and of its evidence sentence, extraction method and OCR flag, resolution
method, tier and status, the matched target judgments and the decision signals. Only
references the admission policy admits become occurrences; temporal conflicts among the
admitted methods are kept apart as review items, never as edges.

Outputs: ``artifacts/graph_<policy>_{nodes,edges}.jsonl`` (edges quote the corpus:
gitignored), ``artifacts/graph_<policy>.ttl`` (RDF, no corpus text; ``graph.rdf``) and
``runs/graph_<policy>.json`` / ``.md`` (statistics, committable).
"""

import argparse
import hashlib
import json
import sys
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.evaluation.retrieval import corpus_version
from experiments.graphrag.graph.policy import POLICIES, AdmissionPolicy
from experiments.graphrag.graph.rdf import RDF_SCHEMA_VERSION, write_turtle
from experiments.graphrag.graph.stats import graph_statistics, markdown
from experiments.graphrag.manifest import ARTIFACTS_DIR, RUNS_DIR, git_state, write_json
from experiments.graphrag.resolution.index import CorpusIndex, load_index

VERSION = "graph-builder-v1"
RELATION = "CITES"

# Fields of a profiled reference kept on an occurrence (provenance, AGENTS.md rule 2).
_OCCURRENCE_FIELDS = (
    "chunk_id",
    "judgment_id",
    "uri",
    "court",
    "date",
    "start",
    "end",
    "source_start",
    "source_end",
    "evidence_start",
    "evidence_end",
    "text",
    "evidence",
    "kind",
    "method",
    "tier",
    "status",
    "reason",
    "candidates",
    "name_agrees",
    "identifiers",
    "stages",
    "decision_date",
    "source_method",
    "ocr",
    "ocr_confidence",
    "page_reference_status",
    "target_ids",
    "target_uris",
    "target_date",
)


@dataclass
class Graph:
    policy: AdmissionPolicy
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    review: list[dict[str, Any]] = field(default_factory=list)

    def outgoing(self) -> dict[str, set[str]]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for source, target in self.edges:
            adjacency[source].add(target)
        return adjacency

    def incoming(self) -> dict[str, set[str]]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for source, target in self.edges:
            adjacency[target].add(source)
        return adjacency

    def fingerprint(self) -> str:
        """SHA-256 over the policy, every node and every edge with its occurrence keys."""
        digest = hashlib.sha256()
        digest.update(json.dumps(self.policy.describe(), sort_keys=True).encode())
        for case in sorted(self.nodes):
            ids = sorted(j["id"] for j in self.nodes[case]["judgments"])
            digest.update(json.dumps(["node", case, ids]).encode())
        for (source, target), occurrences in sorted(self.edges.items()):
            keys = sorted(
                (o["chunk_id"], o["start"], o["end"], o["method"], sorted(o["target_ids"]))
                for o in occurrences
            )
            digest.update(json.dumps(["edge", source, target, keys]).encode())
        return digest.hexdigest()


def occurrence(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in _OCCURRENCE_FIELDS}


def build_graph(
    records: Iterable[dict[str, Any]], index: CorpusIndex, policy: AdmissionPolicy
) -> Graph:
    graph = Graph(policy)
    for group, judgments in index.groups.items():
        graph.nodes[group] = {
            "case": group,
            "judgments": [
                {
                    "id": j.id,
                    "uri": j.uri,
                    "citation": j.citation,
                    "court": j.court,
                    "date": j.date.isoformat() if j.date else None,
                }
                for j in sorted(judgments, key=lambda j: j.uri)
            ],
        }
    edges: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["method"] not in policy.methods:
            continue
        if policy.admits(record):
            edges[(record["group"], record["target_group"])].append(occurrence(record))
        elif record["status"] == "temporal_conflict":
            graph.review.append(occurrence(record))
    for key in sorted(edges):
        graph.edges[key] = sorted(edges[key], key=lambda o: (o["chunk_id"], o["start"]))
    return graph


def edge_rows(graph: Graph) -> list[dict[str, Any]]:
    rows = []
    for (source, target), occurrences in graph.edges.items():
        rows.append(
            {
                "relation": RELATION,
                "source_case": source,
                "target_case": target,
                "occurrences": occurrences,
                "methods": sorted({o["method"] for o in occurrences}),
                "tiers": sorted({o["tier"] for o in occurrences if o["tier"]}),
            }
        )
    return rows


# Corpus fingerprint fields that must be unchanged since the audited profile was made.
CORPUS_KEYS = ("eligible_judgments", "judgments_digest", "chunks", "chunks_digest")


def corpus_mismatches(stored: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Fingerprint fields that differ between the audited profile's corpus and the live one.

    The graph's nodes come from the live database and its edges from the profile, so both
    must describe the same corpus snapshot."""
    return [key for key in CORPUS_KEYS if stored.get(key) != current.get(key)]


def graph_manifest(
    profile: dict[str, Any],
    policy: AdmissionPolicy,
    fingerprint: str,
    stats: dict[str, Any],
    *,
    git: dict[str, Any],
) -> dict[str, Any]:
    """A manifest of its own for this graph build: its own run id and time, the RDF schema
    version, and the profile it came from, kept apart."""
    inherited = ("corpus_fingerprint", "mention_extractor_versions", "resolver_versions")
    return {
        "run_id": str(uuid.uuid4()),
        "kind": "graphrag_graph",
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        **git,
        **{key: profile.get(key) for key in inherited},
        "graph_builder_version": VERSION,
        "rdf_schema_version": RDF_SCHEMA_VERSION,
        "policy": policy.describe(),
        "graph_fingerprint": fingerprint,
        "graph_build_id": profile.get("graph_build_id"),
        "profile_run_id": profile.get("run_id"),
        "profile_timestamp": profile.get("timestamp"),
        "profile_git_sha": profile.get("git_sha"),
        "metrics": {"graph": stats},
    }


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.graphrag.graph.build")
    parser.add_argument("--policy", default="phase2-v1", choices=sorted(POLICIES))
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--out-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args(argv)
    policy = POLICIES[args.policy]

    meta_path = args.artifacts / f"mentions_{policy.source_build}.meta.json"
    if not meta_path.exists():
        sys.stderr.write(f"{meta_path} is missing: the policy was audited on that build\n")
        return 1
    meta = json.loads(meta_path.read_text())
    if meta["manifest"]["graph_build_id"] != policy.source_build:
        sys.stderr.write("the profile's build id does not match the policy's audited build\n")
        return 1
    engine = make_engine(get_settings())
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            differ = corpus_mismatches(
                meta["manifest"]["corpus_fingerprint"], corpus_version(conn, None)
            )
            if differ:
                sys.stderr.write(
                    "the corpus has changed since the audited profile was made "
                    f"({', '.join(differ)}); refusing to build\n"
                )
                return 1
            index = load_index(conn)
    finally:
        engine.dispose()
    with (args.artifacts / meta["mentions_file"]).open() as handle:
        graph = build_graph((json.loads(line) for line in handle), index, policy)

    fingerprint = graph.fingerprint()
    stem = f"graph_{policy.name}"
    write_jsonl(args.artifacts / f"{stem}_nodes.jsonl", graph.nodes.values())
    write_jsonl(args.artifacts / f"{stem}_edges.jsonl", edge_rows(graph))
    write_jsonl(args.artifacts / f"{stem}_review.jsonl", graph.review)
    write_turtle(args.artifacts / f"{stem}.ttl", graph, fingerprint, meta["manifest"])
    stats = graph_statistics(graph)
    manifest = graph_manifest(meta["manifest"], policy, fingerprint, stats, git=git_state())
    write_json(args.out_dir / f"{stem}.json", manifest)
    (args.out_dir / f"{stem}.md").write_text(markdown(stats, manifest))
    sys.stdout.write(
        f"{policy.name}: {stats['nodes']['cases']:,} cases, {stats['edges']['edges']:,} edges "
        f"from {stats['edges']['occurrences']:,} occurrences; fingerprint {fingerprint[:16]}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
