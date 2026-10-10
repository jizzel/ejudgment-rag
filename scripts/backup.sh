#!/usr/bin/env bash
# Back up the database: a compressed pg_dump with a SHA-256 checksum, newest BACKUP_KEEP kept.
#   scripts/backup.sh [backup_dir]          (default: BACKUP_DIR from the environment or .env,
#                                            else backups/; mode 700, gitignored)
# BACKUP_KEEP (environment or .env, default 14) is how many dumps are kept.
# Backups hold accounts (password hashes), audit records and corpus-derived data: keep them
# private and encrypted at rest; never share them publicly.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh

dir="${1:-$BACKUP_DIR}"
keep="$BACKUP_KEEP"
# Checked before anything runs: a bad value must not delete backups.
[[ "$keep" =~ ^[1-9][0-9]*$ ]] || { echo "BACKUP_KEEP must be a positive integer: '$keep'" >&2; exit 2; }
umask 077
mkdir -p "$dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
name="ejudgment-${stamp}.dump"

pg pg_dump -U ejudgment -d ejudgment --format=custom --compress=6 >"${dir}/${name}.partial"
mv "${dir}/${name}.partial" "${dir}/${name}"
(cd "$dir" && sha256 "$name" >"${name}.sha256")

# Keep the newest $keep backups. Names carry UTC timestamps, so name order is time order
# (oldest first in the glob) and file modification times do not matter.
dumps=("$dir"/ejudgment-*.dump)
excess=$((${#dumps[@]} - keep))
for ((i = 0; i < excess; i++)); do
  rm -f -- "${dumps[i]}" "${dumps[i]}.sha256"
done

echo "${dir}/${name}"
