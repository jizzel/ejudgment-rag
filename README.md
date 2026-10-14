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

  Answers stream: the page shows each stage (searching, drafting, checking) and the passages being read, and **Cancel** stops the model call on the server.
- **Research workspace:** results and answers sit beside an evidence panel showing the passage in its judgment, with the quote or search terms highlighted, its verified pages and a link to GhaLII. The search, its filters and the open passage stay in the URL, and the layout works down to phone width.
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

### Requirements
- **Python 3.13** with [Poetry](https://python-poetry.org/), **Node 22**, and **Docker** with Compose v2 (for Postgres).
- **[Ollama](https://ollama.com)** with the answer model, for answers only: search works without it.
- **Tesseract and poppler** (`brew install tesseract poppler`), only to OCR scanned PDFs.
- **Disk:**
  - the export: about 4.7 GB
  - the database once built: about 1.8 GB
  - the pinned models: about 930 MB
  - the answer model, in Ollama
- **The corpus:** the legacy export in `output/` (not in git), or a database backup made with `scripts/backup.sh`. A fresh clone has neither: the tests still run (they use a synthetic fixture), but search finds nothing until a corpus is loaded.

### Set up
```bash
poetry install
npm --prefix ui install

cp .env.example .env              # set POSTGRES_PASSWORD (the same, percent-encoded, in DATABASE_URL) and AUTH_HASH_SECRET
cp ui/.env.example ui/.env.local  # uncomment UI_INSECURE_COOKIES=1: plain http on 127.0.0.1 can't keep Secure cookies

docker compose up -d postgres     # pgvector/pgvector:pg17 on 127.0.0.1:5434 (EJUDGMENT_DB_PORT changes it)
poetry run alembic upgrade head
poetry run python -m ejudgment.worker.models fetch-models   # once: pinned tokenizer, embedder, reranker, NLI (~930 MB)
ollama pull gemma4:latest                                   # the default answer model (OLLAMA_CHAT_MODEL)
```

### Load the corpus
Use one of the following.

**From the export** (idempotent: a re-run only redoes what changed):
```bash
poetry run python -m ejudgment.worker.ingest legacy --source output/pdf/judgments_with_text.db --pdf-base-dir .   # add --dry-run to only count
poetry run python -m ejudgment.worker.extract --pdf-base-dir .   # Word conversion + OCR (~45 min for the 74 scans)
poetry run python -m ejudgment.worker.chunk
poetry run python -m ejudgment.worker.embed                      # ~26 min on an Apple M2 Pro (GPU), much longer on CPU
```

**From a backup:** the restore must go into an empty database. With a fresh Postgres volume, skip `alembic upgrade head` above, run `scripts/restore.sh <dump> ejudgment --into-empty`, then run `alembic upgrade head` (see `docs/operations.md`, "First run").

### Run
```bash
poetry run python -m ejudgment.worker.users create --email you@example.org --name "You" --role admin --generate   # prints the password once
poetry run uvicorn ejudgment.api.main:app          # API on 127.0.0.1:8000 (loads the models at start)
npm --prefix ui run dev                            # UI on http://127.0.0.1:3000 (loopback only)
```
Open http://127.0.0.1:3000 and sign in. To check from the terminal:
- `curl http://127.0.0.1:8000/healthz`
- `poetry run python -m ejudgment.worker.search "adverse possession"`
- `poetry run python -m ejudgment.worker.ask "When may a landlord recover possession?"`

## Deployment

One machine with Docker Compose: Postgres, a migration step, the API, the UI and a Caddy reverse proxy (HTTPS for a domain, security headers). Ollama runs on the host and the model cache is mounted read-only. Only Caddy is reachable from outside; Postgres is published on `127.0.0.1` only.

```bash
cp .env.example .env    # secrets; SITE_ADDRESS=your.domain for HTTPS (see the checklist)
docker compose up -d --build
docker compose run --rm worker python -m ejudgment.worker.users create --email you@example.org --name "You" --role admin --generate
```

Locally the stack is at `http://127.0.0.1:8080` (with `UI_INSECURE_COOKIES=1`); on a server, set `SITE_ADDRESS` to your domain and follow the TLS checklist. It needs about 6 GB of memory for the containers. The models run on CPU there: search takes 1–3 s, and answers depend on Ollama on the host.

**Loading the corpus:** restore a backup into the database before the rest of the stack starts, or build it from the export with `docker compose run --rm worker …`. The export is mounted read-only at `/data/output`.

`docs/operations.md` covers:
- the first run, including loading the corpus or restoring a backup
- the TLS checklist and upgrades
- daily backups (`scripts/backup.sh`), retention and a monthly restore drill (`scripts/restore_drill.sh`)
- monitoring, capacity and data protection

**Free hosting for testing:** `docs/deploy-free.md` covers an Oracle Cloud Always Free Arm server, and Cloudflare Tunnel (from that server or your own Mac, no open ports; `docker compose --profile tunnel up -d` with `TRUSTED_PROXIES=private_ranges`).

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
| `ui/` | Next.js 16 app: search and ask beside an evidence panel, sign-in, gold-set review (see `ui/README.md`) |
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

Measured on questions written by engineers and not yet reviewed by a lawyer, so the figures are **provisional**. Retrieval uses all 60 draft questions; the answer figures are from the first 20. Full figures and run IDs are in `AGENTS.md`.

| Measure | Result |
| ------- | ------ |
| Retrieval, hybrid (Recall@20 / MRR@10) | 0.88 / 0.56, with reranking 0.88 / 0.63; citation and case-name questions 1.0 |
| Answers, gemma4 (local) | 94% answered, 53% cite a gold case, all 3 out-of-scope questions abstained, 42 of 43 claims verified |
| Answers, gpt-6-luna (OpenAI pilot) | 88% answered, 59% cite a gold case, all out-of-scope abstained, 32 of 37 claims verified, $0.0068 for 20 questions |

**Next:** a lawyer reviews the 60 draft questions (and adds their own) before anyone tunes retrieval, prompts or verification.

**Comparison with GhaLII's own search:** `docs/benchmark-ghalii.md` runs the same questions through both (GhaLII searched by hand, as its terms require; `worker.benchmark_ghalii` prepares the sheets and scores them). Not run yet.

### How lawyers review the gold set
1. An admin creates a reviewer account: `worker.users create --email … --role reviewer --generate`, and loads the questions: `worker.gold import` (run it again after `evals/gold.jsonl` gains questions; existing ones are left alone).
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
  - `deploy`: Compose config, `bash -n` and shellcheck on `scripts/`, both image builds, an image smoke test, and `scripts/check_proxy_stream.sh`. That last check runs the real Caddyfile in front of a stand-in UI, and fails if answers stop streaming or if Cancel no longer reaches the server.
  - Python dependencies are installed with CPU-only torch by `scripts/install-python-deps.sh`, the same script the Docker image uses.
- **Tests never touch the network:** a socket guard allows loopback only, and the models and LLM are faked.
- **Drift guards** fail when the OpenAPI snapshot, the generated UI types, `.env.example` or the evaluation settings fall out of date.
- **Shell scripts** must pass shellcheck in both `koalaman/shellcheck:stable` and `v0.9.0` (CI's older version reports some findings under other codes), and stay bash 3.2 compatible for macOS:
  ```bash
  docker run --rm -v "$PWD":/mnt -w /mnt koalaman/shellcheck:stable -x scripts/*.sh
  ```
- **After an API schema change:** `poetry run python -m ejudgment.api.export_openapi && npm --prefix ui run gen:api`.
- **Contributing:** read `AGENTS.md` first (it is binding), keep changes PR-sized, and leave commits to the repository owner.

## Troubleshooting

| Symptom | Cause and fix |
| ------- | ------------- |
| `docker compose` says `Set POSTGRES_PASSWORD in .env` | Copy `.env.example` to `.env` and set it. A development database created before the password became required uses `ejudgment` (see `docs/operations.md`). |
| `password authentication failed` from the CLI or tests | `DATABASE_URL` in `.env` must hold the same password as `POSTGRES_PASSWORD`, percent-encoded (`@` → `%40`). |
| Port 5434 already in use | Set `EJUDGMENT_DB_PORT` in `.env`, and the same port in `DATABASE_URL`. |
| Sign-in succeeds but you land back on `/login` | The session cookie is `Secure`, and some browsers drop Secure cookies over plain http. Set `UI_INSECURE_COOKIES=1` (in `ui/.env.local`, or in `.env` for Compose) for local http use only, never on a public address. |
| Ask says the answer model is not available (`llm_unavailable`) | Ollama isn't running or lacks the model: `ollama serve`, `ollama pull gemma4:latest`. Search still works. |
| Answers are switched off (`verifier_unavailable`) | The NLI model is missing from the Hugging Face cache: run `worker.models fetch-models`. |
| Search says "Results may be incomplete" | Vectors are missing or out of date for some chunks: run `worker.embed`. Without the embedding model, search falls back to keywords and says so. |
| Integration tests are skipped | Postgres isn't reachable. Start it with `docker compose up -d postgres`; `EJUDGMENT_REQUIRE_DB=1` makes this a failure instead. |
| The first search after a restart is slow | Postgres' cache is cold. Queries of only very common words ("the court") take about 0.5 s even when warm, because every match is ranked. |

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
