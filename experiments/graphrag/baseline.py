"""Phase 0: freeze the research baseline (docs/graphrag/AGENTS.md).

    poetry run python -m ejudgment.worker.evaluate        # once, if no current run exists
    poetry run python -m experiments.graphrag.baseline [--gold evals/gold.jsonl]

Writes ``runs/baseline_<date>.json``: the research manifest (code, corpus fingerprint,
settings, models), the gold-set state, and the metrics of the newest stored retrieval
evaluation that ran with *exactly the current configuration*: the same gold file, ranking
settings, embedding and reranker models, embedding template, and the same corpus *and*
vector fingerprint (judgments, chunks, embeddings, HNSW indexes, schema). If none does, it
lists what differs and stores nothing: graph experiments are only compared with a
baseline that reproduces the system as it is now.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Connection, text

from ejudgment.config import Settings, get_settings
from ejudgment.db import make_engine
from ejudgment.embeddings.base import EmbeddingProvider
from ejudgment.embeddings.template import TEMPLATE_VERSION
from ejudgment.evaluation.retrieval import RANKING_SETTINGS, corpus_version, load_gold
from ejudgment.ingestion.hashing import sha256_file
from experiments.graphrag.manifest import RUNS_DIR, research_manifest, write_json

# Keys of a retrieval evaluation's per-mode metrics that the baseline records.
METRICS = ("recall@20", "mrr@10", "passage_recall@20", "latency_p50_ms", "latency_p95_ms")
CANDIDATE_RUNS = 20


@dataclass(frozen=True)
class _ModelRef:
    """Just enough of an embedding provider for ``corpus_version`` to fingerprint the
    configured model's vectors, without loading the model."""

    model_id: str
    model_revision: str


def _normal(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def current_config(settings: Settings, gold_sha: str, corpus: dict[str, Any]) -> dict[str, Any]:
    """The parts of a retrieval evaluation's config that must match for it to be the baseline."""
    config: dict[str, Any] = _normal(
        {
            "gold_sha256": gold_sha,
            "settings": {name: getattr(settings, name) for name in RANKING_SETTINGS},
            "embedding_model": {
                "model_id": settings.embedding_model_id,
                "revision": settings.embedding_revision,
            },
            "reranker_model": {
                "model_id": settings.reranker_model_id,
                "revision": settings.reranker_revision,
            },
            "embedding_template_version": TEMPLATE_VERSION,
            "corpus": corpus,
        }
    )
    return config


def mismatches(run_config: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """What differs between a stored run's config and the current one (empty: it matches)."""
    found: list[str] = []
    for key, expected in current.items():
        stored = _normal(run_config.get(key))
        if key in ("embedding_model", "reranker_model"):
            # Runs also record dimension and token limits; the identity is id + revision.
            stored = {k: (stored or {}).get(k) for k in expected}
        if isinstance(expected, dict) and isinstance(stored, dict):
            found += [
                f"{key}.{k}"
                for k in sorted(set(expected) | set(stored))
                if expected.get(k) != stored.get(k)
            ]
        elif stored != expected:
            found.append(key)
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiments.graphrag.baseline")
    parser.add_argument("--gold", type=Path, default=Path("evals/gold.jsonl"))
    parser.add_argument("--out-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args(argv)

    settings = get_settings()
    questions = load_gold(args.gold)
    gold_sha = sha256_file(args.gold)
    engine = make_engine(settings)
    try:
        with engine.connect() as conn, conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            model = cast(
                EmbeddingProvider,
                _ModelRef(settings.embedding_model_id, settings.embedding_revision),
            )
            current = current_config(settings, gold_sha, corpus_version(conn, model))
            runs = _retrieval_runs(conn)
            manifest = research_manifest(
                conn,
                kind="graphrag_baseline",
                query_set_hash=gold_sha,
                baseline_config=current["settings"],
                notes="Phase 0: the default E-Judgment retrieval every graph experiment is "
                "compared with (exact lookup, lexical + dense, RRF, cross-encoder rerank, "
                "case grouping).",
            )
    finally:
        engine.dispose()
    run = next((r for r in runs if not mismatches(r.config, current)), None)
    if run is None:
        newest = runs[0] if runs else None
        detail = (
            f"newest run {newest.id} differs in: {', '.join(mismatches(newest.config, current))}"
            if newest
            else "there are no stored retrieval evaluations"
        )
        sys.stderr.write(
            "no stored retrieval evaluation matches the current configuration and corpus "
            f"({detail}); run\n  poetry run python -m ejudgment.worker.evaluate\nand try again\n"
        )
        return 1

    manifest["corpus_fingerprint"] = current["corpus"]  # including embeddings and indexes
    manifest["models"] = {
        "embedding": run.config.get("embedding_model"),
        "reranker": run.config.get("reranker_model"),
        "embedding_template_version": run.config.get("embedding_template_version"),
    }
    manifest["gold_set"] = {
        "file": str(args.gold),
        "sha256": gold_sha,
        "questions": len(questions),
        "reviewed": sum(q.reviewed for q in questions),
        "by_category": dict(sorted(Counter(q.category for q in questions).items())),
        "provisional": not all(q.reviewed for q in questions),
    }
    manifest["metrics"] = {
        "evaluation_run": run.id,
        "evaluated_at": run.created_at.isoformat(timespec="seconds"),
        "modes": {
            mode: {key: values.get(key) for key in METRICS}
            for mode, values in run.metrics.items()
            if isinstance(values, dict) and "recall@20" in values
        },
    }
    out = args.out_dir / f"baseline_{datetime.now(UTC):%Y-%m-%d}.json"
    write_json(out, manifest)
    sys.stdout.write(f"baseline: evaluation run {run.id} -> {out}\n")
    return 0


def _retrieval_runs(conn: Connection) -> list[Any]:
    """The newest retrieval evaluations (not answer or benchmark runs)."""
    return list(
        conn.execute(
            text(
                "SELECT id::text AS id, created_at, config, metrics FROM evaluation_runs "
                "WHERE config->>'kind' IS NULL AND config ? 'settings' "
                "ORDER BY created_at DESC LIMIT :n"
            ),
            {"n": CANDIDATE_RUNS},
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
