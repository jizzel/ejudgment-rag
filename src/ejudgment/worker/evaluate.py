"""Evaluate retrieval against the gold set and store the run in ``evaluation_runs``.

python -m ejudgment.worker.evaluate [--gold evals/gold.jsonl]
"""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.embeddings.loading import load_providers
from ejudgment.evaluation.retrieval import evaluate, load_gold, run_config, store_run


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="ejudgment.worker.evaluate", description=__doc__)
    parser.add_argument("--gold", type=Path, default=Path("evals/gold.jsonl"))
    args = parser.parse_args(argv)

    settings = get_settings()
    questions = load_gold(args.gold)
    embedder, reranker = load_providers(settings)
    engine = make_engine(settings)
    try:
        metrics, per_question = evaluate(
            engine, settings, questions, embedder=embedder, reranker=reranker
        )
        # Fingerprinting scans whole tables (~10 s on the real corpus); doing it after the
        # timed queries keeps it from evicting their working set from the buffer cache.
        config = run_config(engine, settings, args.gold, questions, embedder, reranker)
        run_id = store_run(engine, config, metrics, per_question)
    finally:
        engine.dispose()
    label = "PROVISIONAL (unreviewed questions)" if config["provisional"] else "reviewed"
    sys.stdout.write(f"evaluation run {run_id} - {label}\n")
    json.dump({"config": config, "metrics": metrics}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
