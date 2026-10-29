"""Research-log manifest (docs/graphrag/AGENTS.md, "Research log: required fields").

Every run records enough to reproduce it: code, corpus, extractor/resolver versions, query
set and configuration. Results without a manifest are not used in claims.
"""

import hashlib
import json
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection

from ejudgment.embeddings.base import EmbeddingProvider
from ejudgment.evaluation.retrieval import corpus_version

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = Path(__file__).resolve().parent / "runs"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"


def git_state(root: Path = REPO_ROOT) -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()

    return {
        "git_sha": git("rev-parse", "HEAD"),
        "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        # Uncommitted changes, including new files not yet added, mean the SHA alone does
        # not reproduce the run. Ignored files (the corpus-derived artifacts) don't count.
        "git_dirty": bool(git("status", "--porcelain")),
    }


def build_id(
    versions: dict[str, str], corpus: dict[str, Any], config: dict[str, Any] | None = None
) -> str:
    """Short, stable id of a graph build: extractor/resolver versions, corpus digests and the
    run's configuration (a ``--limit`` profile must not share the full profile's id)."""
    payload = json.dumps(
        {
            "versions": versions,
            "judgments": corpus.get("judgments_digest"),
            "chunks": corpus.get("chunks_digest"),
            "config": config or {},
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def research_manifest(
    conn: Connection,
    *,
    kind: str,
    versions: dict[str, str] | None = None,
    query_set_hash: str | None = None,
    baseline_config: dict[str, Any] | None = None,
    graph_config: dict[str, Any] | None = None,
    models: dict[str, Any] | None = None,
    notes: str = "",
    embedder: EmbeddingProvider | None = None,
) -> dict[str, Any]:
    # With the embedder that served the run, the fingerprint also covers its vectors
    # (count, input digest, template versions): a re-embedding changes the record.
    corpus = corpus_version(conn, embedder)
    versions = versions or {}
    return {
        "run_id": str(uuid.uuid4()),
        "kind": kind,
        **git_state(),
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "corpus_fingerprint": corpus,
        "graph_build_id": build_id(versions, corpus, graph_config) if versions else None,
        "mention_extractor_versions": {k: v for k, v in versions.items() if k != "resolver"},
        "resolver_versions": {k: v for k, v in versions.items() if k == "resolver"},
        "rdf_schema_version": None,
        "query_set_hash": query_set_hash,
        "baseline_config": baseline_config,
        "graph_config": graph_config,
        "models": models or {},
        "metrics": {},
        "notes": notes,
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
