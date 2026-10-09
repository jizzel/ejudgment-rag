"""Load the configured local models, or report why they are unavailable."""

import logging

from ejudgment.config import Settings
from ejudgment.embeddings.base import EmbeddingProvider, ModelUnavailable, Reranker
from ejudgment.verification.entailment import EntailmentModel

logger = logging.getLogger(__name__)


def load_providers(settings: Settings) -> tuple[EmbeddingProvider | None, Reranker | None]:
    """Both providers, or ``None`` for any whose weights are not cached (search then
    degrades visibly: ``query_info.degraded``)."""
    from ejudgment.embeddings.sentence_transformers import SentenceTransformerProvider
    from ejudgment.retrieval.rerank import CrossEncoderReranker

    embedder: EmbeddingProvider | None = None
    reranker: Reranker | None = None
    try:
        embedder = SentenceTransformerProvider(settings)
    except ModelUnavailable as exc:
        logger.warning("Dense retrieval disabled: %s", exc)
    try:
        reranker = CrossEncoderReranker(settings)
    except ModelUnavailable as exc:
        logger.warning("Reranking disabled: %s", exc)
    return embedder, reranker


def load_nli(settings: Settings) -> EntailmentModel | None:
    """The proposition-support model, or ``None`` (then /v1/chat refuses to answer)."""
    from ejudgment.verification.entailment import CrossEncoderNli

    try:
        return CrossEncoderNli(settings)
    except ModelUnavailable as exc:
        logger.warning("Answer verification disabled: %s", exc)
        return None
