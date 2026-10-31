# © 2026 Andy217Ace
"""Restaurarea bazei din o copie de siguranță (Val 4b). Nu există restaurare din interfața
web. Pași, în ordine, fără să se atingă baza live dacă un pas eșuează:

1. confirmarea explicită (`CONFIRM`, dată ca parametru; fără ea nu se face nimic);
2. refuz dacă serviciul rulează (systemd `tabela`, sau baza are un lacăt de scriere);
3. verificare de integritate pe o copie a fișierului de restaurat;
4. copie de siguranță a stării curente (în directorul de backup, cu retenția obișnuită);
5. înlocuire atomică a bazei; fișierele -wal și -shm vechi se șterg, altfel SQLite
   ar aplica pagini din baza înlocuită peste copia restaurată.

Copia restaurată cu o schemă mai veche este migrată de `Store` la următoarea pornire."""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from app import backup_api, dbbackup

log = logging.getLogger(__name__)

CONFIRM = "RESTAUREZ"  # confirmarea explicită: trebuie trimisă ca parametru, la fiecare apel
SERVICE = "tabela"


class RestoreRefused(RuntimeError):
    """Restaurarea nu s-a făcut; baza live a rămas neschimbată."""


def service_active(db_path: str) -> bool:
    """Serviciul rulează? systemd dacă e disponibil; altfel, un lacăt de scriere pe bază."""
    if shutil.which("systemctl"):
        r = subprocess.run(["systemctl", "is-active", "--quiet", SERVICE], check=False)
        return r.returncode == 0
    if not os.path.isfile(db_path):
        return False
    c = sqlite3.connect(db_path, timeout=0, isolation_level=None)
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("ROLLBACK")
        return False
    except sqlite3.OperationalError:
        return True
    finally:
        c.close()


def _drop_sidecars(db: Path) -> None:
    for suffix in ("-wal", "-shm"):
        side = db.with_name(db.name + suffix)
        if side.exists():
            side.unlink()


def restore(path: str | Path, db_path: str | Path, confirm: str = "") -> None:
    """Restaurează `db_path` din copia `path`. Ridică RestoreRefused (fără atingerea bazei)
    dacă lipsește confirmarea, serviciul rulează sau copia nu trece integritatea."""
    src, db = Path(path), Path(db_path)
    if confirm != CONFIRM:
        raise RestoreRefused(f"restaurarea cere confirmarea „{CONFIRM}”.")
    if service_active(str(db)):
        raise RestoreRefused(f"serviciul „{SERVICE}” rulează: oprește-l înainte de restaurare.")
    if not backup_api.verify_backup(src):
        raise RestoreRefused(f"copia {src} nu trece verificarea de integritate; baza nu a fost atinsă.")
    tmp = db.with_name(db.name + ".restore-tmp")
    try:
        shutil.copyfile(src, tmp)  # verificăm copia de lucru, nu fișierul original
        if not backup_api.verify_backup(tmp):
            raise RestoreRefused("copia de lucru nu trece verificarea de integritate.")
        if db.is_file():
            pre = backup_api.make_backup(str(db), dbbackup.backup_dir(str(db)))
            log.warning("restaurare: starea curentă salvată în %s", pre)
        _drop_sidecars(db)
        os.replace(tmp, db)
        log.warning("restaurare: %s <- %s", db, src)
    finally:
        if tmp.exists():
            tmp.unlink()
