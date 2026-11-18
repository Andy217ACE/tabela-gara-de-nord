# © 2026 Andy217Ace
"""Statistici v3 sp3: „Ce s-a schimbat săptămâna asta” (`/api/stats/changes`) and the threshold alerts.

Read-only, cached 60 s through `stats_compare.load`. Routes and operators are compared by their % on
time in the last 7 days against the 7 before (arrivals and departures never mixed). A group needs the
minimum sample in BOTH weeks, otherwise it is left out: no percentage is ever invented. Under
HISTORY_MIN_DAYS days of data: status `insufficient` + dictionary key, no lists.
Alerts: a route or an operator whose MEDIAN delay over the last 7 days is above ALERT_MEDIAN_MIN
(a code constant, not configurable from the interface).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from app import stats
from app import stats_compare as cmp

TOP = 3
ALERT_MEDIAN_MIN = 15
KINDS = (("route", "station"), ("operator", "operator"))


def _groups(rows: list[dict], p: stats.Params, field: str) -> dict:
    g: dict = defaultdict(list)
    for j in rows:
        if j[field] and stats.counted(j, p):
            g[(j["board"], j[field])].append(j["result"]["observed_delay"])
    return {k: stats.summarize(v, p.on_time, p.min_sample) for k, v in g.items()}


def _changes(now: list[dict], before: list[dict], p: stats.Params) -> tuple[list, list]:
    better, worse = [], []
    for kind, field in KINDS:
        a, b = _groups(now, p, field), _groups(before, p, field)
        items = []
        for (board, key), s in a.items():
            o = b.get((board, key))
            if not s["sufficient"] or not o or not o["sufficient"]:
                continue
            delta = round(s["on_time_pct"] - o["on_time_pct"], 1)
            if delta:
                items.append({"kind": kind, "board": board, "key": key, "now_pct": s["on_time_pct"],
                              "before_pct": o["on_time_pct"], "delta": delta,
                              "n_now": s["n"], "n_before": o["n"]})
        items.sort(key=lambda x: (-x["delta"], -x["n_now"], x["key"], x["board"]))
        better += [x for x in items if x["delta"] > 0][:TOP]
        worse += sorted((x for x in items if x["delta"] < 0),
                        key=lambda x: (x["delta"], -x["n_now"], x["key"], x["board"]))[:TOP]
    better.sort(key=lambda x: (-x["delta"], x["kind"], x["key"]))
    worse.sort(key=lambda x: (x["delta"], x["kind"], x["key"]))
    return better, worse


def alerts(now: list[dict], p: stats.Params) -> list[dict]:
    """Routes / operators with a median delay above the threshold over the window, worst first."""
    out = []
    for kind, field in KINDS:
        for (board, key), s in _groups(now, p, field).items():
            if s["sufficient"] and s["median"] is not None and s["median"] > ALERT_MEDIAN_MIN:
                out.append({"kind": kind, "board": board, "key": key, "median": s["median"],
                            "n": s["n"], "threshold": ALERT_MEDIAN_MIN})
    out.sort(key=lambda x: (-x["median"], x["kind"], x["key"], x["board"]))
    return out


def changes(store, p: stats.Params, filters: dict, today: date) -> dict:
    now, before, hist = cmp.two_weeks(store, p, filters, today)
    d = cmp.envelope(p, filters, today, hist)
    d["alert_threshold_min"] = ALERT_MEDIAN_MIN
    d["alerts"] = alerts(now, p)
    if not hist["sufficient"]:
        d.update(status="insufficient", message_key=cmp.INSUFFICIENT_KEY, improved=[], worsened=[])
        return d
    better, worse = _changes(now, before, p)
    d.update(status="ok", improved=better, worsened=worse)
    return d
