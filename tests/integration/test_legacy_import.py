import sqlite3
import uuid
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url

from ejudgment.config import Settings, get_settings
from ejudgment.ingestion.service import CONFLICT_RECORD_HASH, run_legacy_import
from tests.fixtures import legacy_fixture as fx
from tests.integration.conftest import REPO_ROOT, alembic_config

pytestmark = pytest.mark.integration

SNAPSHOT_QUERIES = {
    "judgments": "SELECT id, canonical_uri, record_hash, eligibility_status, source_status "
    "FROM judgments ORDER BY id",
    "document_sources": "SELECT id, judgment_id, kind, sha256, verification_status, rights_status "
    "FROM document_sources ORDER BY id",
    "document_pages": "SELECT id, source_id, page_index, text_hash, extraction_method "
    "FROM document_pages ORDER BY id",
}


def _snapshot(engine: Engine) -> dict[str, list[tuple[Any, ...]]]:
    with engine.connect() as conn:
        return {
            name: [tuple(row) for row in conn.execute(text(sql))]
            for name, sql in SNAPSHOT_QUERIES.items()
        }


def _import(fixture: fx.LegacyFixture, settings: Settings, engine: Engine) -> Any:
    return run_legacy_import(fixture.db_path, fixture.base_dir, settings, engine=engine)


def test_import_twice_is_idempotent(
    legacy_fixture: fx.LegacyFixture, settings: Settings, migrated_engine: Engine
) -> None:
    first = _import(legacy_fixture, settings, migrated_engine)
    snapshot = _snapshot(migrated_engine)

    assert first.inserted == fx.EXPECTED["judgments_written"]
    assert first.updated == 0
    assert len(snapshot["judgments"]) == fx.EXPECTED["judgments_written"]
    assert snapshot["document_pages"]

    second = _import(legacy_fixture, settings, migrated_engine)
    assert (second.inserted, second.updated) == (0, 0)
    assert second.skipped_unchanged == fx.EXPECTED["judgments_written"]
    assert _snapshot(migrated_engine) == snapshot

    with migrated_engine.connect() as conn:
        jobs = conn.execute(text("SELECT status FROM ingestion_jobs")).scalars().all()
        issues_per_job = (
            conn.execute(text("SELECT count(*) FROM ingestion_issues GROUP BY job_id"))
            .scalars()
            .all()
        )
    assert jobs == ["succeeded", "succeeded"]
    assert len(set(issues_per_job)) == 1  # both runs report the same issues


def test_changed_record_is_updated(
    legacy_fixture: fx.LegacyFixture, settings: Settings, migrated_engine: Engine
) -> None:
    _import(legacy_fixture, settings, migrated_engine)
    with sqlite3.connect(legacy_fixture.db_path) as conn:
        conn.execute(
            "UPDATE judgments SET court = 'Court of Appeal' WHERE rowid = 21"
        )  # row 20: no duplicate
    conn.close()

    report = _import(legacy_fixture, settings, migrated_engine)
    assert (report.inserted, report.updated) == (0, 1)
    with migrated_engine.connect() as conn:
        court = conn.execute(
            text("SELECT court_name FROM judgments WHERE citation LIKE 'Party20 %'")
        ).scalar_one()
    assert court == "Court of Appeal"


def _judgment_state(engine: Engine, citation_prefix: str) -> tuple[str, str]:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT eligibility_status, record_hash FROM judgments WHERE citation LIKE :p"),
            {"p": f"{citation_prefix} %"},
        ).one()
    return row.eligibility_status, row.record_hash


def test_later_conflict_quarantines_stored_judgment(
    legacy_fixture: fx.LegacyFixture, settings: Settings, migrated_engine: Engine
) -> None:
    _import(legacy_fixture, settings, migrated_engine)
    assert _judgment_state(migrated_engine, "Party30")[0] == "eligible"

    # A later export carries a second, different row for the same URI.
    with sqlite3.connect(legacy_fixture.db_path) as conn:
        conn.execute("INSERT INTO judgments SELECT * FROM judgments WHERE rowid = 31")
        conn.execute(
            "UPDATE judgments SET citation = 'Someone Else Vrs Party30 [2020] GHASC 31 (x)Copy' "
            "WHERE rowid = (SELECT max(rowid) FROM judgments)"
        )
    conn.close()

    report = _import(legacy_fixture, settings, migrated_engine)
    assert report.quarantined_existing == 1
    assert _judgment_state(migrated_engine, "Party30") == (
        "quarantined",
        CONFLICT_RECORD_HASH,
    )

    # Re-running over the same conflicting export changes nothing further.
    snapshot = _snapshot(migrated_engine)
    again = _import(legacy_fixture, settings, migrated_engine)
    assert (again.quarantined_existing, again.inserted, again.updated) == (0, 0, 0)
    assert _snapshot(migrated_engine) == snapshot

    # Once the conflict is gone, the record is restored on the next import.
    with sqlite3.connect(legacy_fixture.db_path) as conn:
        conn.execute("DELETE FROM judgments WHERE rowid = (SELECT max(rowid) FROM judgments)")
    conn.close()
    restored = _import(legacy_fixture, settings, migrated_engine)
    assert restored.updated == 1
    assert _judgment_state(migrated_engine, "Party30")[0] == "eligible"


def test_quarantine_and_provenance_are_recorded(
    legacy_fixture: fx.LegacyFixture, settings: Settings, migrated_engine: Engine
) -> None:
    _import(legacy_fixture, settings, migrated_engine)
    with migrated_engine.connect() as conn:
        reasons = {
            row.reason: row.count
            for row in conn.execute(
                text(
                    "SELECT reason, count(*) AS count FROM ingestion_issues "
                    "WHERE severity = 'quarantine' GROUP BY reason"
                )
            )
        }
        rights = conn.execute(text("SELECT DISTINCT rights_status FROM document_sources")).scalars()
        mismatched = conn.execute(
            text("SELECT count(*) FROM document_sources WHERE verification_status = 'mismatch'")
        ).scalar_one()
        unmapped_pages = conn.execute(
            text("SELECT count(*) FROM document_pages WHERE page_index IS NOT NULL")
        ).scalar_one()
    assert reasons == {
        "invalid_akn_uri": 1,
        "duplicate_uri_conflict": 2,
        "no_usable_text_and_no_pdf": 2,
    }
    assert list(rights) == ["cc_by_nc_local_export"]
    assert mismatched == 2
    assert unmapped_pages == 0  # legacy text never gets invented page numbers


def test_migration_downgrade(database_url: str) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    engine = create_engine(database_url)
    try:
        tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()
    assert tables == set()


def test_migrations_accept_percent_encoded_credentials(
    admin_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """env.py must escape ``%`` when it reads DATABASE_URL from settings."""
    suffix = uuid.uuid4().hex[:12]
    role, database = f"ejudgment_pct_{suffix}", f"ejudgment_pct_{suffix}"
    password = "p@ss%word"  # URL-encoded below as p%40ss%25word
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'"))
        conn.execute(text(f'CREATE DATABASE "{database}" OWNER "{role}"'))
    url = (
        make_url(admin_url)
        .set(username=role, password=password, database=database)
        .render_as_string(hide_password=False)
    )
    assert "%40" in url and "%25" in url
    try:
        monkeypatch.setenv("DATABASE_URL", url)
        get_settings.cache_clear()
        config = Config(str(REPO_ROOT / "alembic.ini"))  # no URL: env.py reads settings
        command.upgrade(config, "head")
        engine = create_engine(url)
        try:
            assert "judgments" in inspect(engine).get_table_names()
        finally:
            engine.dispose()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
            conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        admin.dispose()
