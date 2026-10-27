#!/usr/bin/env bash
# © 2026 Andy217Ace
# Update the deployed code: sudo bash /opt/tabela/app/deploy/update.sh [branch]
# Default branch: the one currently checked out (fails on a detached HEAD).
#
#  1. records the running commit (PREV), fetches and checks out origin/<branch>;
#  2. pip install -r requirements.txt - on failure the old commit is checked out again
#     and the service is NOT restarted (it keeps running the old code);
#  3. migrates /etc/tabela.env (adds LAST_IMAGE_PATH and CAPTURE_DIR if missing) and
#     creates CAPTURE_DIR owned by the service user; ADMIN_TOKEN is set by hand (secret);
#     creates/repairs BACKUP_DIR owned by the service user, mode 750 (the app lists it at
#     startup before a migration; a root:root 0700 directory stopped Beta 1.29 from
#     starting). Only the directory itself: existing backups keep their owner (root, 600);
#  4. if the new code's store.SCHEMA_VERSION is above the database's user_version,
#     takes an online SQLite backup first (/var/lib/tabela/backups, last 5 kept) and
#     records it in <db dir>/.pre-migration-backup (version, backup, db) for the app;
#  5. restarts and waits for /api/health; if it never gets healthy, ROLLS BACK to PREV
#     on the ORIGINAL branch (checkout, pip install, restart, wait) and exits 1.
#
# Every deploy bumps the version: VERSION (Beta 1.NN, NN + 1) and a new section on top of
# CHANGELOG.md (Romanian) - committed BEFORE running this script; it prints the version.
#
# Health gate: HEALTH_MODE=strict (default) needs {"ok":true}, i.e. the app is up AND
# it has read the CFR board recently. When CFR itself is failing that can never pass;
# for an emergency redeploy use HEALTH_MODE=up (HTTP 200 from /api/health is enough).
#
# Paths and commands can be overridden through the environment (used by
# tests/test_update_sh.py to simulate a server); production uses the defaults.
set -euo pipefail

# bash reads a script while running it and `git checkout` below replaces this file:
# run from a private copy so the rest of the run is not read from the new version.
if [ -z "${TABELA_UPDATE_COPY:-}" ]; then
    copy="$(mktemp "${TMPDIR:-/tmp}/tabela-update.XXXXXX")"
    cp "$0" "$copy"
    TABELA_UPDATE_COPY="$copy" exec bash "$copy" "$@"
fi
trap 'rm -f "$TABELA_UPDATE_COPY"' EXIT

APP_DIR="${APP_DIR:-/opt/tabela/app}"
VENV="${VENV:-/opt/tabela/venv}"
ENV_FILE="${ENV_FILE:-/etc/tabela.env}"
DATA_DIR="${DATA_DIR:-/var/lib/tabela}"
BACKUP_DIR="${BACKUP_DIR:-$DATA_DIR/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-5}"
PIP="${PIP:-$VENV/bin/pip}"
PYTHON="${PYTHON:-$VENV/bin/python}"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
HEALTH_CMD="${HEALTH_CMD:-curl -fs $HEALTH_URL}"
HEALTH_TRIES="${HEALTH_TRIES:-90}"     # x HEALTH_SLEEP seconds (default: 3 minutes)
HEALTH_SLEEP="${HEALTH_SLEEP:-2}"
HEALTH_MODE="${HEALTH_MODE:-strict}"   # strict | up
SVC_OWNER="${SVC_OWNER-tabela}"        # owner of CAPTURE_DIR/BACKUP_DIR (empty: current user, tests)
CHOWN="${CHOWN:-chown}"
CHMOD="${CHMOD:-chmod}"
UNIT_SRC="$APP_DIR/deploy/tabela.service"
UNIT_DST="${UNIT_DST:-/etc/systemd/system/tabela.service}"

if [ "${REQUIRE_ROOT:-1}" = 1 ] && [ "$(id -u)" -ne 0 ]; then
    echo "run as root (sudo)" >&2; exit 1
fi

git_() { git -C "$APP_DIR" "$@"; }

CURRENT="$(git_ rev-parse --abbrev-ref HEAD)"
if [ $# -ge 1 ] && [ -n "$1" ]; then
    BRANCH="$1"
elif [ "$CURRENT" = "HEAD" ]; then
    echo "ERROR: $APP_DIR is on a detached HEAD ($(git_ rev-parse --short HEAD))." >&2
    echo "Pass the branch explicitly, e.g.: update.sh main" >&2
    exit 1
else
    BRANCH="$CURRENT"
fi

PREV="$(git_ rev-parse HEAD)"
echo "== current: $(git_ log -1 --oneline "$PREV") (branch: $CURRENT)"

case "$HEALTH_MODE" in strict|up) ;; *) echo "HEALTH_MODE must be strict or up" >&2; exit 1;; esac
# pre-check: if the running app is up but not reading CFR, a strict gate cannot pass
if [ "$HEALTH_MODE" = strict ]; then
    pre="$($HEALTH_CMD 2>/dev/null || true)"
    if printf '%s' "$pre" | grep -q '"ok":false'; then
        echo "WARNING: /api/health is ok=false BEFORE the update (CFR board not read recently)." >&2
        echo "The strict health gate will then fail and roll back. For an emergency redeploy:" >&2
        echo "  HEALTH_MODE=up bash update.sh $BRANCH" >&2
    fi
fi

health_ok() {   # one probe according to HEALTH_MODE
    local body
    body="$($HEALTH_CMD 2>/dev/null)" || return 1
    if [ "$HEALTH_MODE" = up ]; then
        printf '%s' "$body" | grep -q '"ok":'
    else
        printf '%s' "$body" | grep -q '"ok":true'
    fi
}

healthy() {
    local i
    for i in $(seq 1 "$HEALTH_TRIES"); do
        if health_ok; then
            echo "healthy after ~$((i * HEALTH_SLEEP)) s"
            return 0
        fi
        sleep "$HEALTH_SLEEP"
    done
    return 1
}

install_unit() {
    if [ -f "$UNIT_SRC" ] && ! cmp -s "$UNIT_SRC" "$UNIT_DST"; then
        install -m 644 "$UNIT_SRC" "$UNIT_DST"
        $SYSTEMCTL daemon-reload
    fi
}

# Append KEY=VALUE when KEY is missing, never gluing it to a last line that has no
# trailing newline.
env_add_missing() {
    local key="$1" value="$2"
    [ -f "$ENV_FILE" ] || return 0
    if ! grep -q "^${key}=" "$ENV_FILE"; then
        if [ -s "$ENV_FILE" ] && [ -n "$(tail -c 1 "$ENV_FILE")" ]; then
            printf '\n' >> "$ENV_FILE" || return 1
        fi
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE" || return 1
        echo "env: added $key"
    fi
}

db_path() {
    local p=""
    if [ -f "$ENV_FILE" ]; then
        p="$(grep '^DB_PATH=' "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true)"
    fi
    echo "${p:-$DATA_DIR/tabela.db}"
}

db_version() {   # PRAGMA user_version of the live database (0 if absent)
    local db="$1"
    if [ ! -f "$db" ]; then echo 0; return; fi
    "$PYTHON" -c 'import sqlite3,sys; c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro", uri=True); print(c.execute("PRAGMA user_version").fetchone()[0])' "$db"
}

code_version() { # SCHEMA_VERSION declared by the checked-out code
    sed -n 's/^SCHEMA_VERSION = \([0-9][0-9]*\).*/\1/p' "$APP_DIR/app/store.py" | head -n 1
}

backup_db() {
    local db="$1" dest
    # called as `backup_db ... || abort_before_restart`, where `set -e` is off: check each step
    # umask 077: the directory is created 700 and the copy 600 (root only)
    (umask 077; mkdir -p "$BACKUP_DIR") || return 1
    dest="$BACKUP_DIR/tabela-$(date +%Y%m%d-%H%M%S)-v$2.db"
    if command -v sqlite3 >/dev/null 2>&1; then
        # -readonly: the backup never creates root-owned -wal/-shm next to the live DB
        (umask 077; sqlite3 -readonly "$db" ".backup '$dest'") || return 1
    else   # the same online-backup API, through Python
        (umask 077; "$PYTHON" -c 'import sqlite3,sys; s=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro", uri=True); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()' "$db" "$dest") || return 1
    fi
    [ -s "$dest" ] || return 1
    echo "db backup: $dest"
    # keep only the newest $BACKUP_KEEP (names sort by time)
    find "$BACKUP_DIR" -maxdepth 1 -name 'tabela-*.db' -print | sort -r |
        tail -n +"$((BACKUP_KEEP + 1))" | while read -r old; do rm -f -- "$old"; done
    # tell the app a backup exists (app/dbbackup.py: proof when it cannot see the backup
    # itself); written last, only after a good backup, readable by the service
    local marker tmp
    marker="$(dirname "$db")/.pre-migration-backup"
    tmp="$marker.tmp.$$"
    if (umask 022; printf 'version=%s\nbackup=%s\ndb=%s\n' "$2" "$dest" "$db" > "$tmp") &&
        mv -f -- "$tmp" "$marker"; then
        echo "backup marker: $marker"
    else
        rm -f -- "$tmp"
        echo "WARNING: could not write $marker (the app finds the backup in $BACKUP_DIR)" >&2
    fi
}

# The app (user SVC_OWNER) lists BACKUP_DIR at startup before migrating and may write its
# own backup there: the directory (not the files in it) belongs to the service user.
prepare_backup_dir() {
    (umask 077; mkdir -p "$BACKUP_DIR") || return 1
    [ -n "$SVC_OWNER" ] || return 0
    $CHOWN "$SVC_OWNER:$SVC_OWNER" "$BACKUP_DIR" && $CHMOD 750 "$BACKUP_DIR"
}

echo "== fetch $BRANCH"
git_ fetch --prune origin "$BRANCH"
git_ checkout -q -B "$BRANCH" "origin/$BRANCH"
NEW="$(git_ rev-parse HEAD)"
echo "== new: $(git_ log -1 --oneline)"

restore_prev() {  # the original branch name at the original commit
    if [ "$CURRENT" = "HEAD" ]; then git_ checkout -q --detach "$PREV"
    else git_ checkout -q -B "$CURRENT" "$PREV"; fi
}

# Before the restart nothing has changed for the running process: put the old code back
# on disk and stop (static files are served from disk, so it must match the process).
abort_before_restart() {
    echo "ERROR: $1; restoring $PREV - service NOT restarted (old code keeps running)" >&2
    restore_prev
    "$PIP" install -q -r "$APP_DIR/requirements.txt" || true
    exit 1
}

echo "== pip install"
"$PIP" install -q -r "$APP_DIR/requirements.txt" || abort_before_restart "pip install failed"

env_add_missing LAST_IMAGE_PATH "$DATA_DIR/last.jpg" || abort_before_restart "cannot update $ENV_FILE"
env_add_missing CAPTURE_DIR "$DATA_DIR/captures" || abort_before_restart "cannot update $ENV_FILE"
CAPTURE_DIR_="$(sed -n 's/^CAPTURE_DIR=//p' "$ENV_FILE" | tail -n 1 | tr -d "\"'")"
case "$CAPTURE_DIR_" in
    "") ;;
    "$DATA_DIR"/*)  # the unit can only write under DATA_DIR (ReadWritePaths)
        { mkdir -p "$CAPTURE_DIR_" && { [ -z "$SVC_OWNER" ] || {
            $CHOWN "$SVC_OWNER:$SVC_OWNER" "$CAPTURE_DIR_" && $CHMOD 750 "$CAPTURE_DIR_"; }; }; }             || abort_before_restart "cannot prepare $CAPTURE_DIR_" ;;
    *) echo "WARNING: CAPTURE_DIR=$CAPTURE_DIR_ is outside $DATA_DIR; the service cannot write there" >&2 ;;
esac

case "$BACKUP_DIR" in
    "$DATA_DIR"/*) ;;
    *) echo "WARNING: BACKUP_DIR=$BACKUP_DIR is outside $DATA_DIR; the service cannot write there" >&2 ;;
esac
prepare_backup_dir || abort_before_restart "cannot prepare $BACKUP_DIR for $SVC_OWNER"

DB="$(db_path)"
OLD_V="$(db_version "$DB")" || abort_before_restart "cannot read the schema version of $DB"
NEW_V="$(code_version)"
if [ -f "$DB" ] && [ -n "$NEW_V" ] && [ "$NEW_V" -gt "$OLD_V" ]; then
    echo "== schema v$OLD_V -> v$NEW_V: backup before restart"
    backup_db "$DB" "$OLD_V" || abort_before_restart "database backup failed"
fi

install_unit
echo "== restart"
$SYSTEMCTL restart tabela

if healthy; then
    echo "OK: $PREV -> $NEW ($(cat "$APP_DIR/VERSION" 2>/dev/null || echo 'fără VERSION'))"
    exit 0
fi

echo "ERROR: not healthy after $((HEALTH_TRIES * HEALTH_SLEEP)) s; rolling back to $PREV" >&2
echo "(logs: journalctl -u tabela -n 100)" >&2
restore_prev
"$PIP" install -q -r "$APP_DIR/requirements.txt" || echo "WARNING: pip install during rollback failed" >&2
install_unit
$SYSTEMCTL restart tabela
if healthy; then
    echo "ROLLED BACK: running $(git_ log -1 --oneline) again (failed: $NEW)" >&2
else
    echo "ROLLBACK FAILED: $(git_ log -1 --oneline) is not healthy either; check journalctl -u tabela" >&2
fi
if [ -n "$NEW_V" ] && [ "$NEW_V" -gt "$OLD_V" ]; then
    echo "note: the new code may already have migrated the database to v$NEW_V (older code" >&2
    echo "ignores the extra columns). Pre-update copy: newest file in $BACKUP_DIR" >&2
fi
exit 1
