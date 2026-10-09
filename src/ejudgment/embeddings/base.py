"""Provider protocols (AGENTS.md). Implementations load weights from the local cache only."""

from collections.abc import Sequence
from typing import Protocol


class ModelUnavailable(Exception):
    """Model weights are not in the local cache; run ``worker.models fetch-models``."""


class EmbeddingProvider(Protocol):
    @property
    def model_id(self) -> str: ...
    @property
    def model_revision(self) -> str: ...
    @property
    def dimension(self) -> int: ...
    @property
    def max_input_tokens(self) -> int: ...
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    @property
    def model_id(self) -> str: ...
    @property
    def model_revision(self) -> str: ...
    @property
    def max_input_tokens(self) -> int: ...
    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


def resolve_device(device: str) -> str:
    if device != "auto":
        return device
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
