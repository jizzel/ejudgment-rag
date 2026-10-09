"""Ask a question and get a grounded answer (prints the /v1/chat JSON shape).

python -m ejudgment.worker.ask "When is a landlord entitled to recover possession?" --court ghasc
Needs Ollama running with the configured model (``ollama_chat_model``; ``--model`` overrides).
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.domain.schemas import ChatRequest, SearchFilters
from ejudgment.embeddings.loading import load_nli, load_providers
from ejudgment.generation.base import LLMUnavailable
from ejudgment.generation.chat import answer_question
from ejudgment.generation.loading import make_llm


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ejudgment.worker.ask", description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--court")
    parser.add_argument("--jurisdiction")
    parser.add_argument("--year-from", type=int)
    parser.add_argument("--year-to", type=int)
    parser.add_argument("--judge")
    parser.add_argument("--model", help="Ollama model (default: ollama_chat_model)")
    args = parser.parse_args(argv)
    try:
        request = ChatRequest(
            question=args.question,
            filters=SearchFilters(
                court=args.court,
                jurisdiction=args.jurisdiction,
                year_from=args.year_from,
                year_to=args.year_to,
                judge=args.judge,
            ),
        )
    except ValidationError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    settings = get_settings()
    embedder, reranker = load_providers(settings)
    llm = make_llm(settings, model=args.model)
    nli = load_nli(settings)
    if nli is None:
        sys.stderr.write("verifier_unavailable: run worker.models fetch-models\n")
        return 3
    engine = make_engine(settings)
    try:
        response = asyncio.run(
            answer_question(
                engine,
                request,
                settings,
                embedder=embedder,
                reranker=reranker,
                llm=llm,
                nli=nli,
                endpoint="cli/ask",
            )
        )
    except LLMUnavailable as exc:
        sys.stderr.write(f"llm_unavailable: {exc}\n")
        return 3
    finally:
        engine.dispose()
    sys.stdout.write(response.model_dump_json(indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
