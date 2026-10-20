#!/usr/bin/env bash
# © 2026 Andy217Ace
# Update the deployed code: sudo bash /opt/tabela/app/deploy/update.sh [branch]
# Default branch: the one currently checked out (feat/app now, main after the merge).
set -euo pipefail

APP_DIR=/opt/tabela/app
VENV=/opt/tabela/venv
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }
BRANCH="${1:-$(git -C "$APP_DIR" rev-parse --abbrev-ref HEAD)}"

git -C "$APP_DIR" fetch --prune origin "$BRANCH"
git -C "$APP_DIR" checkout -B "$BRANCH" "origin/$BRANCH"
git -C "$APP_DIR" log -1 --oneline
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"
if ! cmp -s "$APP_DIR/deploy/tabela.service" /etc/systemd/system/tabela.service; then
    install -m 644 "$APP_DIR/deploy/tabela.service" /etc/systemd/system/tabela.service
    systemctl daemon-reload
fi
systemctl restart tabela

for i in $(seq 1 90); do
    if curl -fs http://127.0.0.1:8000/api/health | grep -q '"ok":true'; then
        echo "healthy after ~$((i * 2)) s"; exit 0
    fi
    sleep 2
done
echo "not healthy after 180 s; see: journalctl -u tabela -n 100" >&2
exit 1
