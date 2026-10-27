# © 2026 Andy217Ace
"""Backup-aware schema migration: before a migration changes a populated database file,
make sure a copy of the database as it was exists.

``deploy/update.sh`` already takes an online backup named
``<BACKUP_DIR>/tabela-<YYYYmmdd-HHMMSS>-v<schema>.db`` before every deploy. Here the
migration first looks for one of the current schema version taken in the last
``RECENT_S`` seconds and, only when there is none (a restart outside update.sh, a manual
run), takes the same kind of online backup itself (sqlite3 backup API from a read-only
connection, integrity checked, mode 600). A failed backup is logged and never blocks the
migration: the steps are additive and atomic, and the migration of a database that
cannot be copied is the operator's call, not a crash loop.

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


def backup_dir(db_path: str) -> Path:
    env = os.environ.get("BACKUP_DIR", "").strip()
    return Path(env) if env else Path(os.path.abspath(db_path)).parent / "backups"


def recent_backup(db_path: str, version: int, now: float | None = None) -> Path | None:
    """A backup of schema `version` made by update.sh (or by `ensure`) in the last day."""
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


def ensure(db_path: str, version: int) -> Path | None:
    """Path of a usable backup of the database at schema `version` (existing recent one,
    or a new one), or None when there is nothing to protect / it could not be made."""
    if not db_path or db_path == ":memory:" or not os.path.isfile(db_path):
        return None
    if os.path.getsize(db_path) == 0:
        return None
    found = recent_backup(db_path, version)
    if found is not None:
        return found
    dest = backup_dir(db_path) / f"tabela-{datetime.now():%Y%m%d-%H%M%S}-v{version}.db"
    src = dst = None
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(str(dest))
        src.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        dst.close()
        dst = None
        if ok != "ok":
            dest.unlink(missing_ok=True)
            log.warning("pre-migration backup failed its integrity check: %s", ok)
            return None
        try:
            os.chmod(dest, 0o600)
        except OSError:
            pass
        log.info("pre-migration backup: %s", dest)
        return dest
    except (OSError, sqlite3.Error):
        log.warning("pre-migration backup could not be made", exc_info=True)
        return None
    finally:
        for c in (src, dst):
            if c is not None:
                try:
                    c.close()
                except sqlite3.Error:
                    pass
