# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

The project is evolving from a GhaLII scraper into a source-grounded legal RAG. The full development contract (source rights, schema, pipelines, provider interfaces, testing gates, milestones) lives in AGENTS.md and is binding:

@AGENTS.md

## Legacy scripts (frozen — do not run)

`src/main.py` (scraper) and `src/pdf_extractor.py` (PDF download + PyPDF2 text) produced the local export in `output/` (not in Git). Do **not** run or extend them: GhaLII prohibits scraping and bulk downloading. Work from the existing export, primarily `output/pdf/judgments_with_text.db` (table `judgments`, full `pdf_text`). Open it read-only, e.g. `sqlite3 -readonly output/pdf/judgments_with_text.db`.

Behaviours to keep in mind when reading or adapting them:
- Both resolve `output/` relative to the CWD and pick the "latest" export folder by mtime. New code must take explicit paths instead.
- Record columns come from GhaLII's metadata labels (lowercased, spaces → `_`), so treat the schema as dynamic. `url` (an AKN expression URI) is the unique record identity.
- `judgments_with_text.json` truncates `pdf_text` to 500 characters; never use it as full text.

## Commands

Python 3.13+, Poetry. Local Postgres (pgvector image) runs in Docker on host port **5434** (`EJUDGMENT_DB_PORT` overrides; 5432/5433 are taken on the dev machine).

```bash
poetry install
docker compose up -d postgres
poetry run alembic upgrade head

poetry run ruff check . && poetry run mypy && poetry run pytest
poetry run pytest tests/unit/test_normalize.py::test_split_judges   # single test
poetry run pytest -m "not integration"                              # without Postgres

# Legacy import (read-only on the export; explicit paths only)
poetry run python -m ejudgment.worker.ingest legacy \
  --source output/pdf/judgments_with_text.db --pdf-base-dir . [--dry-run] [--limit N]
```

Integration tests create and drop a throwaway database per test via `DATABASE_URL` and are skipped when Postgres is unreachable. A test-wide socket guard fails any non-loopback connection.

## RAG package layout (`src/ejudgment`)

- `config.py`: pydantic-settings; env > `config/models.yaml` > defaults. Don't read `os.environ` elsewhere.
- `domain/models.py` + `migrations/`: canonical schema (judgments, document_sources, document_pages, ingestion_jobs, ingestion_issues). Keep models and migrations in sync (`alembic check`).
- `ingestion/`: `legacy_adapter` (read-only SQLite reader) → `normalize`/`quality` (pure functions) → `pdf_verify` (file-type sniffing + char-n-gram match against legacy text) → `service.run_legacy_import` (deterministic uuid5 IDs + `record_hash` make re-imports no-ops).
- `tests/fixtures/legacy_fixture.py` generates the synthetic 100-row export; each trap from the real data has a named `ROW_*` constant and `EXPECTED` counts.

Do not commit to git. Always leave commit task to me.
