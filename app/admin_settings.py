# © 2026 Andy217Ace
"""Setări editabile din pagina Setări (admin): retenția capturilor și pragul de spațiu liber.

Doar valori nesecrete. Cheia de administrare rămâne în /etc/tabela.env și nu intră aici.
Tabelul `settings` (cheie-valoare) are prioritate; fără rând se folosește valoarea din
mediu (CAPTURE_RETENTION_DAYS, CAPTURE_MIN_FREE_MB). Fiecare schimbare ajunge în
`correction_audit` cu action='setting' (cine, când, ce; fără valori secrete).
"""
from __future__ import annotations

from datetime import datetime

from app import corrections
from app.store import TZ

# cheie -> (minim, maxim, implicit când mediul nu are o valoare validă)
SPECS: dict[str, tuple[int, int, int]] = {
    "capture_retention_days": (1, 30, 7),
    "capture_min_free_mb": (256, 102400, 2048),
}

_DDL = ("CREATE TABLE IF NOT EXISTS settings ("
        " key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")


def validate(key: str, value) -> int:
    """Valoarea întreagă dacă e în interval; ValueError altfel (bool, șir, float și interval)."""
    if key not in SPECS:
        raise ValueError("cheie necunoscută")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("tip invalid")
    lo, hi, _ = SPECS[key]
    if not lo <= value <= hi:
        raise ValueError("în afara intervalului")
    return value


def _raw(store, key: str) -> str | None:
    with store._lock:
        store._conn.execute(_DDL)
        row = store._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def effective(store, key: str, env_default: int) -> int:
    """Valoarea activă: din DB dacă există și e validă; altfel valoarea din mediu, așa cum
    e (CAPTURE_RETENTION_DAYS=0 înseamnă „nu păstra imagini"). Un rând invalid cade pe mediu."""
    raw = _raw(store, key)
    if raw is None:
        return env_default
    try:
        return validate(key, int(raw))
    except (ValueError, TypeError):
        return env_default


def view(store, env_defaults: dict[str, int]) -> dict:
    """Ce vede pagina Setări: valoarea activă și intervalul, fără nimic secret."""
    out = {}
    for key, (lo, hi, _) in SPECS.items():
        out[key] = {"value": effective(store, key, env_defaults.get(key, SPECS[key][2])),
                    "min": lo, "max": hi}
    return out


def save(store, changes: dict, *, actor: str = "admin", ip: str | None = None) -> dict:
    """Validează tot înainte de scriere (nimic nu se modifică la o eroare), apoi scrie
    atomic și auditează fiecare valoare schimbată. Returnează {cheie: {old, new}}."""
    clean = {k: validate(k, v) for k, v in changes.items()}  # ValueError înainte de orice scriere
    now = datetime.now(TZ).isoformat(timespec="seconds")
    changed: dict[str, dict] = {}
    with store._lock:
        c = store._conn
        c.execute(_DDL)
        c.execute("BEGIN IMMEDIATE")
        try:
            for key, value in clean.items():
                row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
                old = row[0] if row else None
                if old == str(value):
                    continue
                c.execute("INSERT INTO settings(key, value, updated_at) VALUES (?,?,?)"
                          " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                          " updated_at=excluded.updated_at", (key, str(value), now))
                changed[key] = {"old": int(old) if old is not None else None, "new": value}
                corrections.audit(c, "setting", actor=actor, ip=ip,
                                  detail={"key": key, "old": changed[key]["old"], "new": value})
            c.execute("COMMIT")
        except Exception:
            c.execute("ROLLBACK")
            raise
    return changed
