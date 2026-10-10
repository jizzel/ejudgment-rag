# Operations: running E-Judgment research on one machine

This deploys the research service with Docker Compose. Postgres (with pgvector), the API, the UI and a Caddy reverse proxy run in containers. Ollama runs on the host, so questions never leave the machine. The deployment is **non-commercial**. Every page credits GhaLII (CC BY-NC 4.0), as the source licence requires. See `AGENTS.md`, "Source rights".

```text
browser ── Caddy (only published service: HTTP/HTTPS) ── ui (Next.js) ── api (FastAPI) ── postgres
                                                                         │
                                                       host: Ollama (answers), HF model cache (read-only)
```

## Existing development databases
The Compose file now requires `POSTGRES_PASSWORD`. A development database created before this change was initialised with the password `ejudgment`. Either put `POSTGRES_PASSWORD=ejudgment` in `.env`, or change the password (`ALTER USER ejudgment PASSWORD '…'`) and update both `POSTGRES_PASSWORD` and `DATABASE_URL`. Recreating the container (`docker compose up -d postgres`) also moves its port to `127.0.0.1` only; the data volume is kept.

## Requirements
- Docker with Compose v2, and about 6 GB of free memory for the containers. Postgres uses a 1 GB buffer cache; the API loads the embedding, reranker and NLI models on CPU.
- Ollama on the host, with the answer model pulled (`ollama pull gemma4:latest`, or whatever `OLLAMA_CHAT_MODEL` names).
- The pinned model weights in the host's Hugging Face cache. Fetch them once with `poetry run python -m ejudgment.worker.models fetch-models`, or copy `~/.cache/huggingface` from another machine. The containers mount it read-only and never download.
- The corpus, either:
  - the legacy export (`output/pdf/judgments_with_text.db` plus the downloaded files under `output/`), loaded with the worker; or
  - a database backup made with `scripts/backup.sh`.

## First run
1. **Configure.** Copy the template and fill in the secrets:
   ```bash
   cp .env.example .env
   python -c "import secrets; print(secrets.token_urlsafe(48))"   # use for AUTH_HASH_SECRET
   ```
   - Set `POSTGRES_PASSWORD` and `AUTH_HASH_SECRET`. Any characters work for the containers, which encode the password themselves. Two caveats:
     - In `.env`, a password containing `$` must be wrapped in single quotes (`POSTGRES_PASSWORD='a$b'`) or written with `$$`. Otherwise Compose reads `$b` as a variable and silently drops it.
     - The host-side `DATABASE_URL` (CLI, tests) needs the password percent-encoded, e.g. `@` → `%40`, `/` → `%2F`.
   - Local use: keep `SITE_ADDRESS=:80` and set `UI_INSECURE_COOKIES=1`. The site is then at `http://127.0.0.1:8080`.
   - Server use: see the TLS checklist below.

   `POSTGRES_PASSWORD` is applied when the database volume is first created. To change it later, use `ALTER USER ejudgment PASSWORD '…'` and update `.env`.
2. **Load the corpus and start.** Follow **one** path, in this order.

   **a) From a backup.** Restore into the empty database **before** the rest of the stack starts. `migrate` would otherwise create the tables first, and `--into-empty` then (rightly) refuses.
   ```bash
   docker compose up -d postgres          # Postgres alone: nothing else touches the database yet
   scripts/restore.sh backups/ejudgment-<timestamp>.dump ejudgment --into-empty
   docker compose up -d --build           # migrate (brings the restored schema up to date), api, ui, caddy
   ```

   **b) From the legacy export.** Start everything, then build the index with the worker. This takes hours on CPU; embedding all chunks took 26 minutes on an Apple M2 Pro GPU.
   ```bash
   docker compose up -d --build           # migrate creates the empty schema
   docker compose run --rm worker python -m ejudgment.worker.ingest legacy \
     --source /data/output/pdf/judgments_with_text.db --pdf-base-dir /data
   docker compose run --rm worker python -m ejudgment.worker.extract --pdf-base-dir /data
   docker compose run --rm worker python -m ejudgment.worker.chunk
   docker compose run --rm worker python -m ejudgment.worker.embed
   ```
   `docker compose ps` should then show postgres, api, ui and caddy as healthy.

   *Started the whole stack before restoring?* On a new machine with nothing to keep, start over:
   - `docker compose down`
   - `docker compose up -d postgres`
   - drop and recreate the database: `docker compose exec postgres dropdb -U ejudgment ejudgment && docker compose exec postgres createdb -U ejudgment ejudgment`
   - then continue with path a). Never do this on a machine whose data you need.
3. **Create the first account.** Access is by invitation only:
   ```bash
   docker compose run --rm worker python -m ejudgment.worker.users create \
     --email you@example.org --name "Your Name" --role admin --generate
   ```
   The generated password is printed once. Other commands: `list`, `disable`, `enable`, `reset-password`, `revoke-sessions`.

## TLS and a public address (checklist)
- [ ] A DNS `A`/`AAAA` record for your domain points at the machine.
- [ ] Ports 80 and 443 are open to the internet. Caddy needs 80 for the certificate challenge and redirects it to HTTPS.
- [ ] `.env` has `SITE_ADDRESS=research.example.org`, `HTTP_BIND=0.0.0.0`, `HTTP_PORT=80` and `HTTPS_PORT=443`.
- [ ] `UI_INSECURE_COOKIES` is **removed** (cookies must be `Secure`).
- [ ] `AUTH_HASH_SECRET` is set, so the login lockout survives restarts.
- [ ] `POSTGRES_PASSWORD` is long and random. Postgres is published only on `127.0.0.1`.
- [ ] Apply with `docker compose up -d`. Caddy obtains and renews certificates automatically. Check `https://research.example.org/login`.

Caddy adds HSTS on HTTPS, `X-Content-Type-Options`, `X-Frame-Options`/`frame-ancestors 'none'`, `Referrer-Policy` and a restrictive `Permissions-Policy` (`docker/Caddyfile`).

## Upgrades
```bash
git pull
docker compose up -d --build     # migrate runs before the new api starts
```
- Take a backup first: `scripts/backup.sh`.
- Model or chunker changes need the worker steps the release notes name (for example `worker.chunk`, then `worker.embed`). Both are idempotent and only redo what changed.

## Daily jobs (cron on the host)
```cron
# Backups at 02:30, retention at 03:00, a restore drill on the 1st of each month.
30 2 * * *  cd /srv/ejudgment && scripts/backup.sh >>/var/log/ejudgment-backup.log 2>&1
0 3 * * *   cd /srv/ejudgment && docker compose run --rm worker python -m ejudgment.worker.retention >>/var/log/ejudgment-retention.log 2>&1
0 4 1 * *   cd /srv/ejudgment && scripts/restore_drill.sh >>/var/log/ejudgment-drill.log 2>&1
```
- **Backups:** a compressed `pg_dump` with a SHA-256 checksum. The newest `BACKUP_KEEP` (14) are kept in `backups/` with mode 600. **Copy them off the machine** (encrypted), because a backup on the same disk doesn't survive that disk.
- **Retention:** deletes search and question audit rows after 90 days, security events after 365, ended sessions after 7, and usage rows after 730. Evaluation runs are kept. Raw query text is never stored unless `AUDIT_STORE_RAW_QUERIES=true`, which needs a documented retention reason first.
- **Restore drill:** backs up, restores into a scratch database, compares row counts per table and the schema revision with the live database, then drops the scratch copy. It fails loudly on any difference. Writes made during the drill show up as differences, so run it when the service is quiet.

## Restore
- If a restore fails partway (a damaged dump, a full disk), `restore.sh` cleans up after itself: it drops the new database it created, or empties again the database it had found empty. Fix the cause and run it again.
- `scripts/restore.sh <dump>` verifies the checksum and restores into a **new** database (`ejudgment_restore_<yyyymmdd_hhmmss>`). It never overwrites the live one. It prints the row counts and the switch-over steps:
  - stop api, ui and caddy
  - rename the databases
  - start again
- On a new machine, `scripts/restore.sh <dump> ejudgment --into-empty` restores into the live database name, but only if that database has no tables yet.

## Monitoring
- **Health:** `docker compose ps` reports container health. The API exposes `GET /healthz` inside the network, and the UI answers `/login`.
- **Logs:** `docker compose logs -f api ui caddy`. Sign-in failures and lockouts are in the `auth_events` table, and every search and question is in `query_audit` (hashed text, with the user).
- **What a user sees when something is down:**
  - Ollama down: answers fail with "answer model not available", and search keeps working.
  - Database down: every page shows "database not reachable".

## Capacity and performance
- **Models run on CPU in the containers**, because Docker can't use Apple's GPU. They are bge-small for query embeddings, MiniLM for reranking and DeBERTa for answer checking. Measured on an Apple M2 Pro (Docker VM with 8 GB), on the full corpus restored from a backup:
  - search: 1.4–3.0 s (the first query after start is the slowest), against about 0.2 s natively on the GPU; most of it is reranking
  - a cited answer: 49 s in total, of which 35 s is gemma4 on the host and about 14 s is CPU retrieval plus answer checking
- **Ollama on the host uses the GPU.** Keep its model loaded (`OLLAMA_KEEP_ALIVE`) to avoid a cold start on the first question.
- **Memory:** Postgres has a 1 GB buffer cache (`docker-compose.yml`). A smaller machine can lower it at the cost of slower cold queries.

## Data, privacy and rights
- **What the database holds:**
  - the corpus and its derived data (chunks, embeddings), under GhaLII's CC BY-NC 4.0 licence
  - accounts with Argon2 password hashes
  - session token hashes
  - security events with hashed emails and IP addresses
  - search and question audit with hashed queries
- Backups hold the same, so treat them as confidential.
- Keep the deployment **non-commercial**, with GhaLII attribution on every page (built in). New judgments may only come from GhaLII's official API or a licence, never from scraping.
- **OpenAI is off by default.** Enabling it (`OPENAI_ENABLED=true`, `LLM_PROVIDER=openai`) sends users' questions and the retrieved passages to OpenAI. Tell users first, and set a project budget in the OpenAI dashboard as well as the app's own limits.
