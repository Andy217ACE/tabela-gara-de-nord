# © 2026 Andy217Ace
"""Copii de siguranță ale bazei: copie online (consistentă cu WAL), verificare de integritate
și retenție. Copia și verificarea se fac cu app.dbbackup (aceeași regulă ca migrația):
copia e scrisă ca fișier temporar, verificată, apoi redenumită. Copiile rămân pe server,
în directorul de backup (`dbbackup.backup_dir`); nu se descarcă din interfața admin."""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from app import dbbackup

log = logging.getLogger(__name__)

KEEP = 5  # copii păstrate în directorul de backup (cele mai noi)


def _schema_version(db_path: str) -> int:
    c = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
    try:
        return c.execute("PRAGMA user_version").fetchone()[0]
    finally:
        c.close()


def make_backup(store_path: str, dest_dir: str | Path, keep: int = KEEP) -> Path:
    """Copie online a bazei în `dest_dir`, verificată, apoi retenție: rămân `keep` copii.
    Ridică sqlite3.Error / OSError dacă nu reușește; baza live nu este modificată."""
    dest_dir = Path(dest_dir)
    version = _schema_version(store_path)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S-%f}"  # microsecunde: copii rapide nu se suprascriu
    out = dbbackup._make(store_path, version, dest_dir, stamp=stamp)
    dbbackup._prune(dest_dir, keep=keep)
    log.info("copie de siguranță: %s", out)
    return out


def verify_backup(path: str | Path) -> bool:
    """True doar dacă fișierul există, nu e gol și trece PRAGMA integrity_check.
    Deschis doar în citire: nu creează fișiere lângă copie și nu atinge baza live."""
    p = Path(path)
    try:
        if not p.is_file() or p.stat().st_size == 0:
            return False
        c = sqlite3.connect(f"file:{p.resolve().as_posix()}?mode=ro", uri=True)
        try:
            return c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            c.close()
    except (OSError, sqlite3.Error):
        return False
