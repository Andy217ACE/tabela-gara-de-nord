# © 2026 Andy217Ace
"""Erori de citire pe ferestre glisante (24 h, 48 h, 5 z, 7 z, 30 z, încheiate acum), publice.

Doar numărători agregate, nimic per tren, per rând sau per captură:

- frames / frames_failed   capturi ale tabelei și cele din care nu s-a citit nimic (captures.ok = 0);
- rows                     rânduri cu text (observații, fără liniile goale ale tabelei, `+empty`);
- rows_unread              rânduri cu text din care nu s-a putut citi trenul (`incomplete`) sau
                           respinse pentru încredere prea mică (`rejected_low_conf`);
- rows_partial             tren recunoscut, dar o valoare (de ex. întârzierea) nesigură (`uncertain`);
- ghosts                   trenuri fantomă eliminate (service_quality.ghost), după prima apariție;
- error_rate_pct           (rows_unread + rows_partial) / rows.

Aceleași stări ca `captures._board_counts` (admin) și `system_status.ocr_quality` (#sistem),
care își ia numerele tot de aici (`counts`). Ferestrele sunt intervale absolute (UTC în bază):
24 h înseamnă 24 h reale și la schimbarea orei (Europe/Bucharest). Cache CACHE_TTL_S secunde.
Ruta: GET /api/stats/read-errors."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app import stats_overview
from app.store import TZ

WINDOWS = (("h24", timedelta(hours=24)), ("h48", timedelta(hours=48)), ("d5", timedelta(days=5)),
           ("d7", timedelta(days=7)), ("d30", timedelta(days=30)))
CACHE_TTL_S = 300

router = APIRouter()
_cache: tuple[object, float, dict] | None = None   # (store, monotonic time, result)
_lock = threading.Lock()


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def counts(conn, now: datetime, windows=WINDOWS) -> dict[str, dict]:
    """Raw counts per window: frames, frames_ok, lines (every observation), ok, empty,
    unread, partial, ghosts. One pass per table covers every window."""
    starts = [(now - d).astimezone(timezone.utc).isoformat(timespec="seconds") for _, d in windows]
    oldest = min(starts)

    def sums(expr: str) -> str:   # ?1 is the oldest start (WHERE), ?2.. one per window
        return ", ".join("COALESCE(SUM(" + expr.format(f"?{i + 2}") + "), 0)" for i in range(len(starts)))

    out = {k: dict.fromkeys(("frames", "frames_ok", "lines", "ok", "empty", "unread", "partial",
                             "ghosts"), 0) for k, _ in windows}
    keys = [k for k, _ in windows]

    def add(field, row):
        for k, n in zip(keys, row):
            out[k][field] += n

    # stored as UTC ISO strings: a string comparison is a time comparison
    for ok, *row in conn.execute(f"SELECT ok != 0, {sums('captured_at >= {}')} FROM captures"
                                 " WHERE captured_at >= ?1 GROUP BY 1", (oldest, *starts)):
        add("frames", row)
        if ok:
            add("frames_ok", row)
    for state, empty, *row in conn.execute(
            f"SELECT validation_state, processing_version LIKE '%+empty%', {sums('observed_at >= {}')}"
            " FROM observations WHERE observed_at >= ?1 GROUP BY 1, 2", (oldest, *starts)):
        add("lines", row)
        if state == "ok":
            add("ok", row)
        elif state == "uncertain":
            add("partial", row)
        elif empty and state == "incomplete":
            add("empty", row)   # a blank line of the board: nothing to read, not an error
        else:
            add("unread", row)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='service_quality'").fetchone():
        # first_seen holds a local offset (+02:00/+03:00): julianday compares the instants
        day = (now - max(d for _, d in windows)).astimezone(TZ).date() - timedelta(days=1)
        row = conn.execute(f"SELECT {sums('julianday(s.first_seen) >= julianday({})')}"
                           " FROM services s JOIN service_quality q ON q.service_id = s.id"
                           " WHERE q.ghost = 1 AND s.service_date >= ?1",  # ?1: index, a day of margin
                           (day.isoformat(), *starts)).fetchone()
        add("ghosts", row)
    return out


def summary(c: dict) -> dict:
    rows = c["lines"] - c["empty"]
    return {"frames": c["frames"], "frames_failed": c["frames"] - c["frames_ok"], "rows": rows,
            "rows_unread": c["unread"], "rows_partial": c["partial"], "ghosts": c["ghosts"],
            "error_rate_pct": _pct(c["unread"] + c["partial"], rows)}


def read_errors(store, now: datetime) -> dict:
    global _cache
    with _lock:   # one recompute at a time: concurrent requests after expiry wait for it
        c = _cache
        if c and c[0] is store and time.monotonic() - c[1] < CACHE_TTL_S:
            return c[2]
        with stats_overview._reader(store) as conn:   # own read-only connection: OCR ingest is not blocked
            raw = counts(conn, now)
        out = {"windows": [k for k, _ in WINDOWS],
               "data": {k: summary(v) for k, v in raw.items()},
               "generated_at": now.isoformat(timespec="seconds"), "cache_ttl_s": CACHE_TTL_S}
        _cache = (store, time.monotonic(), out)
        return out


@router.get("/api/stats/read-errors")
async def read_errors_route(request: Request):
    return await run_in_threadpool(read_errors, request.app.state.store, datetime.now(TZ))
