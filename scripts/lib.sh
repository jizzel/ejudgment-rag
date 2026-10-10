#!/usr/bin/env bash
# Shared helpers for the backup scripts (sourced, not run).

env_value() { # env_value KEY: the last KEY=value in ${ENV_FILE:-.env}, quotes removed
  # Only the requested key is read: .env is never sourced (other values may hold characters
  # that the shell would interpret).
  local file="${ENV_FILE:-.env}"
  [[ -f "$file" ]] || return 0
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$file" | tail -n 1 \
    | sed -e "s/[[:space:]]*\$//" -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'\$/\1/"
}

# Backup settings: an exported variable wins, then .env, then the default.
BACKUP_DIR="${BACKUP_DIR:-$(env_value BACKUP_DIR)}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
BACKUP_KEEP="${BACKUP_KEEP:-$(env_value BACKUP_KEEP)}"
BACKUP_KEEP="${BACKUP_KEEP:-14}"

# The Compose command, e.g. COMPOSE="docker compose -p ejudgment-verify" for another project.
read -r -a COMPOSE_CMD <<<"${COMPOSE:-docker compose}"

pg() { # pg <command> [args...]: run a Postgres client tool in the postgres container
  "${COMPOSE_CMD[@]}" exec -T postgres "$@"
}

psql_value() { # psql_value <database> <sql>: one value, no headers
  pg psql -U ejudgment -d "$1" -Atq -v ON_ERROR_STOP=1 -c "$2"
}

sha256() { # sha256 <file>: "<hash>  <name>" in the format sha256sum -c expects
  if command -v sha256sum >/dev/null; then sha256sum "$1"; else shasum -a 256 "$1"; fi
}

sha256_check() { # sha256_check <checksum file> (run in its directory)
  if command -v sha256sum >/dev/null; then sha256sum -c "$1"; else shasum -a 256 -c "$1"; fi
}

# Tables compared by the restore drill (row counts) besides the Alembic revision.
# Every application table (a test keeps this in step with the SQLAlchemy models).
DRILL_TABLES=(judgments document_sources document_pages chunks chunk_embeddings model_registry
  users sessions auth_events query_audit llm_usage_ledger evaluation_runs ingestion_jobs
  gold_questions gold_question_history
  ingestion_issues)

table_counts() { # table_counts <database>: "table=count" lines; fails if any query fails
  local table value
  for table in "${DRILL_TABLES[@]}"; do
    # Assigned first: a failure inside "$(...)" used as an echo argument would be ignored.
    value="$(psql_value "$1" "SELECT count(*) FROM ${table}")"
    echo "${table}=${value}"
  done
  value="$(psql_value "$1" "SELECT version_num FROM alembic_version")"
  echo "alembic=${value}"
}
