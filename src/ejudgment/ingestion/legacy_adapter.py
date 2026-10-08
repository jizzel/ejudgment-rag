"""Read-only reader for the legacy SQLite export (``output/pdf/judgments_with_text.db``).

The export's columns come from GhaLII's metadata labels, so they are discovered at runtime.
The file is opened with ``mode=ro`` and is never written.
"""

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ejudgment.ingestion.hashing import sha256_file

TABLE_NAME = "judgments"
REQUIRED_COLUMNS = frozenset({"url", "citation"})
# Large text columns are carried separately and kept out of the metadata JSONB.
TEXT_COLUMNS = frozenset({"pdf_text", "full_text"})


class LegacyExportError(Exception):
    """The export does not have the shape this adapter understands."""


@dataclass(frozen=True)
class LegacyRecord:
    row_number: int  # 1-based position in the export, used as a fallback row key
    values: dict[str, Any]

    def get(self, column: str) -> Any:
        return self.values.get(column)

    @property
    def row_key(self) -> str:
        url = self.values.get("url")
        return str(url) if url else f"row:{self.row_number}"


class LegacyExport:
    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise LegacyExportError(f"Legacy export not found: {path}")
        self.path = path
        self._columns: list[str] | None = None

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True)

    @property
    def columns(self) -> list[str]:
        if self._columns is None:
            with self._connect() as conn:
                tables = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if TABLE_NAME not in tables:
                    raise LegacyExportError(
                        f"Table {TABLE_NAME!r} not found in {self.path}; found {sorted(tables)}"
                    )
                columns = [row[1] for row in conn.execute(f"PRAGMA table_info({TABLE_NAME})")]
            missing = REQUIRED_COLUMNS - set(columns)
            if missing:
                raise LegacyExportError(
                    f"{self.path} is missing required columns: {sorted(missing)}"
                )
            self._columns = columns
        return self._columns

    def source_version(self) -> str:
        return f"legacy-export:{sha256_file(self.path)[:16]}"

    def count(self) -> int:
        with self._connect() as conn:
            (total,) = conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()
        return int(total)

    def records(self, limit: int | None = None) -> Iterator[LegacyRecord]:
        columns = self.columns
        quoted = ", ".join(f'"{column}"' for column in columns)
        sql = f"SELECT {quoted} FROM {TABLE_NAME} ORDER BY rowid"
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = (limit,)
        conn = self._connect()
        try:
            for row_number, row in enumerate(conn.execute(sql, params), start=1):
                yield LegacyRecord(row_number, dict(zip(columns, row, strict=True)))
        finally:
            conn.close()
