import sqlite3
from pathlib import Path

import pytest

from ejudgment.ingestion.hashing import sha256_file
from ejudgment.ingestion.legacy_adapter import LegacyExport, LegacyExportError
from tests.fixtures.legacy_fixture import COLUMNS, ROW_COUNT, LegacyFixture


def test_reads_all_rows_with_dynamic_columns(legacy_fixture: LegacyFixture) -> None:
    export = LegacyExport(legacy_fixture.db_path)
    assert export.columns == COLUMNS
    records = list(export.records())
    assert len(records) == ROW_COUNT == export.count()
    assert records[0].row_number == 1
    assert records[0].row_key.startswith("https://ghalii.org/akn/")


def test_limit(legacy_fixture: LegacyFixture) -> None:
    assert len(list(LegacyExport(legacy_fixture.db_path).records(limit=5))) == 5


def test_source_is_not_modified(legacy_fixture: LegacyFixture) -> None:
    path = legacy_fixture.db_path
    before = (sha256_file(path), path.stat().st_mtime_ns)
    export = LegacyExport(path)
    list(export.records())
    export.source_version()
    assert (sha256_file(path), path.stat().st_mtime_ns) == before


def test_connection_is_read_only(legacy_fixture: LegacyFixture) -> None:
    conn = LegacyExport(legacy_fixture.db_path)._connect()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM judgments")
    conn.close()


def test_missing_required_column_fails_clearly(tmp_path: Path) -> None:
    db = tmp_path / "bad.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE judgments (citation TEXT)")
    conn.close()
    with pytest.raises(LegacyExportError, match="url"):
        _ = LegacyExport(db).columns


def test_missing_table_fails_clearly(tmp_path: Path) -> None:
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    with pytest.raises(LegacyExportError, match="judgments"):
        _ = LegacyExport(db).columns


def test_missing_file_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(LegacyExportError, match="not found"):
        LegacyExport(tmp_path / "nope.db")
