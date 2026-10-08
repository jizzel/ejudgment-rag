"""FastAPI app. Run locally with ``poetry run uvicorn ejudgment.api.main:app``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from ejudgment.api.errors import install_error_handlers
from ejudgment.api.routes import health, judgments, search
from ejudgment.config import Settings, get_settings
from ejudgment.db import make_engine
from ejudgment.embeddings.base import EmbeddingProvider, Reranker
from ejudgment.embeddings.loading import load_providers


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    *,
    embedder: EmbeddingProvider | None = None,
    reranker: Reranker | None = None,
    load_models: bool = True,
) -> FastAPI:
    """Build the app. Tests pass their own settings, engine and (fake) providers; otherwise
    everything comes from config and the local model cache. Missing models degrade search
    to lexical/unreranked results, reported in ``query_info``."""
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
        yield
        if owns_engine:
            app.state.engine.dispose()

    app = FastAPI(
        title="E-Judgment legal research API",
        description=(
            "Source-grounded search over Ghanaian judgments from GhaLII (CC BY-NC 4.0). "
            "Assisted legal research, not legal advice."
        ),
        version="0.3.0",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(judgments.router)
    app.include_router(search.router)
    return app


app = create_app()
