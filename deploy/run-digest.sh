#!/bin/bash
# Daily homework reminder emails.
#
# cron does NOT inherit the systemd unit's EnvironmentFile, so the credentials
# have to be sourced explicitly here. Without this the script starts fine,
# finds no SMTP_USER, and silently sends nothing — which looks identical to
# "nobody had homework due".
#
# Installed at /srv/prepwithtee/deploy/run-digest.sh, invoked by
# /etc/cron.d/prepwithtee.
set -euo pipefail

ENV_FILE=/etc/prepwithtee.env
APP_DIR=/srv/prepwithtee

if [[ ! -r "$ENV_FILE" ]]; then
    echo "$(date -Is) FATAL: cannot read $ENV_FILE" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

cd "$APP_DIR"
exec "$APP_DIR/.venv/bin/python" -m website.scripts.homework_digest "$@"
