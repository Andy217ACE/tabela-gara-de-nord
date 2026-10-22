# © 2026 Andy217Ace
"""Delay statistics over journeys (pure functions + catalog/global aggregates).

Rules: only finished journeys whose delay was READ count (missing is never 0); the
delay is the one shown on the București Nord board; arrivals and departures are
always summarised separately; every figure carries N (journeys). Below the minimum
sample the raw numbers stay but percentages and p90 are withheld (`sufficient`).
"""
from __future__ import annotations

import csv
import io
import json
import os
from collections import defaultdict
from datetime import date

from app import journeys
from app import quality as dq

ON_TIME_MAX_DEFAULT = 5     # env ON_TIME_MAX_MIN: delay <= this counts as "la timp"
MIN_SAMPLE_DEFAULT = 5      # env STATS_MIN_SAMPLE: below this, no percentages
OVER = 30                   # "> 30 min" bucket
BOARDS = ("arrival", "departure")
BUCKETS = (("0", 0, 0), ("1–5", 1, 5), ("6–15", 6, 15), ("16–30", 16, 30),
           ("31–60", 31, 60), ("> 60", 61, None))
WEEKDAYS = ("luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică")


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.environ.get(name, default))
    except ValueError:
        return default
    return v if lo <= v <= hi else default


def default_on_time() -> int:
    return _env_int("ON_TIME_MAX_MIN", ON_TIME_MAX_DEFAULT, 0, 60)


def default_min_sample() -> int:
    return _env_int("STATS_MIN_SAMPLE", MIN_SAMPLE_DEFAULT, 1, 1000)


def percentile(sorted_vals: list[float], q: float) -> float | None:
    """Linear interpolation between closest ranks (q in [0, 1])."""
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 1)


def summarize(values, on_time_max: int, min_sample: int) -> dict:
    vals = sorted(int(v) for v in values if v is not None)
    n = len(vals)
    if not n:
        return {"n": 0, "mean": None, "median": None, "p90": None, "max": None,
                "on_time": 0, "on_time_pct": None, "over_30": 0, "over_30_pct": None,
                "sufficient": False}
    on_time = sum(1 for v in vals if v <= on_time_max)
    over = sum(1 for v in vals if v > OVER)
    ok = n >= min_sample
    return {
        "n": n,
        "mean": _r(sum(vals) / n),
        "median": _r(percentile(vals, 0.5)),
        "p90": _r(percentile(vals, 0.9)) if ok else None,
        "max": vals[-1],
        "on_time": on_time,
        "on_time_pct": _r(100.0 * on_time / n) if ok else None,
        "over_30": over,
        "over_30_pct": _r(100.0 * over / n) if ok else None,
        "sufficient": ok,
    }


def distribution(values) -> list[dict]:
    out = []
    for label, lo, hi in BUCKETS:
        out.append({"label": label, "n": sum(1 for v in values if v is not None and v >= lo
                                             and (hi is None or v <= hi))})
    return out


# ---- journey sets ---------------------------------------------------------------------

class Params:
    """Validated request parameters (see stats_api.parse_params)."""

    def __init__(self, on_time: int | None = None, min_sample: int | None = None,
                 board: str | None = None, date_from: date | None = None,
                 date_to: date | None = None, confirmed_only: bool = False):
        self.on_time = default_on_time() if on_time is None else on_time
        self.min_sample = default_min_sample() if min_sample is None else min_sample
        self.board = board
        self.date_from = date_from
        self.date_to = date_to
        self.confirmed_only = confirmed_only

    def where(self) -> tuple[list[str], list]:
        # never ghosts; the reduced-quality (beta) period only with STATS_INCLUDE_LOW_QUALITY=1
        w, a = [dq.public_services_where("s")], []
        if self.board:
            w.append("s.board = ?")
            a.append(self.board)
        if self.date_from:
            w.append("s.service_date >= ?")
            a.append(self.date_from.isoformat())
        if self.date_to:
            w.append("s.service_date <= ?")
            a.append(self.date_to.isoformat())
        return w, a

    def echo(self) -> dict:
        return {"on_time_max_min": self.on_time, "min_sample": self.min_sample,
                "board": self.board,
                "from": self.date_from.isoformat() if self.date_from else None,
                "to": self.date_to.isoformat() if self.date_to else None,
                "confirmed_only": self.confirmed_only,
                "include_low_quality": dq.include_low_quality(),
                "final_read_max_gap_min": journeys.final_gap_min()}


_CACHE_MAX = 16  # cached journey sets per store and data generation (store._stats_cache)


def load(store, p: Params, where: list[str] | None = None, args: list | None = None) -> list[dict]:
    """Journeys matching the params, each with its computed result. Read-only for callers:
    the list is cached until the data changes (new run or new event)."""
    w, a = p.where()
    w, a = w + (where or []), a + (args or [])
    gap = journeys.final_gap_min()
    with store._lock:
        stamp = store._conn.execute(
            "SELECT (SELECT MAX(id) FROM runs), (SELECT MAX(id) FROM events),"
            " (SELECT COUNT(*) FROM services), (SELECT MAX(id) FROM services)").fetchone()
    # One generation per store: any new run/event/service drops every cached set (the
    # dict is only touched under the GIL; a race at worst recomputes or serves the
    # previous generation for one request).
    if store.__dict__.get("_stats_stamp") != tuple(stamp):
        store.__dict__["_stats_cache"] = {}
        store.__dict__["_stats_stamp"] = tuple(stamp)
    cache = store.__dict__["_stats_cache"]
    key = (tuple(w), tuple(a), gap)
    hit = cache.get(key)
    if hit is not None:
        return hit
    rows = journeys.query(store, w, a)
    out = []
    for s in rows:
        d = dict(s)
        d["result"] = journeys.result(s, gap)
        out.append(d)
    if len(cache) >= _CACHE_MAX:
        cache.clear()
    cache[key] = out
    return out


def counted(j: dict, p: Params) -> bool:
    """Does this journey's delay enter the statistics?"""
    r = j["result"]
    if p.confirmed_only:
        return r["state"] == "confirmed"
    return r["state"] in ("confirmed", "unconfirmed") and r["delay_known"]


def delays(js: list[dict], p: Params) -> list[int]:
    return [j["result"]["observed_delay"] for j in js if counted(j, p)]


def quality(js: list[dict]) -> dict:
    states = {s: 0 for s in journeys.STATES}
    for j in js:
        states[j["result"]["state"]] += 1
    n = len(js)
    finished = n - states["in_progress"]
    known = sum(1 for j in js if j["result"]["delay_known"] and j["status"] == "gone")
    return {
        "journeys": n,
        "finished": finished,
        "delay_known": known,
        "delay_known_pct": _r(100.0 * known / finished) if finished else None,
        "states": states,
        "uncertain_names": sum(1 for j in js if j["uncertain"]),
    }


def _board_summaries(js, p):
    return {b: summarize(delays([j for j in js if j["board"] == b], p), p.on_time, p.min_sample)
            for b in BOARDS if not p.board or p.board == b}


def _grouped(js, p, keyfn, keys=None) -> list[dict]:
    groups: dict = defaultdict(list)
    for j in js:
        if counted(j, p):
            groups[keyfn(j)].append(j["result"]["observed_delay"])
    order = keys if keys is not None else sorted(groups)
    return [{"key": k, **summarize(groups.get(k, []), p.on_time, p.min_sample)} for k in order]


def by_time(js, p) -> dict:
    """Per board: by scheduled hour, by weekday of the service date, by month."""
    out = {}
    for b in BOARDS:
        if p.board and p.board != b:
            continue
        bj = [j for j in js if j["board"] == b]
        out[b] = {
            "hour": _grouped(bj, p, lambda j: int(j["sched_time"][:2]), list(range(24))),
            "weekday": [dict(g, label=WEEKDAYS[g["key"]]) for g in
                        _grouped(bj, p, lambda j: date.fromisoformat(j["service_date"]).weekday(),
                                 list(range(7)))],
            "month": _grouped(bj, p, lambda j: j["service_date"][:7]),
        }
    return out


def overview(store, p: Params) -> dict:
    js = load(store, p)
    with store._lock:
        n_obs = store._conn.execute(
            "SELECT COUNT(*) FROM observations WHERE validation_state IN ('ok','uncertain')"
        ).fetchone()[0] if _has(store, "observations") else 0
    dates = [j["service_date"] for j in js]
    return {
        "params": p.echo(),
        "period": {"first": min(dates) if dates else None, "last": max(dates) if dates else None,
                   "days": len(set(dates))},
        "trains": len({j["train_no"] for j in js}),
        "observations": n_obs,
        "quality": quality(js),
        "boards": _board_summaries(js, p),
        "distribution": {b: distribution(delays([j for j in js if j["board"] == b], p))
                         for b in BOARDS if not p.board or p.board == b},
        "by_time": by_time(js, p),
    }


def _has(store, table: str) -> bool:
    return store._conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                               (table,)).fetchone() is not None


def _catalog_extra(store) -> dict:
    """Per train number: observations count and observed operators from `trains`."""
    if not _has(store, "trains"):
        return {}
    with store._lock:
        rows = store._conn.execute("SELECT train_no, observations, operators_json FROM trains"
                                   ).fetchall()
    out = {}
    for r in rows:
        try:
            ops = [o.get("operator") for o in json.loads(r["operators_json"] or "[]")
                   if isinstance(o, dict)]
        except ValueError:
            ops = []
        out[r["train_no"]] = {"observations": r["observations"], "operators": ops}
    return out


def train_entries(js: list[dict], p: Params, extra: dict | None = None) -> list[dict]:
    """One entry per (train number, board): the catalog row."""
    groups: dict = defaultdict(list)
    for j in js:
        groups[(j["train_no"], j["board"])].append(j)
    extra = extra or {}
    out = []
    for (no, board), g in groups.items():
        g.sort(key=lambda j: (j["service_date"], j["sched_time"]))
        last = g[-1]
        out.append({
            "train_no": no, "board": board,
            "train_type": last["train_type"], "station": last["station"],
            "operator": last["operator"],
            "stations": sorted({j["station"] for j in g}),
            "journeys": len(g),
            "first_date": g[0]["service_date"], "last_date": last["service_date"],
            "observations": (extra.get(no) or {}).get("observations"),
            "quality": quality(g),
            "stats": summarize(delays(g, p), p.on_time, p.min_sample),
        })
    out.sort(key=lambda e: (e["train_no"], e["board"]))
    return out


def catalog(store, p: Params, query: str | None = None) -> dict:
    where, args = [], []
    if query:
        q = query.strip().upper()
        if q.isdigit():
            where.append("CAST(s.train_no AS TEXT) LIKE ?")
            args.append(q + "%")
        else:
            esc = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            where.append(f"({journeys.STATION_SQL} LIKE ? ESCAPE '!'"
                         " OR UPPER(COALESCE(q.operator_canonical, s.operator)) LIKE ? ESCAPE '!')")
            args += [f"%{esc}%", f"%{esc}%"]
    js = load(store, p, where, args)
    entries = train_entries(js, p, _catalog_extra(store))
    return {"params": p.echo(), "n": len(entries), "trains": entries}


def train_profile(store, no: int, p: Params) -> dict | None:
    js = load(store, p, ["s.train_no = ?"], [no])
    if not js:
        return None
    extra = _catalog_extra(store).get(no) or {}
    return {
        "params": p.echo(),
        "train_no": no,
        "observations": extra.get("observations"),
        "operators": extra.get("operators") or sorted({j["operator"] for j in js}),
        "entries": train_entries(js, p),
        "distribution": {b: distribution(delays([j for j in js if j["board"] == b], p))
                         for b in BOARDS if not p.board or p.board == b},
        "journeys": [journey_public(j) for j in
                     sorted(js, key=lambda j: (j["service_date"], j["sched_time"]), reverse=True)],
    }


def journey_public(j: dict) -> dict:
    return {k: j[k] for k in ("id", "board", "service_date", "train_type", "train_no", "station",
                              "operator", "sched_time", "status")} | {
        "platform": j["last_platform"], "uncertain": bool(j["uncertain"]), "result": j["result"]}


def rankings(store, p: Params, limit: int = 10) -> dict:
    js = load(store, p)
    entries = train_entries(js, p)
    ranked = [e for e in entries if e["stats"]["n"] >= p.min_sample]
    below = sum(1 for e in entries if 0 < e["stats"]["n"] < p.min_sample)
    delayed = sorted(ranked, key=lambda e: (-e["stats"]["mean"], -e["stats"]["median"],
                                            e["train_no"]))
    punctual = sorted(ranked, key=lambda e: (-e["stats"]["on_time_pct"], e["stats"]["mean"],
                                             e["train_no"]))
    return {"params": p.echo(), "eligible": len(ranked), "below_min": below,
            "most_delayed": delayed[:limit], "most_punctual": punctual[:limit]}


# ---- CSV -----------------------------------------------------------------------------

def to_csv(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    buf.write("﻿")  # BOM: Excel opens UTF-8 (diacritics) correctly
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(header)
    for r in rows:
        w.writerow([_cell(v) for v in r])
    return buf.getvalue()


def _cell(v):
    """CSV cell; text starting like a spreadsheet formula is prefixed with ' (inert)."""
    if v is None:
        return ""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


STAT_COLS = ["n", "mean", "median", "p90", "max", "on_time", "on_time_pct", "over_30",
             "over_30_pct", "sufficient"]


def entries_csv(entries: list[dict]) -> str:
    head = ["train_no", "board", "train_type", "station", "operator", "journeys",
            "delay_known", "confirmed", "unknown", "first_date", "last_date"] + STAT_COLS
    rows = [[e["train_no"], e["board"], e["train_type"], e["station"], e["operator"],
             e["journeys"], e["quality"]["delay_known"], e["quality"]["states"]["confirmed"],
             e["quality"]["states"]["unknown"], e["first_date"], e["last_date"]]
            + [e["stats"][c] for c in STAT_COLS] for e in entries]
    return to_csv(head, rows)


def journeys_csv(items: list[dict]) -> str:
    head = ["id", "service_date", "board", "train_type", "train_no", "station", "operator",
            "sched_time", "platform", "status", "result", "observed_delay_min",
            "final_delay_min", "delay_read_at", "disappeared_at", "reason"]
    rows = [[j["id"], j["service_date"], j["board"], j["train_type"], j["train_no"],
             j["station"], j["operator"], j["sched_time"], j["platform"], j["status"],
             j["result"]["state"], j["result"]["observed_delay"], j["result"]["final_delay"],
             j["result"]["delay_read_at"], j["result"]["disappeared_at"], j["result"]["reason"]]
            for j in items]
    return to_csv(head, rows)
