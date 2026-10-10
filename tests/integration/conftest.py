import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from ejudgment.config import Settings, get_settings
from ejudgment.db import alembic_ini_value
from ejudgment.ingestion.chunk_service import run_chunking
from ejudgment.ingestion.service import run_legacy_import
from ejudgment.ingestion.tokenizer import WhitespaceTokenizer
from tests.fixtures import legacy_fixture as fx

REPO_ROOT = Path(__file__).resolve().parents[2]


def require_database() -> bool:
    """CI sets EJUDGMENT_REQUIRE_DB=1: a missing database must fail the run, not skip silently.
    (Test-only switch, so it is read here rather than through Settings.)"""
    return os.environ.get("EJUDGMENT_REQUIRE_DB") == "1"


@pytest.fixture(scope="session")
def admin_url() -> str:
    url = get_settings().database_url
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        where = make_url(url).render_as_string()  # password masked
        if require_database():
            pytest.fail(f"Postgres not reachable at {where} (required)", pytrace=False)
        pytest.skip(f"Postgres not reachable at {where}")
    finally:
        engine.dispose()
    return url


@pytest.fixture
def database_url(admin_url: str) -> Iterator[str]:
    """A throwaway database per test, dropped afterwards."""
    name = f"ejudgment_test_{uuid.uuid4().hex[:12]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(admin_url).set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def alembic_config(database_url: str) -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", alembic_ini_value(database_url))
    return config


@pytest.fixture
def migrated_engine(database_url: str) -> Iterator[Engine]:
    command.upgrade(alembic_config(database_url), "head")
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def chat_engine(
    legacy_fixture: fx.LegacyFixture, settings: Settings, migrated_engine: Engine
) -> Engine:
    """The fixture corpus imported and chunked (no embeddings): what the chat tests need."""
    run_legacy_import(
        legacy_fixture.db_path, legacy_fixture.base_dir, settings, engine=migrated_engine
    )
    run_chunking(migrated_engine, WhitespaceTokenizer(), settings)
    return migrated_engine
