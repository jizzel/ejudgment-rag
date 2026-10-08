"""Token counting for chunk budgets.

Chunks are measured with the embedding model's own tokenizer (AGENTS.md), loaded from the
local Hugging Face cache only; ``python -m ejudgment.worker.models fetch-tokenizer`` puts it
there once. Tests use :class:`WhitespaceTokenizer`, which needs no download.
"""

import re
from collections.abc import Sequence
from typing import Protocol

from tokenizers import Tokenizer as _HfTokenizer

TOKENIZER_FILE = "tokenizer.json"


class TokenizerUnavailable(Exception):
    """The tokenizer is not in the local cache; fetch it first."""


class Tokenizer(Protocol):
    @property
    def name(self) -> str: ...

    def count(self, texts: Sequence[str]) -> list[int]:
        """Token count of each text, without special tokens."""
        ...

    def offsets(self, text: str) -> list[tuple[int, int]]:
        """Character span of every token in ``text``."""
        ...


class HfTokenizer:
    def __init__(self, model_id: str, revision: str) -> None:
        from huggingface_hub import hf_hub_download
        from huggingface_hub.errors import LocalEntryNotFoundError

        try:
            path = hf_hub_download(
                model_id, TOKENIZER_FILE, revision=revision, local_files_only=True
            )
        except LocalEntryNotFoundError as exc:
            raise TokenizerUnavailable(
                f"{model_id}@{revision} tokenizer is not cached. Run: "
                "poetry run python -m ejudgment.worker.models fetch-tokenizer"
            ) from exc
        self._tokenizer = _HfTokenizer.from_file(path)
        self._tokenizer.no_truncation()
        self._tokenizer.no_padding()
        self._name = f"{model_id}@{revision[:12]}"

    @property
    def name(self) -> str:
        return self._name

    def count(self, texts: Sequence[str]) -> list[int]:
        if not texts:
            return []
        encodings = self._tokenizer.encode_batch(list(texts), add_special_tokens=False)
        return [len(encoding.ids) for encoding in encodings]

    def offsets(self, text: str) -> list[tuple[int, int]]:
        encoding = self._tokenizer.encode(text, add_special_tokens=False)
        return [(start, end) for start, end in encoding.offsets]


_WORD = re.compile(r"\S+")


class WhitespaceTokenizer:
    """Deterministic stand-in for tests: one token per whitespace-separated word."""

    name = "whitespace"

    def count(self, texts: Sequence[str]) -> list[int]:
        return [len(_WORD.findall(text)) for text in texts]

    def offsets(self, text: str) -> list[tuple[int, int]]:
        return [match.span() for match in _WORD.finditer(text)]
