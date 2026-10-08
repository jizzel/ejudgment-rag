"""Deterministic, download-free providers for tests.

The fake embedder hashes words (and simple synonyms) into a fixed-size bag-of-words vector,
so texts sharing vocabulary are close. The fake reranker scores by query-word overlap.
"""

import hashlib
import math
import re
from collections.abc import Sequence

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class FakeEmbeddingProvider:
    model_id = "fake/hashed-bow"
    model_revision = "v1"
    max_input_tokens = 512

    def __init__(self, dimension: int = 384, synonyms: dict[str, str] | None = None) -> None:
        self.dimension = dimension
        # Lets tests model "semantic" matches lexical search cannot see, e.g. tenancy ~ lease.
        self._synonyms = synonyms or {}

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for word in _words(text):
            word = self._synonyms.get(word, word)
            bucket = int(hashlib.sha256(word.encode()).hexdigest(), 16) % self.dimension
            vector[bucket] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class FakeReranker:
    max_input_tokens = 512

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        wanted = set(_words(query))
        return [
            len(wanted & set(_words(passage))) / (1 + len(_words(passage)) ** 0.5)
            for passage in passages
        ]
