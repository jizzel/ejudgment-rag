"""Model asset setup. Downloads happen only here, explicitly, never during imports or tests.

python -m ejudgment.worker.models fetch-tokenizer
"""

import argparse
import logging
from collections.abc import Sequence

from ejudgment.config import get_settings
from ejudgment.ingestion.tokenizer import TOKENIZER_FILE, HfTokenizer


def fetch_tokenizer() -> str:
    from huggingface_hub import hf_hub_download

    settings = get_settings()
    path = hf_hub_download(
        settings.tokenizer_model_id, TOKENIZER_FILE, revision=settings.tokenizer_revision
    )
    HfTokenizer(settings.tokenizer_model_id, settings.tokenizer_revision)  # loads offline
    return path


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="ejudgment.worker.models", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch-tokenizer", help="Download the pinned tokenizer to the HF cache")
    args = parser.parse_args(argv)
    if args.command == "fetch-tokenizer":
        logging.info("Tokenizer cached at %s", fetch_tokenizer())
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
