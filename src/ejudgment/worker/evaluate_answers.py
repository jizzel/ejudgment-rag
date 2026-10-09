"""Evaluate grounded answers against the gold set; store the run in ``evaluation_runs``.

python -m ejudgment.worker.evaluate_answers [--gold evals/gold.jsonl] [--model mistral-nemo:12b]
Needs Ollama running with the model. Model calls are logged in ``llm_usage_ledger`` under the
run id.
"""

import argparse
import asyncio
import json
import logging
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.embeddings.loading import load_nli, load_providers
from ejudgment.evaluation.answers import evaluate_answers, generation_config
from ejudgment.evaluation.retrieval import load_gold, run_config, store_run
from ejudgment.generation.base import LLMUnavailable
from ejudgment.generation.loading import make_llm
from ejudgment.generation.ollama_provider import OllamaProvider


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="ejudgment.worker.evaluate_answers", description=__doc__)
    parser.add_argument("--gold", type=Path, default=Path("evals/gold.jsonl"))
    parser.add_argument("--model", help="Ollama model (default: ollama_chat_model)")
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.model:
        settings = settings.model_copy(update={"ollama_chat_model": args.model})
    questions = load_gold(args.gold)
    embedder, reranker = load_providers(settings)
    llm = make_llm(settings)
    nli = load_nli(settings)
    if nli is None:
        sys.stderr.write("verifier_unavailable: run worker.models fetch-models\n")
        return 3
    engine = make_engine(settings)
    run_id = uuid.uuid4()
    try:
        described: dict[str, Any] = (
            asyncio.run(llm.describe()) if isinstance(llm, OllamaProvider) else {}
        )
        metrics, per_question = asyncio.run(
            evaluate_answers(
                engine,
                settings,
                questions,
                embedder=embedder,
                reranker=reranker,
                llm=llm,
                nli=nli,
                run_id=run_id,
            )
        )
        config = run_config(engine, settings, args.gold, questions, embedder, reranker)
        config.update(generation_config(settings, llm, nli, described))
        store_run(engine, config, metrics, per_question, run_id=run_id)
    except LLMUnavailable as exc:
        sys.stderr.write(f"llm_unavailable: {exc}\n")
        return 3
    finally:
        engine.dispose()
    label = "PROVISIONAL (unreviewed questions)" if config["provisional"] else "reviewed"
    sys.stdout.write(f"answer evaluation run {run_id} - {label}\n")
    json.dump({"llm": config["llm"], "metrics": metrics}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
