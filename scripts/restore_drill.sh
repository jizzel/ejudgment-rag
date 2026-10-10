#!/usr/bin/env bash
# Restore drill: back up, restore into a scratch database, compare row counts and the schema
# revision with the live database, then drop the scratch database. Exit 1 on any difference.
#   scripts/restore_drill.sh [backup_dir]
# Run it on a schedule (e.g. monthly) and after changing the backup setup. Compare at a quiet
# time: rows written between the backup and the comparison show up as differences.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh

dump="$(scripts/backup.sh "${1:-$BACKUP_DIR}")"
scratch="ejudgment_drill_$(date -u +%Y%m%d_%H%M%S)"
trap 'pg dropdb -U ejudgment --if-exists "$scratch" >/dev/null 2>&1 || true' EXIT

scripts/restore.sh "$dump" "$scratch" >/dev/null
live="$(table_counts ejudgment)"
restored="$(table_counts "$scratch")"
if diff <(echo "$live") <(echo "$restored"); then
  echo "restore drill OK: $dump"
  echo "$restored"
else
  echo "restore drill FAILED: the restored copy differs from the live database (above)" >&2
  exit 1
fi
