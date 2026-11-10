#!/usr/bin/env bash
# Copies Money Radar's nightly database snapshots to a second location, keeping 14 days there too.
#
# The service already writes a compressed snapshot to data/backups/ every night (03:30 Lagos).
# This script ships those off the VPS, so losing the server doesn't lose your history.
#
# One-time setup:
#   1. Install rclone (https://rclone.org/install/) and run `rclone config` to add a remote,
#      e.g. Google Drive named "gdrive".
#   2. Put BACKUP_REMOTE=gdrive:money-radar-backups in .env
#   3. Add to crontab (crontab -e), after the nightly snapshot:
#        45 3 * * * /home/salam/money-radar/deploy/backup.sh >> /home/salam/money-radar/data/backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."
REMOTE="${BACKUP_REMOTE:-$(grep -E '^BACKUP_REMOTE=' .env 2>/dev/null | cut -d= -f2- || true)}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"

if [[ -z "${REMOTE}" ]]; then
  echo "$(date -u +%FT%TZ) BACKUP_REMOTE is not set; local snapshots only (data/backups)."
  exit 0
fi
if ! command -v rclone >/dev/null; then
  echo "$(date -u +%FT%TZ) rclone is not installed; see the comments at the top of this script." >&2
  exit 1
fi

rclone copy data/backups "${REMOTE}" --include "radar-*.db.gz"
rclone delete "${REMOTE}" --min-age "${KEEP_DAYS}d" --include "radar-*.db.gz"
echo "$(date -u +%FT%TZ) backups copied to ${REMOTE}"
