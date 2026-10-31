# © 2026 Andy217Ace
"""Unelte din pagina #admin (după autentificarea din app.admin):

- curățarea duplicatelor de trenuri: refolosește scripts/merge_number_dups.py (fără să-i
  schimbe logica). Citirea (raportul) e într-o conexiune doar-în-citire; scrierea și
  restaurarea se fac pe conexiunea store-ului, sub `store._lock` (același lock ca
  poller-ul), după o copie de siguranță verificată;
- starea serverului (read-only): /proc, systemctl is-active pe unități fixe, watchdog.json.
  Pe platforme fără /proc (Windows, teste) câmpurile lipsă sunt null.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from app import dbbackup
from app.store import TZ

log = logging.getLogger(__name__)

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "merge_number_dups.py"
_md = None  # modulul scripts/merge_number_dups.py, încărcat la prima folosire
SYSTEMCTL_TIMEOUT_S = 3
SERVICE_UNITS = ("tabela", "tabela-watchdog.timer", "nginx")  # fixe: nu vin din input
UNIT_STATES = ("active", "inactive", "failed")


def _merge():
    global _md
    if _md is None:
        spec = importlib.util.spec_from_file_location("merge_number_dups", _SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _md = mod
    return _md


def _backup(store) -> str:
    """Copie verificată a bazei în directorul de backup (dbbackup.backup_dir, ca backup_api).
    Returnează doar numele fișierului. Ridică RuntimeError dacă nu reușește."""
    db = os.path.abspath(store.path)
    try:
        dest = _merge().backup(db, str(dbbackup.backup_dir(db)))
    except (SystemExit, OSError, sqlite3.Error) as e:  # integritate / I/O
        log.error("dupes: copia de siguranță a eșuat (%s)", type(e).__name__)
        raise RuntimeError("Copia de siguranță a eșuat.") from None
    return Path(dest).name


def dupes_report(db_path: str, min_age_min: int = 60) -> dict:
    """Raportul (dry run) din merge_number_dups.report. Nu scrie nimic."""
    uri = f"file:{Path(os.path.abspath(db_path)).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        return _merge().report(conn, min_age_min)
    finally:
        conn.close()


def dupes_apply(store, min_age_min: int = 60) -> dict:
    """Backup, apoi merge (aceeași tranzacție și arhivă ca --apply din script).
    Sub store._lock: nicio scriere concurentă a poller-ului în timpul operației."""
    with store._lock:
        name = _backup(store)  # fișierul există înainte de orice scriere
        batch, summary = _merge().apply(store._conn, min_age_min)
    return {"batch": batch, "summary": summary, "backup": name}


def dupes_restore(store, batch: str | None = None) -> dict:
    """Backup, apoi restaurarea din merged_rows (un batch sau toate), sub store._lock."""
    with store._lock:
        name = _backup(store)
        restored = _merge().restore(store._conn, batch)
    return {"restored": restored, "backup": name}


# -- starea serverului -------------------------------------------------------------

def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def _kb_fields(text: str, names: tuple[str, ...]) -> dict[str, int] | None:
    out: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        if key in names:
            try:
                out[key] = int(rest.split()[0])
            except (ValueError, IndexError):
                return None
    return out if len(out) == len(names) else None


def _load() -> dict | None:
    t = _read("/proc/loadavg")
    if not t:
        return None
    try:
        a = t.split()
        return {"1m": float(a[0]), "5m": float(a[1]), "15m": float(a[2]),
                "cores": os.cpu_count()}
    except (ValueError, IndexError):
        return None


def _memory() -> dict | None:
    t = _read("/proc/meminfo")
    f = _kb_fields(t, ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")) if t else None
    if f is None:
        return None
    mb = lambda kb: round(kb / 1024, 1)  # noqa: E731
    return {"total_mb": mb(f["MemTotal"]), "available_mb": mb(f["MemAvailable"]),
            "swap_total_mb": mb(f["SwapTotal"]),
            "swap_used_mb": mb(f["SwapTotal"] - f["SwapFree"])}


def _uptime() -> int | None:
    t = _read("/proc/uptime")
    try:
        return int(float(t.split()[0])) if t else None
    except (ValueError, IndexError):
        return None


def _rss_mb() -> float | None:
    t = _read("/proc/self/status")
    f = _kb_fields(t, ("VmRSS",)) if t else None
    return round(f["VmRSS"] / 1024, 1) if f else None


def _disk(db_path: str) -> dict | None:
    if db_path == ":memory:":
        return None
    try:
        du = shutil.disk_usage(os.path.dirname(os.path.abspath(db_path)))
    except OSError:
        return None
    return {"total_gb": round(du.total / 2**30, 1), "free_gb": round(du.free / 2**30, 1)}


def _unit_state(unit: str) -> str:
    """systemctl is-active <unit>, fără shell; orice altceva decât cele trei stări -> unknown."""
    exe = shutil.which("systemctl")
    if not exe:
        return "unknown"
    try:
        p = subprocess.run([exe, "is-active", unit], capture_output=True, text=True,
                           timeout=SYSTEMCTL_TIMEOUT_S, shell=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    out = (p.stdout or "").strip()
    return out if out in UNIT_STATES else "unknown"


def _watchdog(db_path: str) -> dict:
    """Starea watchdog-ului din watchdog.json (lângă baza de date); nulls dacă lipsește."""
    empty = {"failures": None, "last_restart": None}
    if db_path == ":memory:":
        return empty
    t = _read(str(Path(os.path.abspath(db_path)).parent / "watchdog.json"))
    try:
        st = json.loads(t) if t else None
    except ValueError:
        return empty
    if not isinstance(st, dict):
        return empty
    f = st.get("failures")
    lr = st.get("last_restart")
    last = None
    if isinstance(lr, (int, float)) and not isinstance(lr, bool):
        try:
            last = datetime.fromtimestamp(lr, TZ).isoformat(timespec="seconds")
        except (OSError, OverflowError, ValueError):
            last = None
    return {"failures": f if isinstance(f, int) and not isinstance(f, bool) else None,
            "last_restart": last}


def server_status(db_path: str) -> dict:
    """Starea serverului, fără căi absolute, token-uri sau erori brute."""
    return {
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "load": _load(),
        "memory": _memory(),
        "disk": _disk(db_path),
        "uptime_s": _uptime(),
        "process": {"rss_mb": _rss_mb()},
        "services": {u: _unit_state(u) for u in SERVICE_UNITS},
        "watchdog": _watchdog(db_path),
    }
