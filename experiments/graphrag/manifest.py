"""Research-log manifest (docs/graphrag/AGENTS.md, "Research log: required fields").

Every run records enough to reproduce it: code, corpus, extractor/resolver versions, query
set and configuration. Results without a manifest are not used in claims.
"""

import hashlib
import json
import subprocess
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection

from ejudgment.embeddings.base import EmbeddingProvider
from ejudgment.evaluation.retrieval import corpus_version

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = Path(__file__).resolve().parent / "runs"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"


PATCH_DIR = RUNS_DIR / "patches"
# Where patches go instead, when set (the test suite points it at a temporary directory so
# that no test writes into the repository).
PATCH_DIR_OVERRIDE: Path | None = None


def _working_patch(git: Callable[..., str], root: Path, skip: str) -> str:
    """The uncommitted code: ``git diff HEAD`` plus every untracked, non-ignored file as an
    addition (``git diff --no-index``, which exits 1 when files differ). Read-only."""
    parts = [git("diff", "HEAD", "--binary")]
    untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
    for path in sorted(untracked):
        if path.startswith(skip):
            continue
        result = subprocess.run(
            ["git", "diff", "--no-index", "--binary", "/dev/null", path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        parts.append(result.stdout.strip())
    return "\n".join(p for p in parts if p) + "\n"


def git_state(root: Path = REPO_ROOT, patch_dir: Path | None = None) -> dict[str, Any]:
    """The code a run came from. On a dirty tree the SHA alone does not reproduce it, so the
    uncommitted patch is hashed and kept as ``runs/patches/<sha256[:16]>.patch`` (code only:
    corpus-derived artifacts are gitignored and never part of it); ``git apply`` on the
    recorded SHA restores the exact tree."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True
        ).stdout.strip()

    patch_dir = patch_dir or PATCH_DIR_OVERRIDE or root / PATCH_DIR.relative_to(REPO_ROOT)
    dirty = bool(git("status", "--porcelain"))
    state: dict[str, Any] = {
        "git_sha": git("rev-parse", "HEAD"),
        "git_branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        # Uncommitted changes, including new files not yet added, mean the SHA alone does
        # not reproduce the run. Ignored files (the corpus-derived artifacts) don't count.
        "git_dirty": dirty,
    }
    if dirty:
        skip = str(patch_dir.relative_to(root)) if patch_dir.is_relative_to(root) else "\0"
        patch = _working_patch(git, root, skip)
        digest = hashlib.sha256(patch.encode()).hexdigest()
        patch_dir.mkdir(parents=True, exist_ok=True)
        path = patch_dir / f"{digest[:16]}.patch"
        if not path.exists():
            path.write_text(patch, encoding="utf-8")
        state["git_patch_sha256"] = digest
        state["git_patch_file"] = str(path.relative_to(root) if path.is_relative_to(root) else path)
    return state


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
    patch_dir: Path | None = None,
) -> dict[str, Any]:
    # With the embedder that served the run, the fingerprint also covers its vectors
    # (count, input digest, template versions): a re-embedding changes the record.
    corpus = corpus_version(conn, embedder)
    versions = versions or {}
    return {
        "run_id": str(uuid.uuid4()),
        "kind": kind,
        **git_state(patch_dir=patch_dir),
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
