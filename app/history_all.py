# © 2026 Andy217Ace
"""Istoric across all days (`/api/history?all=1`): every journey of ONE train
(`train=N`) or — without a train — of EVERY train, optionally one `date`.

Newest first: (service_date, sched_time, id) DESC, paginated with a keyset cursor
"YYYY-MM-DD_HH:MM_id" so new readings never shift a page. Same data rules as the rest:
- the LIST, like the one-day Istoric, leaves out ghost services (app.quality) and keeps
  the reduced-quality (beta) period, marked `low_quality`;
- the SUMMARY, like the statistics/profile (`stats.load`, `stats.Params.where`), also
  leaves out the reduced-quality period unless STATS_INCLUDE_LOW_QUALITY=1; per board
  (arrivals and departures never mixed), only READ delays (missing is never 0), and below
  the minimum sample `stats.summarize` withholds percentages and p90;
- delays/results are `journeys.result` (confirmed values for services checked
  retroactively); `max_read_delay` ignores delay events marked suspect.
`total`, `period`, `quality` and `summary` describe the WHOLE filtered result, not the page.

Without a train the whole history can be large: the page is read with SQL (keyset +
LIMIT, index on service_date), `total`/`period` with one SQL aggregate (always fresh), and
only `quality`/`summary` need every journey's result — computed outside the store lock
(the lock covers the SQL read only) and cached per store for AGG_TTL_S seconds (or until
the data changes, whichever lasts longer: a new reading every poll would defeat a pure
data-generation cache).
"""
from __future__ import annotations

import re
import time
from datetime import date

from app import journeys, quality, stats
from app.normalize import clean_station

PAGE_MAX = 200
AGG_TTL_S = 60.0  # summary/quality cache for the every-train view (see module doc)
_AGG_MAX = 32     # cached filter combinations per store
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


def max_readings(store, ids: list[int]) -> dict[int, int | None]:
    """Highest delay READ per journey (only ids that have an answer): for services checked
    retroactively the confirmed values (none confirmed -> None = unknown); otherwise the
    delay events not marked suspect (the new value is a reading; a non-zero previous value
    too). Unread frames never produce a delay event."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    with store._lock:
        c = store._conn
        checked = c.execute(
            "SELECT service_id, max_delay_clean, last_delay_clean FROM service_quality"
            f" WHERE delay_checked = 1 AND service_id IN ({marks})", ids).fetchall()
        evs = c.execute(
            "SELECT e.service_id, MAX(CAST(e.new AS INTEGER)) AS mx_new,"
            " MAX(CASE WHEN e.old GLOB '[0-9]*' THEN CAST(e.old AS INTEGER) END) AS mx_old"
            " FROM events e WHERE e.kind = 'delay' AND e.new GLOB '[0-9]*'"
            f" AND NOT {quality.SUSPECT_EVENT_SQL} AND e.service_id IN ({marks})"
            " GROUP BY e.service_id", ids).fetchall()
    out: dict[int, int | None] = {
        r["service_id"]: max(v for v in (r["mx_new"], r["mx_old"]) if v is not None) for r in evs}
    for r in checked:
        out[r["service_id"]] = (None if r["last_delay_clean"] is None
                                else max(r["max_delay_clean"] or 0, r["last_delay_clean"]))
    return out


def _public(j: dict, mx: dict) -> dict:
    r = j["result"]
    read = r["observed_delay"] if r["delay_known"] else None
    if j["id"] in mx and mx[j["id"]] is None:  # checked: nothing confirmed -> unknown
        best = None
    else:
        vals = [v for v in (mx.get(j["id"]), read) if v is not None]
        best = max(vals) if vals else None
    return stats.journey_public(j) | {"max_read_delay": best,
                                      "low_quality": bool(j.get("low_quality"))}


def _where(train: int | None, p: stats.Params, station, time_from, time_to):
    where, args = ["NOT " + quality.GHOST_SQL], []
    if train is not None:
        where.append("s.train_no = ?")
        args.append(train)
    if p.board:
        where.append("s.board = ?")
        args.append(p.board)
    if p.date_from:
        where.append("s.service_date >= ?")
        args.append(p.date_from.isoformat())
    if p.date_to:
        where.append("s.service_date <= ?")
        args.append(p.date_to.isoformat())
    if station:
        q = clean_station(station) or station.strip().upper()
        esc = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        where.append(f"{journeys.STATION_SQL} LIKE ? ESCAPE '!'")
        args.append(f"%{esc}%")
    if time_from:
        where.append("s.sched_time >= ?")
        args.append(time_from)
    if time_to:
        where.append("s.sched_time <= ?")
        args.append(time_to)
    return where, args


def _with_result(rows) -> list[dict]:
    gap = journeys.final_gap_min()
    out = []
    for s in rows:
        d = dict(s)
        d["result"] = journeys.result(s, gap)
        out.append(d)
    return out


def _aggregates(js: list[dict], p: stats.Params) -> dict:
    """quality / low_quality_excluded / summary of the whole filtered result."""
    public = js if quality.include_low_quality() else [j for j in js if not j["low_quality"]]
    return {
        "quality": stats.quality(js),
        "low_quality_excluded": len(js) - len(public),
        "summary": {b: stats.summarize(stats.delays([j for j in public if j["board"] == b], p),
                                       p.on_time, p.min_sample)
                    for b in stats.BOARDS if not p.board or p.board == b},
    }


def page(store, train: int | None, p: stats.Params, *, station: str | None = None,
         time_from: str | None = None, time_to: str | None = None,
         limit: int = PAGE_MAX, cursor: str | None = None) -> dict:
    limit = max(1, min(limit, PAGE_MAX))
    where, args = _where(train, p, station, time_from, time_to)
    if train is None:
        return _page_every_train(store, p, where, args, limit, cursor)
    # one train: at most a few journeys per day — load them all, sort in Python
    js = sorted(_with_result(journeys.query(store, where, args)), key=_key, reverse=True)
    start = 0
    if cursor:
        c = parse_cursor(cursor)
        start = next((i for i, j in enumerate(js) if _key(j) < c), len(js))
    chunk = js[start:start + limit]
    more = start + len(chunk) < len(js)
    dates = [j["service_date"] for j in js]
    period = {"first": min(dates) if dates else None, "last": max(dates) if dates else None,
              "days": len(set(dates))}
    return _finish(store, train, p, len(js), period, _aggregates(js, p), chunk, more)


def _finish(store, train, p, total, period, agg, chunk, more) -> dict:
    mx = max_readings(store, [j["id"] for j in chunk])
    return {
        "mode": "all",
        "train": train,
        "params": p.echo(),
        "total": total,
        "period": period,
        **agg,
        "n": len(chunk),
        "next": _cursor(chunk[-1]) if more and chunk else None,
        "journeys": [_public(j, mx) for j in chunk],
        "final_read_max_gap_min": journeys.final_gap_min(),
    }


_FROM = " FROM services s LEFT JOIN service_quality q ON q.service_id = s.id WHERE "


def _page_every_train(store, p, where, args, limit, cursor) -> dict:
    w, a = list(where), list(args)
    if cursor:
        w.append("(s.service_date, s.sched_time, s.id) < (?, ?, ?)")
        a.extend(parse_cursor(cursor))
    rows = journeys.query(store, w, a, order="s.service_date DESC, s.sched_time DESC, s.id DESC",
                          limit=limit + 1)
    more = len(rows) > limit
    chunk = _with_result(rows[:limit])
    with store._lock:
        r = store._conn.execute(
            "SELECT COUNT(*), MIN(s.service_date), MAX(s.service_date),"
            " COUNT(DISTINCT s.service_date)" + _FROM + " AND ".join(where), args).fetchone()
    period = {"first": r[1], "last": r[2], "days": r[3]}
    return _finish(store, None, p, r[0], period, _cached_aggregates(store, p, where, args), chunk, more)


def _cached_aggregates(store, p, where, args) -> dict:
    key = (tuple(where), tuple(args), p.on_time, p.min_sample, p.board, p.confirmed_only,
           quality.include_low_quality(), journeys.final_gap_min())
    with store._lock:
        stamp = tuple(store._conn.execute(
            "SELECT (SELECT MAX(id) FROM runs), (SELECT MAX(id) FROM events),"
            " (SELECT COUNT(*) FROM services), (SELECT MAX(id) FROM services),"
            " (SELECT COUNT(*) FROM service_quality)").fetchone())
    cache = store.__dict__.setdefault("_history_agg", {})
    hit = cache.get(key)
    now = time.monotonic()
    if hit is not None and (hit[0] == stamp or now - hit[1] < AGG_TTL_S):
        return hit[2]
    agg = _aggregates(_with_result(journeys.query(store, where, args)), p)
    if len(cache) >= _AGG_MAX:
        cache.clear()
    cache[key] = (stamp, now, agg)
    return agg
