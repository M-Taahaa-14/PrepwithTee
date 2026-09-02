#!/bin/bash
# Nightly backup: Supabase Postgres dump + homework uploads.
#
# WHAT THIS PROTECTS AGAINST
#   * a bad migration, an accidental DELETE, or table corruption  -> yes
#   * Supabase losing your project                                -> yes
#   * this VM's disk dying                                        -> ONLY once
#     BACKUP_REMOTE is configured; a backup that lives solely on the machine
#     it is backing up is not a backup.
#
# The homework uploads are the part with no other copy anywhere: student
# worksheets live only on this disk, not in Supabase.
#
# Installed at /srv/prepwithtee/deploy/backup.sh, invoked by
# /etc/cron.d/prepwithtee.
set -euo pipefail

ENV_FILE=/etc/prepwithtee.env
APP_DIR=/srv/prepwithtee
DEST=/srv/backups
KEEP_DAYS=14
STAMP=$(date +%F)

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

mkdir -p "$DEST"

fail() { echo "$(date -Is) BACKUP FAILED: $*" >&2; exit 1; }

# ── 1. Database ──────────────────────────────────────────────────────────────
# --no-owner/--no-acl so the dump restores into a fresh project without needing
# the original role names to exist.
if [[ -z "${DATABASE_URL:-}" ]]; then
    fail "DATABASE_URL not set"
fi
DB_OUT="$DEST/db-$STAMP.sql.gz"
pg_dump --no-owner --no-acl "$DATABASE_URL" | gzip -9 > "$DB_OUT.partial" \
    || fail "pg_dump failed"
mv "$DB_OUT.partial" "$DB_OUT"

# A dump that is suspiciously small usually means auth failed and pg_dump wrote
# only a header. Catch that here rather than discovering it during a restore.
SIZE=$(stat -c%s "$DB_OUT")
if (( SIZE < 2048 )); then
    fail "database dump is only ${SIZE} bytes — refusing to treat it as valid"
fi

# ── 2. Homework uploads ──────────────────────────────────────────────────────
UP_DIR="$APP_DIR/data/uploads"
UP_OUT="$DEST/uploads-$STAMP.tar.gz"
if [[ -d "$UP_DIR" ]]; then
    tar czf "$UP_OUT.partial" -C "$APP_DIR/data" uploads || fail "uploads tar failed"
    mv "$UP_OUT.partial" "$UP_OUT"
fi

# ── 3. Off-box copy ──────────────────────────────────────────────────────────
# Set BACKUP_REMOTE in /etc/prepwithtee.env to an rclone remote
# (e.g. "b2:prepwithtee-backups") once cloud storage is configured. Until then
# this is a local-disk-only backup and the VM remains a single point of failure.
if [[ -n "${BACKUP_REMOTE:-}" ]] && command -v rclone >/dev/null; then
    rclone copy "$DEST" "$BACKUP_REMOTE" --include "*-$STAMP.*" \
        || echo "$(date -Is) WARNING: off-box copy failed, local copy kept" >&2
else
    echo "$(date -Is) NOTE: BACKUP_REMOTE unset — backups are local only" >&2
fi

# ── 4. Retention ─────────────────────────────────────────────────────────────
find "$DEST" -name 'db-*.sql.gz'      -mtime +$KEEP_DAYS -delete
find "$DEST" -name 'uploads-*.tar.gz' -mtime +$KEEP_DAYS -delete
find "$DEST" -name '*.partial'        -mtime +1          -delete

echo "$(date -Is) backup ok: $(du -h "$DB_OUT" | cut -f1) db$(
    [[ -f "$UP_OUT" ]] && echo ", $(du -h "$UP_OUT" | cut -f1) uploads")"
