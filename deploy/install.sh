#!/usr/bin/env bash
# © 2026 Andy217Ace
# Idempotent install of Tabela Gara de Nord on Ubuntu 24.04. Run as root:
#   sudo bash install.sh [branch]        (default branch: feat/app; later: main)
# Never prints the VAPID private key. Never enables ufw (the cloud NSG is the firewall).
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Andy217Ace/tabela-gara-de-nord.git}"
BRANCH="${1:-${BRANCH:-feat/app}}"
APP_DIR=/opt/tabela/app
VENV=/opt/tabela/venv
DATA_DIR=/var/lib/tabela
ENV_FILE=/etc/tabela.env
SITE=/etc/nginx/sites-available/tabela
LIMITS=/etc/nginx/conf.d/tabela-limits.conf
BACKUP_DIR="/root/backup-$(date +%F)"

[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }

echo "== packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q tesseract-ocr tesseract-ocr-ron python3-venv git curl sqlite3

echo "== service user and directories"
id tabela >/dev/null 2>&1 || useradd --system --home-dir "$DATA_DIR" --no-create-home \
    --shell /usr/sbin/nologin tabela
install -d -o root -g root -m 755 /opt/tabela
install -d -o tabela -g tabela -m 750 "$DATA_DIR"

echo "== code ($BRANCH)"
if [ ! -d "$APP_DIR/.git" ]; then
    git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
else
    git -C "$APP_DIR" fetch --prune origin "$BRANCH"
    git -C "$APP_DIR" checkout -B "$BRANCH" "origin/$BRANCH"
fi
git -C "$APP_DIR" log -1 --oneline

echo "== venv"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "== env file"
if [ ! -f "$ENV_FILE" ]; then
    umask 077
    cat > "$ENV_FILE" <<ENV
# Tabela Gara de Nord - runtime settings (root:root 600; not in git)
DB_PATH=$DATA_DIR/tabela.db
LAST_IMAGE_PATH=$DATA_DIR/last.jpg
POLLER_ENABLED=1
VAPID_SUBJECT=https://tabelacfr.ddns.net
ENV
fi
chown root:root "$ENV_FILE"
chmod 600 "$ENV_FILE"

# Rewrite the env file atomically: temp file next to it (same perms) + mv. Every line we
# write ends with a newline, so nothing is ever glued to the previous last line.
env_rewrite() {   # stdin: the new content
    local tmp
    tmp="$(mktemp "$ENV_FILE.XXXXXX")"
    chmod 600 "$tmp"
    cat > "$tmp"
    chown root:root "$tmp"
    mv -f "$tmp" "$ENV_FILE"
}
env_lines_without() {  # print ENV_FILE without the given keys, last line newline-terminated
    local pat="$1"
    grep -v -E "^(${pat})=" "$ENV_FILE" | awk '{ print }' || true   # awk ends every line with \n
}

# older installs: settings added since
if ! grep -q '^LAST_IMAGE_PATH=' "$ENV_FILE"; then
    { env_lines_without 'LAST_IMAGE_PATH'; echo "LAST_IMAGE_PATH=$DATA_DIR/last.jpg"; } | env_rewrite
    echo "env: added LAST_IMAGE_PATH"
fi

# VAPID: raw P-256 private key, base64url (what py_vapid/pywebpush accept); public key =
# uncompressed point. Never regenerated when a private key exists (that would invalidate
# every push subscription); a missing public key is derived from the private one.
if ! grep -q '^VAPID_PRIVATE_KEY=.\+' "$ENV_FILE"; then
    { env_lines_without 'VAPID_PRIVATE_KEY|VAPID_PUBLIC_KEY'
      "$VENV/bin/python" - <<'PY'
import base64
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization as s
k = ec.generate_private_key(ec.SECP256R1())
b = lambda x: base64.urlsafe_b64encode(x).rstrip(b"=").decode()
print("VAPID_PRIVATE_KEY=" + b(k.private_numbers().private_value.to_bytes(32, "big")))
print("VAPID_PUBLIC_KEY=" + b(k.public_key().public_bytes(s.Encoding.X962, s.PublicFormat.UncompressedPoint)))
PY
    } | env_rewrite
    echo "VAPID keys generated"
elif ! grep -q '^VAPID_PUBLIC_KEY=.\+' "$ENV_FILE"; then
    { env_lines_without 'VAPID_PUBLIC_KEY'
      ENV_FILE="$ENV_FILE" "$VENV/bin/python" - <<'PY'
import base64, os
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization as s
raw = [l.split("=", 1)[1].strip() for l in open(os.environ["ENV_FILE"])
       if l.startswith("VAPID_PRIVATE_KEY=")][-1]
d = int.from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), "big")
pub = ec.derive_private_key(d, ec.SECP256R1()).public_key()
b = base64.urlsafe_b64encode(pub.public_bytes(s.Encoding.X962, s.PublicFormat.UncompressedPoint))
print("VAPID_PUBLIC_KEY=" + b.rstrip(b"=").decode())
PY
    } | env_rewrite
    echo "VAPID public key derived from the existing private key"
fi
# only the PUBLIC key is ever printed
echo "VAPID public key: $(grep '^VAPID_PUBLIC_KEY=' "$ENV_FILE" | cut -d= -f2-)"

echo "== systemd"
install -m 644 "$APP_DIR/deploy/tabela.service" /etc/systemd/system/tabela.service
systemctl daemon-reload
systemctl enable tabela >/dev/null
systemctl restart tabela

echo "== nginx"
install -d -m 700 "$BACKUP_DIR"
[ -f "$SITE" ] && cp -a "$SITE" "$BACKUP_DIR/tabela.site.bak"
[ -f "$LIMITS" ] && cp -a "$LIMITS" "$BACKUP_DIR/tabela-limits.conf.bak"
install -m 644 "$APP_DIR/deploy/tabela-limits.conf" "$LIMITS"
install -m 644 "$APP_DIR/deploy/nginx-tabela.conf" "$SITE"
ln -sf "$SITE" /etc/nginx/sites-enabled/tabela
if nginx -t; then
    systemctl reload nginx
else
    echo "nginx -t FAILED: restoring previous config" >&2
    if [ -f "$BACKUP_DIR/tabela.site.bak" ]; then
        cp -a "$BACKUP_DIR/tabela.site.bak" "$SITE"
    else
        # first install: no previous site to restore - remove the broken one entirely
        rm -f /etc/nginx/sites-enabled/tabela "$SITE"
    fi
    if [ -f "$BACKUP_DIR/tabela-limits.conf.bak" ]; then
        cp -a "$BACKUP_DIR/tabela-limits.conf.bak" "$LIMITS"
    else
        rm -f "$LIMITS"
    fi
    nginx -t && systemctl reload nginx
    exit 1
fi

echo "== waiting for /api/health (max 180 s)"
for i in $(seq 1 90); do
    if curl -fs http://127.0.0.1:8000/api/health | grep -q '"ok":true'; then
        echo "healthy after ~$((i * 2)) s"; exit 0
    fi
    sleep 2
done
echo "not healthy after 180 s; see: journalctl -u tabela -n 100" >&2
exit 1
