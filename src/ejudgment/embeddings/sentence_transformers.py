"""Local sentence-transformers embeddings (default provider)."""

from collections.abc import Sequence

from ejudgment.config import Settings
from ejudgment.embeddings.base import ModelUnavailable, resolve_device


class SentenceTransformerProvider:
    def __init__(self, settings: Settings) -> None:
        from sentence_transformers import SentenceTransformer

        self.device = resolve_device(settings.model_device)
        try:
            self._model = SentenceTransformer(
                settings.embedding_model_id,
                revision=settings.embedding_revision,
                device=self.device,
                local_files_only=True,
            )
        except OSError as exc:
            raise ModelUnavailable(
                f"{settings.embedding_model_id}@{settings.embedding_revision} is not cached; "
                "run: poetry run python -m ejudgment.worker.models fetch-models"
            ) from exc
        self._model.max_seq_length = settings.embedding_max_input_tokens
        dimension = self._model.get_embedding_dimension()
        if dimension != settings.embedding_dimension:
            raise ValueError(
                f"{settings.embedding_model_id} has dimension {dimension}, "
                f"configured {settings.embedding_dimension}"
            )
        self._model_id = settings.embedding_model_id
        self._revision = settings.embedding_revision
        self._dimension = dimension
        self._max_tokens = settings.embedding_max_input_tokens
        self._instruction = settings.embedding_query_instruction
        self._batch_size = settings.embedding_batch_size

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def model_revision(self) -> str:
        return self._revision

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def max_input_tokens(self) -> int:
        return self._max_tokens

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(x) for x in row] for row in vectors]

    def embed_query(self, text: str) -> list[float]:
        # BGE retrieval queries carry an instruction prefix; documents do not.
        return self.embed_documents([f"{self._instruction}{text}"])[0]
