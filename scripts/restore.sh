#!/usr/bin/env bash
# Restore a backup into a NEW database; the live one is never overwritten.
#   scripts/restore.sh <dump> [target_db]       default target: ejudgment_restore_<timestamp>
#   scripts/restore.sh <dump> ejudgment --into-empty
#       only on a new machine: restores into the live database name if it has no tables yet
#       (start postgres alone first: docker compose up -d postgres)
# The checksum file next to the dump is verified first.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh

dump="${1:?usage: scripts/restore.sh <dump> [target_db] [--into-empty]}"
target="${2:-ejudgment_restore_$(date -u +%Y%m%d_%H%M%S)}"
mode="${3:-}"

[[ "$target" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "invalid database name: $target" >&2; exit 2; }
[[ -f "$dump" && -f "${dump}.sha256" ]] || { echo "need $dump and ${dump}.sha256" >&2; exit 2; }
(cd "$(dirname "$dump")" && sha256_check "$(basename "$dump").sha256" >/dev/null) \
  || { echo "checksum mismatch: $dump" >&2; exit 3; }

if [[ "$target" == "ejudgment" ]]; then
  [[ "$mode" == "--into-empty" ]] || {
    echo "refusing to restore over the live database; pass --into-empty on a new machine" >&2
    exit 2
  }
  tables="$(psql_value ejudgment "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")"
  [[ "$tables" == "0" ]] || { echo "the live database is not empty ($tables tables)" >&2; exit 2; }
else
  pg createdb -U ejudgment "$target"   # fails if it already exists
fi

pg pg_restore -U ejudgment -d "$target" --no-owner --exit-on-error <"$dump"
echo "restored into database: $target"
table_counts "$target"
if [[ "$target" != "ejudgment" ]]; then
  cat <<NEXT
To switch the application over (after checking the data above):
  1. docker compose stop api ui caddy
  2. ALTER DATABASE ejudgment RENAME TO ejudgment_old_<date>;  ALTER DATABASE ${target} RENAME TO ejudgment;
     (psql as ejudgment, connected to the 'postgres' database)
  3. docker compose up -d
NEXT
fi
