"""Cross-encoder reranking of the top fused passages."""

from collections.abc import Sequence

from ejudgment.config import Settings
from ejudgment.embeddings.base import ModelUnavailable, resolve_device


class CrossEncoderReranker:
    def __init__(self, settings: Settings) -> None:
        from sentence_transformers import CrossEncoder

        self.device = resolve_device(settings.model_device)
        try:
            self._model = CrossEncoder(
                settings.reranker_model_id,
                revision=settings.reranker_revision,
                device=self.device,
                local_files_only=True,
                max_length=settings.reranker_max_input_tokens,
            )
        except OSError as exc:
            raise ModelUnavailable(
                f"{settings.reranker_model_id}@{settings.reranker_revision} is not cached; "
                "run: poetry run python -m ejudgment.worker.models fetch-models"
            ) from exc
        self._max_tokens = settings.reranker_max_input_tokens

    @property
    def max_input_tokens(self) -> int:
        return self._max_tokens

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        scores = self._model.predict(
            [(query, passage) for passage in passages], show_progress_bar=False
        )
        return [float(score) for score in scores]
