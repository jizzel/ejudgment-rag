"""Request-scoped dependencies. The app owns one engine; tests inject their own."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from ejudgment.auth.service import UNAUTHENTICATED, AuthError, AuthUser, resolve_session
from ejudgment.config import Settings
from ejudgment.embeddings.base import EmbeddingProvider, Reranker
from ejudgment.generation.base import LLMProvider
from ejudgment.verification.entailment import EntailmentModel


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def get_connection(engine: Annotated[Engine, Depends(get_engine)]) -> Iterator[Connection]:
    with engine.begin() as conn:
        yield conn


def get_providers(request: Request) -> tuple[EmbeddingProvider | None, Reranker | None]:
    return request.app.state.embedder, request.app.state.reranker


def get_llm(request: Request) -> LLMProvider | None:
    llm: LLMProvider | None = request.app.state.llm
    return llm


def get_nli(request: Request) -> EntailmentModel | None:
    nli: EntailmentModel | None = request.app.state.nli
    return nli


def bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() or None if scheme.lower() == "bearer" else None


def client_address(request: Request) -> str | None:
    """For the audit only (hashed); never used for security decisions. Behind the UI server
    the first X-Forwarded-For entry is the browser's address."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else None)


def get_current_user(request: Request) -> AuthUser | None:
    """The signed-in user (own short transaction, so long chat requests hold no lock).
    ``None`` only when auth_required is off and no valid token is given."""
    settings: Settings = request.app.state.settings
    engine: Engine = request.app.state.engine
    token = bearer_token(request)
    if token is None:
        if settings.auth_required:
            raise UNAUTHENTICATED
        return None
    try:
        with engine.begin() as conn:
            return resolve_session(conn, settings, token)
    except AuthError:
        if settings.auth_required:
            raise
        return None


CurrentUserDep = Annotated[AuthUser | None, Depends(get_current_user)]


def require_user(user: CurrentUserDep) -> None:
    """Router-level guard: every route of the router needs a session."""


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ProvidersDep = Annotated[tuple[EmbeddingProvider | None, Reranker | None], Depends(get_providers)]
EngineDep = Annotated[Engine, Depends(get_engine)]
ConnectionDep = Annotated[Connection, Depends(get_connection)]
LLMDep = Annotated[LLMProvider | None, Depends(get_llm)]
NLIDep = Annotated[EntailmentModel | None, Depends(get_nli)]
