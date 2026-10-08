"""Chunk eligible judgments (offline, no network).

python -m ejudgment.worker.chunk [--limit N] [--judgment-uri URI]
"""

import argparse
import json
import logging
import sys
from collections.abc import Sequence

from ejudgment.config import get_settings
from ejudgment.db import make_engine
from ejudgment.ingestion.chunk_service import run_chunking
from ejudgment.ingestion.tokenizer import HfTokenizer, TokenizerUnavailable


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(prog="ejudgment.worker.chunk", description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only the first N judgments")
    parser.add_argument("--judgment-uri", default=None, help="Only this canonical AKN URI")
    args = parser.parse_args(argv)

    settings = get_settings()
    try:
        tokenizer = HfTokenizer(settings.tokenizer_model_id, settings.tokenizer_revision)
    except TokenizerUnavailable as exc:
        logging.error("%s", exc)
        return 2
    engine = make_engine(settings)
    try:
        report = run_chunking(
            engine, tokenizer, settings, limit=args.limit, judgment_uri=args.judgment_uri
        )
    finally:
        engine.dispose()
    json.dump(report.as_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
