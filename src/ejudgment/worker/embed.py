"""Embed chunks with the configured local model (offline; weights from the HF cache).

python -m ejudgment.worker.embed [--limit N]
"""

import argparse
import json
import logging
import sys
from collections.abc import Sequence

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.embeddings.base import ModelUnavailable
from ejudgment.embeddings.sentence_transformers import SentenceTransformerProvider
from ejudgment.ingestion.embed_service import run_embedding
from ejudgment.ingestion.tokenizer import HfTokenizer, TokenizerUnavailable


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(prog="ejudgment.worker.embed", description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only the first N chunks")
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        tokenizer = HfTokenizer(settings.tokenizer_model_id, settings.tokenizer_revision)
        provider = SentenceTransformerProvider(settings)
    except (TokenizerUnavailable, ModelUnavailable) as exc:
        logging.error("%s", exc)
        return 2
    logging.info("Embedding with %s on %s", provider.model_id, provider.device)
    engine = make_engine(settings)
    try:
        report = run_embedding(engine, provider, tokenizer, limit=args.limit)
    finally:
        engine.dispose()
    json.dump({**report.as_dict(), "device": provider.device}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
