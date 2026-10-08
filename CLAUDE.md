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
poetry run python -m ejudgment.worker.models fetch-models     # once: pinned tokenizer, bge-small, MiniLM reranker -> HF cache

poetry run ruff check . && poetry run mypy && poetry run pytest
poetry run pytest tests/unit/test_normalize.py::test_split_judges   # single test
poetry run pytest -m "not integration"                              # without Postgres

# Legacy import (read-only on the export; explicit paths only)
poetry run python -m ejudgment.worker.ingest legacy \
  --source output/pdf/judgments_with_text.db --pdf-base-dir . [--dry-run] [--limit N]

poetry run python -m ejudgment.worker.chunk [--limit N] [--judgment-uri URI]   # idempotent
poetry run python -m ejudgment.worker.embed [--limit N]                        # idempotent, ~110 chunks/s on MPS
poetry run python -m ejudgment.worker.search "adverse possession" --court ghasc --year-from 2015 [--mode hybrid|lexical|dense] [--no-rerank]
poetry run python -m ejudgment.worker.evaluate [--gold evals/gold.jsonl]      # stores an evaluation_runs row
poetry run uvicorn ejudgment.api.main:app          # /healthz, /v1/judgments/{id}, /v1/search
```

Integration tests create and drop a throwaway database per test via `DATABASE_URL` and are skipped when Postgres is unreachable. A test-wide socket guard fails any non-loopback connection. Tests use fake providers (`embeddings/fake.py`); the one real-model test is skipped when the HF cache lacks the weights. Models always load with `local_files_only=True` (set `HF_HUB_OFFLINE=1` to be sure nothing is fetched). `CREATE EXTENSION vector` needs a superuser; on managed Postgres an admin pre-installs it.

## RAG package layout (`src/ejudgment`)

- `config.py`: pydantic-settings; env > `config/models.yaml` > defaults. Don't read `os.environ` elsewhere.
- `domain/models.py` + `migrations/`: canonical schema (judgments, document_sources, document_pages, ingestion_jobs, ingestion_issues). Keep models and migrations in sync (`alembic check`).
- `ingestion/`: `legacy_adapter` (read-only SQLite reader) → `normalize`/`quality` (pure functions) → `pdf_verify` (file-type sniffing + char-n-gram match against legacy text) → `service.run_legacy_import` (deterministic uuid5 IDs + `record_hash` make re-imports no-ops).
- `ingestion/chunking.py` (pure: exact-span chunks within the bge token budget) → `chunk_service.run_chunking` (one source per judgment; skips judgments whose chunks match the current `chunker_version` + source text hash). Tests use `WhitespaceTokenizer`; the real tokenizer loads offline from the HF cache.
- `embeddings/`: `base` (protocols, device), `sentence_transformers` (bge-small, query instruction prefix), `template` (`ctx-v1` input = context prefix + verbatim chunk; prefix trimmed to fit 512 tokens; `embedding_input_hash` covers template + metadata), `fake`, `loading`. `ingestion/embed_service.run_embedding` re-embeds only chunks whose input hash changed.
- `retrieval/`: `query` (citation/case-name detection) → `repository` (SQL; always eligible-only, filters bound and strict; `dense_passages` inlines the validated model id/revision so the partial HNSW index is usable) → `hybrid` (RRF, rerank ordering) → `service.search` (exact citation > case name > channel ranking; fixed-size pools so pages are stable; cases grouped by `source_text_hash`; missing models degrade visibly via `query_info`). `rerank.py` is the cross-encoder. `domain/schemas.py` holds the API/CLI models, attribution and notice.
- `evaluation/retrieval.py` + `evals/gold.jsonl`: case-level Recall@20/MRR@10/latency per mode; runs stored in `evaluation_runs` with full model/config provenance. The seed questions are engineer-written (`reviewed=false`), so metrics are provisional.
- Per-model HNSW indexes are created by hand in migrations with the prefix `ix_chunk_embeddings_hnsw_`; `migrations/env.py` excludes that prefix from autogenerate.
- `api/`: `create_app(settings, engine, embedder=..., reranker=..., load_models=False)` for tests; errors are `{"error": {"code", ...}}` with stable codes (`invalid_filter`, `query_empty`, `judgment_not_found`, ...). `/v1/search` writes a hashed `query_audit` row.
- `tests/fixtures/legacy_fixture.py` generates the synthetic 100-row export; each trap from the real data has a named `ROW_*` constant and `EXPECTED` counts.

Do not commit to git. Always leave commit task to me.
