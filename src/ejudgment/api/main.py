"""FastAPI app. Run locally with ``poetry run uvicorn ejudgment.api.main:app``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from ejudgment.api.errors import install_error_handlers
from ejudgment.api.routes import chat, health, judgments, search
from ejudgment.config import Settings, get_settings
from ejudgment.db import make_engine
from ejudgment.embeddings.base import EmbeddingProvider, Reranker
from ejudgment.embeddings.loading import load_nli, load_providers
from ejudgment.generation.base import LLMProvider
from ejudgment.generation.loading import make_llm
from ejudgment.verification.entailment import EntailmentModel


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    *,
    embedder: EmbeddingProvider | None = None,
    reranker: Reranker | None = None,
    llm: LLMProvider | None = None,
    nli: EntailmentModel | None = None,
    load_models: bool = True,
) -> FastAPI:
    """Build the app. Tests pass their own settings, engine and (fake) providers; otherwise
    everything comes from config and the local model cache. Missing models degrade search
    to lexical/unreranked results, reported in ``query_info``; without an LLM or the NLI
    model that verifies answers, /v1/chat returns 503 (``llm_unavailable`` /
    ``verifier_unavailable``)."""
    resolved = settings or get_settings()
    owns_engine = engine is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = resolved
        app.state.engine = engine if engine is not None else make_engine(resolved)
        loaded_embedder, loaded_reranker = embedder, reranker
        if load_models and embedder is None and reranker is None:
            loaded_embedder, loaded_reranker = load_providers(resolved)
        app.state.embedder = loaded_embedder
        app.state.reranker = loaded_reranker
        app.state.llm = llm if llm is not None or not load_models else make_llm(resolved)
        app.state.nli = nli if nli is not None or not load_models else load_nli(resolved)
        yield
        if owns_engine:
            app.state.engine.dispose()

    app = FastAPI(
        title="E-Judgment legal research API",
        description=(
            "Source-grounded search and answers over Ghanaian judgments from GhaLII "
            "(CC BY-NC 4.0). "
            "Assisted legal research, not legal advice."
        ),
        version="0.4.0",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(judgments.router)
    app.include_router(search.router)
    app.include_router(chat.router)
    return app


app = create_app()
