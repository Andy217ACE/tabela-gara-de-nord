# © 2026 Andy217Ace
"""Istoric — every journey of ONE train across all days (`/api/history?train=N&all=1`).

Journeys come from `stats.load` (same exclusions and computed final result as the
catalog, profile and statistics), newest first: (service_date, sched_time, id) DESC,
paginated with a keyset cursor "YYYY-MM-DD_HH:MM_id" so new readings never shift a page.
`total`, `period`, `quality` and `summary` always describe the WHOLE filtered result, not
the page. The summary is per board (arrivals and departures are never mixed) and uses only
delays that were READ (missing is never 0); below the minimum sample `stats.summarize`
withholds percentages and p90.
"""
from __future__ import annotations

import re
from datetime import date

from app import journeys, stats
from app.normalize import clean_station

PAGE_MAX = 200
_CURSOR = re.compile(r"^(\d{4}-\d{2}-\d{2})_((?:[01]\d|2[0-3]):[0-5]\d)_(\d{1,12})$")


def parse_cursor(raw: str) -> tuple[str, str, int]:
    m = _CURSOR.match(raw or "")
    if not m:
        raise ValueError("cursor")
    date.fromisoformat(m.group(1))  # ValueError for an impossible day
    return m.group(1), m.group(2), int(m.group(3))


def _key(j: dict) -> tuple[str, str, int]:
    return j["service_date"], j["sched_time"] or "", j["id"]


def _cursor(j: dict) -> str:
    d, t, i = _key(j)
    return f"{d}_{t}_{i}"


def max_readings(store, ids: list[int]) -> dict[int, int]:
    """Highest delay READ per journey from its delay events (the new value is a reading; a
    non-zero previous value too). Unread frames never produce a delay event."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    with store._lock:
        rows = store._conn.execute(
            "SELECT service_id, MAX(CAST(new AS INTEGER)) AS mx_new,"
            " MAX(CASE WHEN old GLOB '[0-9]*' THEN CAST(old AS INTEGER) END) AS mx_old"
            " FROM events WHERE kind = 'delay' AND new GLOB '[0-9]*'"
            f" AND service_id IN ({marks}) GROUP BY service_id", ids).fetchall()
    return {r["service_id"]: max(v for v in (r["mx_new"], r["mx_old"]) if v is not None)
            for r in rows}


def _public(j: dict, ev_max: int | None) -> dict:
    r = j["result"]
    vals = [v for v in (ev_max, r["observed_delay"] if r["delay_known"] else None) if v is not None]
    return stats.journey_public(j) | {"max_read_delay": max(vals) if vals else None}


def page(store, train: int, p: stats.Params, *, station: str | None = None,
         time_from: str | None = None, time_to: str | None = None,
         limit: int = PAGE_MAX, cursor: str | None = None) -> dict:
    where, args = ["s.train_no = ?"], [train]
    if station:
        q = clean_station(station) or station.strip().upper()
        esc = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        where.append("s.station LIKE ? ESCAPE '!'")
        args.append(f"%{esc}%")
    if time_from:
        where.append("s.sched_time >= ?")
        args.append(time_from)
    if time_to:
        where.append("s.sched_time <= ?")
        args.append(time_to)
    js = sorted(stats.load(store, p, where, args), key=_key, reverse=True)
    start = 0
    if cursor:
        c = parse_cursor(cursor)
        start = next((i for i, j in enumerate(js) if _key(j) < c), len(js))
    chunk = js[start:start + max(1, min(limit, PAGE_MAX))]
    more = start + len(chunk) < len(js)
    evmax = max_readings(store, [j["id"] for j in chunk])
    dates = [j["service_date"] for j in js]
    return {
        "mode": "all",
        "train": train,
        "params": p.echo(),
        "total": len(js),
        "period": {"first": min(dates) if dates else None, "last": max(dates) if dates else None,
                   "days": len(set(dates))},
        "quality": stats.quality(js),
        "summary": {b: stats.summarize(stats.delays([j for j in js if j["board"] == b], p),
                                       p.on_time, p.min_sample)
                    for b in stats.BOARDS if not p.board or p.board == b},
        "n": len(chunk),
        "next": _cursor(chunk[-1]) if more and chunk else None,
        "journeys": [_public(j, evmax.get(j["id"])) for j in chunk],
        "final_read_max_gap_min": journeys.final_gap_min(),
    }
