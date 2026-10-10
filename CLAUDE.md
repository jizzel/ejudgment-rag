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
cp .env.example .env && cp ui/.env.example ui/.env.local   # then set AUTH_HASH_SECRET (and OPENAI_* only if opting in)
docker compose up -d postgres
poetry run alembic upgrade head
poetry run python -m ejudgment.worker.models fetch-models     # once: pinned tokenizer, bge-small, MiniLM reranker, NLI model -> HF cache

poetry run ruff check . && poetry run mypy && poetry run pytest
poetry run pytest tests/unit/test_normalize.py::test_split_judges   # single test
poetry run pytest -m "not integration"                              # without Postgres

# Legacy import (read-only on the export; explicit paths only)
poetry run python -m ejudgment.worker.ingest legacy \
  --source output/pdf/judgments_with_text.db --pdf-base-dir . [--dry-run] [--limit N]

poetry run python -m ejudgment.worker.extract --pdf-base-dir . [--limit N]     # Word conversion + OCR; needs `brew install tesseract poppler`
poetry run python -m ejudgment.worker.chunk [--limit N] [--judgment-uri URI]   # idempotent
poetry run python -m ejudgment.worker.embed [--limit N]                        # idempotent, ~110 chunks/s on MPS
poetry run python -m ejudgment.worker.search "adverse possession" --court ghasc --year-from 2015 [--mode hybrid|lexical|dense] [--no-rerank]
poetry run python -m ejudgment.worker.evaluate [--gold evals/gold.jsonl]      # stores an evaluation_runs row
poetry run python -m ejudgment.worker.ask "When may a landlord recover possession?" [--court ghasc] [--model M]
poetry run python -m ejudgment.worker.evaluate_answers [--model M]           # answer metrics -> evaluation_runs
poetry run uvicorn ejudgment.api.main:app          # /healthz, /v1/judgments/{id}, /v1/search, /v1/chat, /v1/passages/{chunk_id}, /v1/courts

# Deployment (docs/operations.md): postgres, migrate, api, ui, caddy; worker on demand
docker compose up -d --build                      # needs POSTGRES_PASSWORD in .env (dev volumes made earlier use "ejudgment"); containers build their DB URL from it (Settings.postgres_*)
docker compose run --rm worker python -m ejudgment.worker.users list
scripts/backup.sh | scripts/restore.sh <dump> [db] | scripts/restore_drill.sh   # COMPOSE="docker compose -p other" for another project

poetry run python -m ejudgment.worker.users create --email you@example.org --name "You" --role admin [--generate]   # invite; list|disable|enable|reset-password|revoke-sessions
poetry run python -m ejudgment.worker.retention      # daily: deletes audit/auth/session/usage rows past their retention
poetry run python -m ejudgment.worker.gold import|export [--file evals/gold.jsonl] | stats   # gold questions DB <-> file; lawyers review at /review (role reviewer)

# UI (ui/, Next.js 16; Node 22): talks to the API server-side via EJUDGMENT_API_URL (default http://127.0.0.1:8000)
# Sign in at /login; UI_INSECURE_COOKIES=1 is needed for plain-http local use (cookies are Secure otherwise)
npm --prefix ui install && npm --prefix ui run dev     # http://127.0.0.1:3000 (loopback only: no sign-in yet)
npm --prefix ui run lint && npm --prefix ui run typecheck && npm --prefix ui test && npm --prefix ui run build
poetry run python -m ejudgment.api.export_openapi && npm --prefix ui run gen:api   # after any API schema change
```

Generation needs Ollama running locally with the configured model (`ollama_chat_model`, `ollama pull <model>` first); without it `/v1/chat` returns 503 `llm_unavailable` and search still works. OpenAI is opt-in and paid: it needs `OPENAI_API_KEY` in `.env` (gitignored; never read, print or commit it) plus `OPENAI_ENABLED=true` and `LLM_PROVIDER=openai` or `--provider openai`, and a model priced in `openai_prices`. Pilot runs: `OPENAI_ENABLED=true poetry run python -m ejudgment.worker.evaluate_answers --provider openai [--gold evals/smoke.jsonl]`. Each run is soft-stopped at 20 calls / $1 (`generation/budget.check_budget`, read from `llm_usage_ledger`); tests never call OpenAI (socket guard; SDK mocked through `httpx2.MockTransport`).

Integration tests create and drop a throwaway database per test via `DATABASE_URL` and are skipped when Postgres is unreachable, unless `EJUDGMENT_REQUIRE_DB=1` (set in CI), which makes that a failure. CI is `.github/workflows/ci.yml` (python, ui, deploy jobs). Shell scripts must pass shellcheck (`docker run --rm -v "$PWD":/mnt -w /mnt koalaman/shellcheck:stable -x scripts/*.sh`) and stay bash 3.2 compatible. A test-wide socket guard fails any non-loopback connection. Tests use fake providers (`embeddings/fake.py`); the one real-model test is skipped when the HF cache lacks the weights. Models always load with `local_files_only=True` (set `HF_HUB_OFFLINE=1` to be sure nothing is fetched). `CREATE EXTENSION vector` needs a superuser; on managed Postgres an admin pre-installs it.

## RAG package layout (`src/ejudgment`)

- `config.py`: pydantic-settings; env > `config/models.yaml` > defaults. Don't read `os.environ` elsewhere.
- `domain/models.py` + `migrations/`: canonical schema (judgments, document_sources, document_pages, ingestion_jobs, ingestion_issues). Keep models and migrations in sync (`alembic check`).
- `ingestion/`: `legacy_adapter` (read-only SQLite reader) → `normalize`/`quality` (pure functions) → `pdf_verify` (file-type sniffing + char-n-gram match against legacy text) → `service.run_legacy_import` (deterministic uuid5 IDs + `record_hash` make re-imports no-ops).
- `ingestion/extract_service.py`: after import, converts `.docx` (`docx_text.py`, stdlib) and OCRs scans (`ocr.py`, Tesseract CLI; `FakeOcr` in tests) into `document_pages` (`converted` / `ocr` with `ocr_confidence`); upgrades `unverified` files to `verified` only on citation/party-name evidence in the extracted text. Pages carry `extractor_version`; a different engine/settings/parser version re-extracts those sources (bump `OCR_FORMAT_VERSION` / `DOCX_EXTRACTOR_VERSION` when the output changes). Placeholder HTML downloads are rejected at import (`pdf_verify.is_placeholder_html`).
- `ingestion/chunking.py` (pure: exact-span chunks within the bge token budget) → `chunk_service.run_chunking` (one source per judgment; skips judgments whose chunks match the current `chunker_version` + source text hash). Tests use `WhitespaceTokenizer`; the real tokenizer loads offline from the HF cache.
- `embeddings/`: `base` (protocols, device), `sentence_transformers` (bge-small, query instruction prefix), `template` (`ctx-v1` input = context prefix + verbatim chunk; prefix trimmed to fit 512 tokens; `embedding_input_hash` covers template + metadata), `fake`, `loading`. `ingestion/embed_service.run_embedding` re-embeds only chunks whose input hash changed and backfills `context_hash` (set-based; never per-row updates on vector rows). Dense search and `retrieval/coverage.py` ignore vectors whose `context_hash` no longer matches the judgment's metadata (`CONTEXT_HASH_SQL`); missing or stale vectors show up as `query_info.degraded`.
- `retrieval/`: `query` (citation/case-name detection) → `repository` (SQL; always eligible-only, filters bound and strict; `dense_passages` inlines the validated model id/revision so the partial HNSW index is usable) → `hybrid` (RRF, rerank ordering) → `service.search` (exact citation > case name > channel ranking; fixed-size pools so pages are stable; cases grouped by `source_text_hash`; missing models degrade visibly via `query_info`). `rerank.py` is the cross-encoder. `domain/schemas.py` holds the API/CLI models, attribution and notice.
- `evaluation/retrieval.py` + `evals/gold.jsonl`: case-level Recall@20/MRR@10/latency per mode; runs stored in `evaluation_runs` with full model/config provenance. The seed questions are engineer-written (`reviewed=false`), so metrics are provisional. `evaluation/gold_review.py` + `api/routes/review.py` + `ui/src/app/review/`: lawyers (role `reviewer`/`admin`) review questions in the app with versioned writes (409 `version_conflict`) and history; `worker.gold export` writes the file (no reviewer names). Metrics are also reported under `reviewed` (approved only). Never approve questions or set `reviewed=true` yourself.
- Per-model HNSW indexes are created by hand in migrations with the prefix `ix_chunk_embeddings_hnsw_`; `migrations/env.py` excludes that prefix from autogenerate.
- `generation/` + `verification/` (M3): `chat.answer_question` retrieves (hybrid + rerank; for an exact citation/case-name match also the judgment's closing chunks), selects passages within a token budget (`budget.py`), sends them as `<source id="S1">` envelopes (`prompt.py`, `PROMPT_VERSION`; passage text can't forge tags) to an `LLMProvider` (`ollama_provider.py`; `fake.FakeLLM` in tests) with a JSON schema, then keeps only claims whose quote occurs verbatim in a passage they cite, whose text adds no citation absent from it and no page reference at all, and which that passage entails: verbatim, or per the pinned NLI cross-encoder on 1–3-sentence windows with case context (`verification/support.py`, `verification/entailment.py`; `FakeNli` in tests; no NLI model → 503 `verifier_unavailable`). The answer text is built server-side from kept claims; citations, links and pages come from the database (pages only when verified). Abstains with `matched_cases` on no results, model abstention, no surviving claim or invalid output. Each model call writes an `llm_usage_ledger` row (no text; `estimated_usd` from `openai_prices` for priced providers); `generation/openai_provider.py` is the opt-in OpenAI Responses-API provider (strict JSON schema, `store=False`). `evaluation/answers.py` holds the answer metrics and `GENERATION_SETTINGS` (a unit test forces new generation settings to be listed).
- `auth/` (M4 slice 2): invited accounts (`worker.users`), Argon2id passwords, bearer sessions stored as SHA-256 hashes (12 h idle / 7 d max), per-email lockout read from `auth_events` (no secrets, HMAC-hashed email/client). `api/dependencies.get_current_user` guards every `/v1` router (`require_user`); `auth_required` is on by default and turned off only in the shared test `settings` fixture, so new route tests must opt in to test auth. Failed logins commit in their own transaction (or the lockout never counts); `login` takes a per-email advisory lock and locks the user row `FOR UPDATE`, so the limit and resets hold under concurrency. `retention.py` is the retention policy.
- `api/`: `create_app(settings, engine, embedder=..., reranker=..., llm=..., nli=..., load_models=False)` for tests; errors are `{"error": {"code", ...}}` with stable codes (`invalid_filter`, `query_empty`, `judgment_not_found`, ...). `/v1/search` and `/v1/chat` write a hashed `query_audit` row.
- `ui/` (M4 slice 1): Next.js App Router. Pages: search (`/`, a server component; the URL holds the query and filters), ask (`/ask`, a client form posting to `src/app/api/chat/route.ts`) and passage viewer (`/passages/[chunkId]?quote=`). Every API call is server-side (`src/lib/api.ts`, `server-only`). Types come from the committed OpenAPI snapshot (`src/lib/openapi.json` → `api-types.ts`); `tests/unit/test_openapi_snapshot.py` and `ui/tests/api-types.test.ts` fail when either is stale. Attribution and notice text come from the snapshot's defaults (`src/lib/notices.ts`). With Cache Components on, async data sits inside `<Suspense>`, and pages render outside try/catch via `attempt()`. Vitest can't render async server components, so the logic lives in synchronous components and `src/lib/` and is tested there. Sign-in: `/login` (server action) keeps the API token in an HttpOnly cookie (`lib/auth.ts`, `lib/session.ts`); `src/proxy.ts` is only an optimistic redirect; the chat route also checks `Origin`. Still local use only until slice 3 (TLS/Compose).
- `tests/fixtures/legacy_fixture.py` generates the synthetic 100-row export; each trap from the real data has a named `ROW_*` constant and `EXPECTED` counts.

Do not commit to git. Always leave commit task to me.
