"""Request-scoped dependencies. The app owns one engine; tests inject their own."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.engine import Connection

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


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ProvidersDep = Annotated[tuple[EmbeddingProvider | None, Reranker | None], Depends(get_providers)]
EngineDep = Annotated[Engine, Depends(get_engine)]
ConnectionDep = Annotated[Connection, Depends(get_connection)]
LLMDep = Annotated[LLMProvider | None, Depends(get_llm)]
NLIDep = Annotated[EntailmentModel | None, Depends(get_nli)]
