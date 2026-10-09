"""Model asset setup. Downloads happen only here, explicitly, never during imports or tests.

python -m ejudgment.worker.models fetch-tokenizer   # chunking tokenizer only (small)
python -m ejudgment.worker.models fetch-models      # tokenizer + embedding model + reranker
"""

import argparse
import logging
from collections.abc import Sequence

from ejudgment.config import get_settings
from ejudgment.ingestion.tokenizer import TOKENIZER_FILE, HfTokenizer

# Only what sentence-transformers needs; skips ONNX/OpenVINO/TF/Flax exports.
_MODEL_FILES = ["*.json", "*.txt", "*.safetensors", "*.model", "1_Pooling/*", "README.md"]


def fetch_tokenizer() -> str:
    from huggingface_hub import hf_hub_download

    settings = get_settings()
    path = hf_hub_download(
        settings.tokenizer_model_id, TOKENIZER_FILE, revision=settings.tokenizer_revision
    )
    HfTokenizer(settings.tokenizer_model_id, settings.tokenizer_revision)  # loads offline
    return path


def fetch_models() -> list[str]:
    from huggingface_hub import snapshot_download

    settings = get_settings()
    paths = [fetch_tokenizer()]
    for model_id, revision in (
        (settings.embedding_model_id, settings.embedding_revision),
        (settings.reranker_model_id, settings.reranker_revision),
    ):
        paths.append(snapshot_download(model_id, revision=revision, allow_patterns=_MODEL_FILES))
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="ejudgment.worker.models", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch-tokenizer", help="Download the pinned tokenizer to the HF cache")
    commands.add_parser("fetch-models", help="Download tokenizer, embedding model and reranker")
    args = parser.parse_args(argv)
    if args.command == "fetch-tokenizer":
        logging.info("Tokenizer cached at %s", fetch_tokenizer())
    else:
        for path in fetch_models():
            logging.info("Cached %s", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
