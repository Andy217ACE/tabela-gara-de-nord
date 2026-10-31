# © 2026 Andy217Ace
"""Export CSV al istoricului (Val 4b): data, ora, trenul, stația, întârzierea și peronul.

Date publice (sunt deja afișate pe pagina de istoric). Fără corecții (`+corr`), fără note
de administrare și fără alte coloane: antetul este fix. Intervalul are cel mult `MAX_DAYS`
zile, iar exportul cel mult `MAX_ROWS` rânduri (peste limită: `truncated=True`, ca în
`/api/history`). Cererile sunt limitate pe client (`RateLimiter`)."""
from __future__ import annotations

import csv
import io
import sqlite3
import threading
import time
from datetime import date
from pathlib import Path

from app import quality
from app.store import _clean_delays

HEADER = ("data", "ora", "tren", "stație", "întârziere_min", "peron")
MAX_DAYS = 366
MAX_ROWS = 50_000
RATE_LIMIT = 30  # cereri per client
RATE_WINDOW_S = 60.0


class ExportRefused(Exception):
    """Cerere respinsă; `status` este codul HTTP (422 parametri, 429 limită de cereri)."""

    def __init__(self, status: int, msg: str):
        super().__init__(msg)
        self.status = status
        self.msg = msg


class RateLimiter:
    """Fereastră glisantă, în memorie, pe cheie (adresa clientului)."""

    def __init__(self, limit: int = RATE_LIMIT, window_s: float = RATE_WINDOW_S):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else now
        with self._lock:
            kept = [h for h in self._hits.get(key, []) if t - h < self.window_s]
            if len(kept) >= self.limit:
                self._hits[key] = kept
                return False
            kept.append(t)
            self._hits[key] = kept
            return True


LIMITER = RateLimiter()


def admit(key: str) -> None:
    """Ridică ExportRefused(429) când clientul a depășit limita de cereri."""
    if not LIMITER.allow(key):
        raise ExportRefused(429, "Prea multe cereri de export; încearcă mai târziu.")


def _day(raw: str | None, name: str) -> date:
    try:
        if not raw or len(raw) != 10:
            raise ValueError
        return date.fromisoformat(raw)
    except ValueError:
        raise ExportRefused(422, f"Data „{name}” invalidă (AAAA-LL-ZZ).") from None


def parse_range(raw_from: str | None, raw_to: str | None) -> tuple[date, date]:
    d0, d1 = _day(raw_from, "de la"), _day(raw_to, "până la")
    if d0 > d1:
        raise ExportRefused(422, "Data „de la” este după data „până la”.")
    if (d1 - d0).days > MAX_DAYS:
        raise ExportRefused(422, f"Intervalul este mai mare de {MAX_DAYS} de zile.")
    return d0, d1


def _parse_train(raw: str | None) -> int | None:
    if not raw:
        return None
    if not (raw.isascii() and raw.isdigit() and 1 <= int(raw) <= 99_999):
        raise ExportRefused(422, "Numărul trenului este invalid.")
    return int(raw)


_SQL = (
    "SELECT s.service_date, s.sched_time, s.board, s.train_no,"
    " COALESCE(q.station_canonical, s.station) AS station, s.last_platform, s.last_delay,"
    " s.delay_read_at, q.delay_checked, q.max_delay_clean, q.last_delay_clean,"
    " (SELECT MAX(MAX(COALESCE(CAST(e.old AS INTEGER), 0),"
    "                 COALESCE(CAST(e.new AS INTEGER), 0)))"
    "    FROM events e WHERE e.service_id = s.id AND e.kind = 'delay'"
    "    AND NOT " + quality.SUSPECT_EVENT_SQL + ") AS ev_max"
    " FROM services s LEFT JOIN service_quality q ON q.service_id = s.id"
    " WHERE s.service_date BETWEEN ? AND ? AND NOT " + quality.GHOST_SQL +
    " {train}"
    " ORDER BY s.service_date, s.sched_time, s.board, s.train_no LIMIT ?"
)


def _delay_cell(r: sqlite3.Row) -> str:
    """Întârzierea citită, sau gol când nu a fost citită niciodată (nu 0)."""
    d = _clean_delays(r)
    if d["max_delay"] is None:
        return ""
    if r["delay_checked"]:  # verificată retroactiv: valoarea confirmată este cea citită
        return str(d["max_delay"])
    seen = r["delay_read_at"] is not None or (r["ev_max"] or 0) > 0 or (r["last_delay"] or 0) > 0
    return str(d["max_delay"]) if seen else ""


def history_csv(db_path: str, raw_from: str | None, raw_to: str | None,
                train: str | None = None) -> tuple[str, bool]:
    """CSV-ul istoricului între două date (inclusiv), opțional pentru un tren.
    Returnează (text, truncated). Citește baza în mod doar-citire."""
    d0, d1 = parse_range(raw_from, raw_to)
    train_no = _parse_train(train)
    extra = " AND s.train_no = ?" if train_no is not None else ""
    args: list = [d0.isoformat(), d1.isoformat()]
    if train_no is not None:
        args.append(train_no)
    args.append(MAX_ROWS + 1)
    c = sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        found = c.execute(_SQL.format(train=extra), args).fetchall()
    finally:
        c.close()
    truncated = len(found) > MAX_ROWS
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(HEADER)
    for r in found[:MAX_ROWS]:
        w.writerow([r["service_date"], r["sched_time"], r["train_no"], r["station"],
                    _delay_cell(r), "" if r["last_platform"] is None else r["last_platform"]])
    return out.getvalue(), truncated
