#!/usr/bin/env bash
# Push the site and the runtime data to the server.
#
#   bash deploy/sync.sh ubuntu@203.0.113.10
#
# Run it from the repo root, in Git Bash or WSL. Safe to re-run — rsync only
# sends what changed, so after the first upload it takes seconds.
#
# What is deliberately NOT sent (build artifacts the running site never opens):
#   data/crops    1.6 GB  per-question crops; compose works from data/raw plus
#                         the stored rectangles, never from these
#   data/debug    991 MB  segmentation check images
#   data/output   897 MB  booklets from CLI runs; the site writes to a temp dir
#   data/batches          classification workflow only
#   *.bak-*               local database backups
# That takes the upload from about 4.4 GB down to roughly 790 MB.

set -euo pipefail

HOST="${1:?usage: bash deploy/sync.sh user@server-ip [dest] [ssh-key-path]}"
DEST="${2:-/srv/prepwithtee}"
SSH_KEY="${3:-}"

if [[ ! -f "website/app.py" ]]; then
  echo "run this from the repo root (website/app.py not found)" >&2
  exit 1
fi

# Build ssh option for rsync if a key path is provided
SSH_OPT=()
[ -n "$SSH_KEY" ] && SSH_OPT=(-e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no")

echo "==> code and taxonomy"
rsync -avz "${SSH_OPT[@]}" --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  pipeline website taxonomy requirements.txt CLAUDE.md \
  "$HOST:$DEST/"

echo "==> paper archive (the big one — expect a while on the first run)"
rsync -avz "${SSH_OPT[@]}" --info=progress2 \
  data/raw "$HOST:$DEST/data/"

echo "==> index database"
# --inplace avoids needing a second 21 MB of free space while it transfers.
rsync -avz "${SSH_OPT[@]}" --inplace data/index.db "$HOST:$DEST/data/"

echo "==> resources / notes (published on the site's Resources page)"
# No --delete: the tutor may also have added files directly on the server.
rsync -avz "${SSH_OPT[@]}" data/resources "$HOST:$DEST/data/"

cat <<EOF

Done. On the server:

    sudo systemctl restart prepwithtee
    curl -s localhost:8017/api/health

The health check should report the paper count and archive_present: true.
EOF
