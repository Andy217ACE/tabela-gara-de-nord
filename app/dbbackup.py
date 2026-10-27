# © 2026 Andy217Ace
"""Backup-aware schema migration: before a migration changes a populated database file,
make sure a copy of the database as it was exists.

``deploy/update.sh`` already takes an online backup named
``<BACKUP_DIR>/tabela-<YYYYmmdd-HHMMSS>-v<schema>.db`` before every deploy that raises the
schema, and then writes a marker file next to the database (``MARKER_NAME``: version,
backup path, database path). Here the migration, in order:

1. looks for a backup of the current schema version taken in the last ``RECENT_S``
   seconds in the backup directory;
2. when there is none, takes the same kind of online backup itself (sqlite3 backup API
   from a read-only connection, integrity checked, mode 600) in the backup directory,
   or, when that directory cannot be used, in ``<directory of the database>/
   FALLBACK_DIRNAME`` (the service can always write next to its database);
3. when no backup could be made, accepts update.sh's marker as proof of a backup (same
   schema version, same database, written in the last ``RECENT_S`` seconds);
4. otherwise raises ``BackupUnavailable``: the database is NOT migrated without a known
   backup; the error says what to fix.

A backup directory that cannot be listed (Beta 1.29 in production: root:root 0700 while
the service runs as `tabela`) is "cannot verify", logged once as an ERROR with the path
and the cause, and never by itself a crash.

``BACKUP_DIR`` (env) overrides the default ``<directory of the database>/backups``.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

RECENT_S = 24 * 3600
BACKUP_KEEP = 5  # same as update.sh: the newest few of this module's own files
FALLBACK_DIRNAME = "backups-fallback"
MARKER_NAME = ".pre-migration-backup"  # written by deploy/update.sh after its backup


class BackupUnavailable(RuntimeError):
    """No backup of the database could be made or found: the migration must not run."""


def backup_dir(db_path: str) -> Path:
    env = os.environ.get("BACKUP_DIR", "").strip()
    return Path(env) if env else Path(os.path.abspath(db_path)).parent / "backups"


def fallback_dir(db_path: str) -> Path:
    return Path(os.path.abspath(db_path)).parent / FALLBACK_DIRNAME


def marker_path(db_path: str) -> Path:
    return Path(os.path.abspath(db_path)).parent / MARKER_NAME


def recent_backup(db_path: str, version: int, now: float | None = None) -> Path | None:
    """A backup of schema `version` made by update.sh (or by `ensure`) in the last day.
    Raises OSError when the backup directory exists but cannot be listed."""
    d = backup_dir(db_path)
    if not d.is_dir():
        return None
    pat = re.compile(rf"^tabela-.*-v{version}\.db$")
    cutoff = (now if now is not None else time.time()) - RECENT_S
    best = None
    for p in d.iterdir():
        try:
            if pat.match(p.name) and p.stat().st_size > 0 and p.stat().st_mtime >= cutoff:
                if best is None or p.stat().st_mtime > best.stat().st_mtime:
                    best = p
        except OSError:
            continue
    return best


def _make(db_path: str, version: int, directory: Path) -> Path:
    """Online backup into `directory`; raises OSError / sqlite3.Error on failure."""
    dest = directory / f"tabela-{datetime.now():%Y%m%d-%H%M%S}-v{version}.db"
    src = dst = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(str(dest))
        src.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        dst.close()
        dst = None
        if ok != "ok":
            dest.unlink(missing_ok=True)
            raise sqlite3.DatabaseError(f"backup failed its integrity check: {ok}")
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass
        return dest
    finally:
        for c in (src, dst):
            if c is not None:
                try:
                    c.close()
                except sqlite3.Error:
                    pass


def marker_backup(db_path: str, version: int, now: float | None = None) -> str | None:
    """The backup update.sh announced for this database at schema `version`, if its
    marker is recent and matches; else None."""
    m = marker_path(db_path)
    try:
        st = m.stat()
        text = m.read_text(encoding="utf-8")
    except OSError:
        return None
    if st.st_mtime < (now if now is not None else time.time()) - RECENT_S:
        return None
    kv = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    if kv.get("version", "").strip() != str(version) or not kv.get("backup", "").strip():
        return None
    try:
        same = os.path.realpath(kv.get("db", "").strip()) == os.path.realpath(db_path)
    except (OSError, ValueError):
        same = False
    return kv["backup"].strip() if same else None


def ensure(db_path: str, version: int) -> Path | str | None:
    """A usable backup of the database at schema `version` before it is migrated: an
    existing recent one, a new one, or the one update.sh announced (its path, as text).
    None when there is nothing to protect. Raises BackupUnavailable when none exists."""
    if not db_path or db_path == ":memory:" or not os.path.isfile(db_path):
        return None
    if os.path.getsize(db_path) == 0:
        return None
    primary = backup_dir(db_path)
    problems: list[str] = []
    try:
        found = recent_backup(db_path, version)
    except OSError as e:
        found = None
        problems.append(f"cannot list {primary}: {e}")
        log.error("backup directory %s cannot be listed (%s): cannot check for a recent "
                  "backup; fix its owner/permissions (the service user must be able to "
                  "read and write it)", primary, e)
    if found is not None:
        return found
    for d in (primary, fallback_dir(db_path)):
        try:
            dest = _make(db_path, version, d)
        except (OSError, sqlite3.Error) as e:
            problems.append(f"cannot back up into {d}: {e}")
            log.warning("pre-migration backup into %s failed: %s", d, e)
            continue
        if d != primary:
            log.error("pre-migration backup made in the FALLBACK directory %s (the backup "
                      "directory %s is not usable)", dest, primary)
        else:
            log.info("pre-migration backup: %s", dest)
        return dest
    announced = marker_backup(db_path, version)
    if announced:
        log.warning("no backup could be made here; migrating on the strength of the "
                    "backup deploy/update.sh reported: %s (marker %s)",
                    announced, marker_path(db_path))
        return announced
    raise BackupUnavailable(
        f"refusing to migrate {db_path} from schema v{version}: no backup of it exists or "
        f"could be made ({'; '.join(problems)}), and no recent marker from deploy/update.sh "
        f"({marker_path(db_path)}). Make {primary} readable and writable by the service user "
        f"(update.sh does: chown <service user> + chmod 750) or run deploy/update.sh, then "
        f"restart. The database was not changed.")
