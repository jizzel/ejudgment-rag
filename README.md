# E-Judgment research

A source-grounded legal research assistant over Ghanaian judgments from the [Ghana Legal Information Institute (GhaLII)](https://ghalii.org). A lawyer can search by citation, case name, words or a legal question, and ask questions that are answered **only from quoted passages of real judgments**. Each statement is checked against its source, and every result links back to the original on GhaLII.

It is a research aid, not legal advice: answers can be incomplete, and the absence of a result does not mean the absence of law. The deployment is **non-commercial**, and all content is credited to GhaLII under its [CC BY-NC 4.0](https://ghalii.org/terms-of-use/) licence.

**Status:** milestones M1–M4 are implemented: foundation, retrieval, conversion/OCR, grounded answers, UI, sign-in and deployment. `AGENTS.md` is the binding development contract and milestone record; `CLAUDE.md` is the command and code guide.

## What it does

- **Search** by exact citation (`[2021] GHASC 1`), case name, keywords or a natural-language question. It combines Postgres full-text search with vector search (bge-small, pgvector), fused by RRF and reranked by a cross-encoder.
  - Filters: court, year range, judge. Judgments published under several URIs show as one case.
- **Cited answers** (`/ask`) from a local model via Ollama (default `gemma4`); OpenAI is opt-in. The model must quote the passages it relies on, and the server keeps a claim only if:
  - the quote really occurs in a cited passage
  - the claim adds no citation or page number of its own
  - an NLI model judges the claim supported by that passage

  The answer text is assembled from the surviving claims, with numbered sources. Page pinpoints appear only for verified PDF pages. When nothing can be supported, it abstains and lists cases to check.
- **Passage viewer:** each passage shown in context, with the quote highlighted, its verified pages, and a link to GhaLII.
- **Sign-in:** invited accounts only, created by an admin.
  - Argon2id passwords; sessions stored only as token hashes.
  - Login lockout, and a security audit with no secrets in it.
  - Per-user query audit, kept as hashes, with a retention policy.
- **Provenance throughout:** every chunk traces back to its judgment, source file, extraction method (PDF text, OCR, converted Word, legacy text), rights status and original URL.

## The corpus

The data is an existing local export (`output/`, not in git) made earlier by the project's original scraper: 8,803 judgment records. After import, source verification, OCR of 74 scanned PDFs and conversion of 6 Word files:
- 8,242 eligible judgments with text
- 159,083 chunks, each with an embedding
- 551 records quarantined: their downloaded "PDF" was a placeholder web page, so their text can only come from GhaLII's official API

The corpus facts, traps and counts are in `AGENTS.md`.

**New data may only come from GhaLII's official API or a separate licence. Scraping and bulk downloading are prohibited by GhaLII's terms, and the old scraper must not be run (see [Legacy export](#legacy-export-frozen)).**

## Quick start: local development

Requirements: Python 3.13 with [Poetry](https://python-poetry.org/), Docker, Node 22, [Ollama](https://ollama.com) (for answers), and `brew install tesseract poppler` (only to OCR scans).

```bash
poetry install
cp .env.example .env              # set POSTGRES_PASSWORD (+ the same in DATABASE_URL) and AUTH_HASH_SECRET
cp ui/.env.example ui/.env.local  # UI_INSECURE_COOKIES=1 for plain-http local use
docker compose up -d postgres     # pgvector/pgvector:pg17 on 127.0.0.1:5434
poetry run alembic upgrade head
poetry run python -m ejudgment.worker.models fetch-models   # pinned tokenizer, embedder, reranker, NLI (~930 MB)
ollama pull gemma4:latest

# Build the index from the export (idempotent; re-runs only redo what changed)
poetry run python -m ejudgment.worker.ingest legacy --source output/pdf/judgments_with_text.db --pdf-base-dir .
poetry run python -m ejudgment.worker.extract --pdf-base-dir .   # Word conversion + OCR
poetry run python -m ejudgment.worker.chunk
poetry run python -m ejudgment.worker.embed                      # ~26 min on an Apple M2 Pro

# Run
poetry run python -m ejudgment.worker.users create --email you@example.org --name "You" --role admin --generate
poetry run uvicorn ejudgment.api.main:app          # API on 127.0.0.1:8000
npm --prefix ui install && npm --prefix ui run dev # UI on http://127.0.0.1:3000 (loopback only)
```

## Deployment

One machine with Docker Compose: Postgres, a migration step, the API, the UI and a Caddy reverse proxy (HTTPS for a domain, security headers). Ollama runs on the host and the model cache is mounted read-only. Only Caddy is reachable from outside; Postgres is published on `127.0.0.1` only.

```bash
cp .env.example .env    # secrets; SITE_ADDRESS=your.domain for HTTPS (see the checklist)
docker compose up -d --build
docker compose run --rm worker python -m ejudgment.worker.users create --email you@example.org --role admin --generate
```

`docs/operations.md` covers:
- the first run, including loading the corpus or restoring a backup
- the TLS checklist and upgrades
- daily backups (`scripts/backup.sh`), retention and a monthly restore drill (`scripts/restore_drill.sh`)
- monitoring, capacity and data protection

## Architecture

```text
output/ (legacy export, read-only)
  └─ worker.ingest   normalise, verify each file against its record, quarantine what can't be trusted
      └─ worker.extract   Word conversion, page-level OCR (Tesseract) with confidence
          └─ worker.chunk     exact-span chunks within the 512-token model budget
              └─ worker.embed     bge-small vectors (pgvector, HNSW)
                  └─ retrieval     citation / case-name lookup + full-text + vectors → RRF → cross-encoder
                      └─ generation    Ollama/OpenAI, JSON schema → quote + reference + NLI verification
                          └─ api (FastAPI, bearer sessions) ── ui (Next.js) ── Caddy
```

| Path | What it is |
| ---- | ---------- |
| `src/ejudgment/` | The Python package: `config`, `domain` (schema), `ingestion`, `embeddings`, `retrieval`, `generation`, `verification`, `auth`, `evaluation`, `api`, `worker` (CLIs) |
| `migrations/` | Alembic migrations (`0001`–`0009`) |
| `ui/` | Next.js 16 app: search, ask, passage viewer, sign-in, gold-set review (see `ui/README.md`) |
| `config/models.yaml` | Non-secret settings: pinned models, chunking, retrieval and generation limits, prices |
| `evals/` | Gold questions (20, engineer-written, `reviewed=false`; exported from the review database) and the OpenAI smoke set |
| `docker/`, `docker-compose.yml`, `scripts/` | Images, Compose stack, Caddy config, backup/restore |
| `tests/`, `ui/tests/` | pytest (unit and Postgres integration) and Vitest suites |
| `src/main.py`, `src/pdf_extractor.py` | The frozen legacy scraper (do not run) |

## Commands

| Command (`poetry run python -m ejudgment.…`) | Purpose |
| -------------------------------------------- | ------- |
| `worker.ingest legacy --source … --pdf-base-dir … [--dry-run]` | Import and verify the export |
| `worker.extract --pdf-base-dir …` | Convert Word files and OCR scanned PDFs |
| `worker.chunk` / `worker.embed` | Build or refresh chunks and vectors |
| `worker.search "query" [--court ghasc …]` | Search from the terminal |
| `worker.ask "question" [--provider openai]` | A cited answer from the terminal |
| `worker.evaluate` / `worker.evaluate_answers` | Retrieval and answer evaluation, stored in `evaluation_runs` |
| `worker.users create\|list\|disable\|enable\|reset-password\|revoke-sessions` | Accounts (roles `admin`, `researcher`, `reviewer`) |
| `worker.gold import\|export\|stats` | Load the gold questions into the review database, write `evals/gold.jsonl` back, show review progress |
| `worker.retention` | Apply the data-retention policy (daily) |
| `worker.models fetch-models` | The only command that downloads model weights |

## Quality

Measured on 20 seed questions written by engineers and not yet reviewed by a lawyer, so the figures are **provisional**. Full figures and run IDs are in `AGENTS.md`.

| Measure | Result |
| ------- | ------ |
| Retrieval, hybrid (Recall@20 / MRR@10) | 0.82 / 0.58; citation and case-name questions 1.0 |
| Answers, gemma4 (local) | 94% answered, 53% cite a gold case, all 3 out-of-scope questions abstained, 42 of 43 claims verified |
| Answers, gpt-6-luna (OpenAI pilot) | 88% answered, 59% cite a gold case, all out-of-scope abstained, 32 of 37 claims verified, $0.0068 for 20 questions |

**Next:** a lawyer-reviewed gold set of 50–100 questions, before tuning retrieval, prompts or verification.

### How lawyers review the gold set
1. An admin creates a reviewer account: `worker.users create --email … --role reviewer --generate`, and loads the questions once: `worker.gold import`.
2. The reviewer signs in and opens **Review**. For each question they see what search returns now. They tick the cases a correct answer must find, mark the passages (or a selected part) that answer it, add missing cases by citation, or mark that the corpus should give no answer. **Preview answer** shows what the system would say.
3. **Approve** confirms the labels. Every change is versioned and kept in a history; two people editing at once get a "reload" message instead of overwriting each other.
4. `worker.gold export` writes `evals/gold.jsonl` (approved questions get `reviewed=true`; reviewer names stay in the database). Evaluations then report the metrics on approved questions separately, under `reviewed`.

## Data, rights and privacy

- **Source rights:**
  - GhaLII content is used under CC BY-NC 4.0: non-commercial use only, with attribution on every result, answer and page (built in).
  - New judgments come only from the official API or a licence.
  - Records whose rights are unknown are quarantined, never indexed.
- **Local first:** by default answers are generated on the host (Ollama), so questions never leave the machine. OpenAI is opt-in, with per-run budget limits, and sends questions and passages to OpenAI.
- **Personal data:**
  - User accounts, sign-in events (hashed emails and IP addresses) and query audit (hashed queries) are kept only as long as the retention policy allows.
  - Backups contain all of this, so keep them private and encrypted.

## Development

```bash
poetry run ruff check . && poetry run mypy && poetry run pytest        # Python (integration tests need the Postgres container)
npm --prefix ui run lint && npm --prefix ui run typecheck && npm --prefix ui test && npm --prefix ui run build
```

- **CI** (`.github/workflows/ci.yml`) runs on every pull request and every push to `main`, with no secrets, paid APIs or model downloads:
  - `python`: ruff, mypy, `alembic upgrade`/`check` and the full pytest suite against a pgvector service. Integration tests must run (`EJUDGMENT_REQUIRE_DB=1` turns a missing database into a failure).
  - `ui`: lint, type check, Vitest, build.
  - `deploy`: Compose config, `bash -n` and shellcheck on `scripts/`, both image builds and an image smoke test.
  - Python dependencies are installed with CPU-only torch by `scripts/install-python-deps.sh`, the same script the Docker image uses.
- **Tests never touch the network:** a socket guard allows loopback only, and the models and LLM are faked.
- **Drift guards** fail when the OpenAPI snapshot, the generated UI types, `.env.example` or the evaluation settings fall out of date.
- **Contributing:** read `AGENTS.md` first (it is binding), keep changes PR-sized, and leave commits to the repository owner.

## Legacy export (frozen)

`src/main.py` (a GhaLII crawler) and `src/pdf_extractor.py` (PDF download and PyPDF2 text) produced the local export in `output/`. They are kept only as a record of how it was made. **They must not be run or extended:** GhaLII prohibits scraping and bulk downloading.

The project now only reads the export, read-only:
- `output/pdf/judgments_with_text.db`: SQLite table `judgments`, one row per AKN URI, with GhaLII's metadata labels as columns (`citation`, `court`, `judges`, `judgment_date`, …) plus `pdf_text`, `pdf_extraction_status`, `pdf_text_length` and `pdf_local_path`.
- `output/pdf/downloaded_pdfs_<year>/`: the downloaded source files, named by citation. They are not always PDFs, and the path is not always right; the importer verifies each file.
- `judgments_with_text.json` cuts `pdf_text` to 500 characters, so it's never used as full text.

The importer handles the export's traps, documented in `AGENTS.md` ("Local corpus facts"):
- viewer boilerplate instead of text
- shared or wrong file paths
- placeholder downloads
- re-published judgments
- NUL characters and mojibake
