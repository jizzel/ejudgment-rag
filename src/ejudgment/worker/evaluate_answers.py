"""Evaluate grounded answers against the gold set; store the run in ``evaluation_runs``.

python -m ejudgment.worker.evaluate_answers [--gold FILE] [--provider openai] [--model M]
Ollama (default) needs the model running locally. OpenAI needs OPENAI_ENABLED=true and
OPENAI_API_KEY; the run stops early, keeping what it has, once the next call would exceed
openai_max_calls_per_run or openai_test_budget_usd. Model calls are logged in
``llm_usage_ledger`` under the run id.
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


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="ejudgment.worker.evaluate_answers", description=__doc__)
    parser.add_argument("--gold", type=Path, default=Path("evals/gold.jsonl"))
    parser.add_argument("--provider", choices=["ollama", "openai"], help="default: llm_provider")
    parser.add_argument("--model", help="model of the provider (default: from settings)")
    args = parser.parse_args(argv)

    settings = get_settings()
    provider = args.provider or settings.llm_provider
    if args.model:
        key = "openai_chat_model" if provider == "openai" else "ollama_chat_model"
        settings = settings.model_copy(update={key: args.model})
    settings = settings.model_copy(update={"llm_provider": provider})
    questions = load_gold(args.gold)
    try:
        llm = make_llm(settings)
    except LLMUnavailable as exc:
        sys.stderr.write(f"llm_unavailable: {exc}\n")
        return 3
    embedder, reranker = load_providers(settings)
    nli = load_nli(settings)
    if nli is None:
        sys.stderr.write("verifier_unavailable: run worker.models fetch-models\n")
        return 3
    engine = make_engine(settings)
    run_id = uuid.uuid4()
    try:
        describe = getattr(llm, "describe", None)
        described: dict[str, Any] = asyncio.run(describe()) if describe else {}
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
    if "budget_stopped" in metrics:
        sys.stdout.write(f"stopped early by the budget: {metrics['budget_stopped']['message']}\n")
    json.dump({"llm": config["llm"], "metrics": metrics}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
