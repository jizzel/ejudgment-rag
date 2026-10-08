"""Request-scoped dependencies. The app owns one engine; tests inject their own."""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine
from sqlalchemy.engine import Connection

from ejudgment.config import Settings


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_engine(request: Request) -> Engine:
    engine: Engine = request.app.state.engine
    return engine


def get_connection(engine: Annotated[Engine, Depends(get_engine)]) -> Iterator[Connection]:
    with engine.begin() as conn:
        yield conn


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
EngineDep = Annotated[Engine, Depends(get_engine)]
ConnectionDep = Annotated[Connection, Depends(get_connection)]
