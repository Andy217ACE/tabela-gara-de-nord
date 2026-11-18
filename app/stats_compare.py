# © 2026 Andy217Ace
"""Statistici v3 sp3: shared read for the new sections and the period comparison.

- `load()` reads the journeys of one window through `stats_overview.fetch` (the same READ-ONLY
  connection and rules: ghosts and the reduced-quality period out, delay = the one read) and caches
  them STATS_CACHE_TTL_S seconds with the mechanism of `stats_overview` (`_fresh` / `_put`).
- `compare()` (`/api/stats/overview?compare=prev7`): the last 7 days next to the 7 before, for the
  figures of the summary. Under HISTORY_MIN_DAYS days of data: status `insufficient` with the
  dictionary key `stats.sp3.insufficient` and no figures (a missing value is never 0).
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import date, datetime, timedelta

from app import stats
from app import stats_overview as so

WINDOW_DAYS = 7
INSUFFICIENT_KEY = "stats.sp3.insufficient"
CACHE_MAX = 16

_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()


def clear_cache() -> None:
    _cache.clear()


def window(today: date) -> dict:
    """The two comparison windows as (first, last) dates: now = last 7 days incl. today."""
    now = (today - timedelta(days=WINDOW_DAYS - 1), today)
    before = (now[0] - timedelta(days=WINDOW_DAYS), now[0] - timedelta(days=1))
    return {"now": now, "before": before}


def window_echo(today: date) -> dict:
    return {k: [a.isoformat(), b.isoformat()] for k, (a, b) in window(today).items()}


def scoped(p: stats.Params, first: date | None, last: date | None) -> stats.Params:
    """The request's thresholds and board, with another date range."""
    return stats.Params(on_time=p.on_time, min_sample=p.min_sample, board=p.board,
                        date_from=first, date_to=last, confirmed_only=p.confirmed_only)


def load(store, p: stats.Params) -> tuple[list[dict], dict]:
    """(journeys with their computed result, extra) of `p`'s date range, cached."""
    key = (id(store), getattr(store, "path", None), tuple(sorted(p.echo().items())))
    ttl = so._ttl()
    hit = so._fresh(_cache, key, ttl)
    if hit is not None:
        return hit
    with _lock:
        hit = so._fresh(_cache, key, ttl)
        if hit is not None:
            return hit
        rows, _wx, extra = so.fetch(store, p)
        so._put(_cache, key, (rows, extra), CACHE_MAX)
        return rows, extra


def select(rows: list[dict], filters: dict, first: date, last: date) -> list[dict]:
    a, b = first.isoformat(), last.isoformat()
    op, tip = filters.get("operator"), filters.get("tip")
    return [j for j in rows if a <= j["service_date"] <= b
            and (not op or j["operator"] == op) and (not tip or j["train_type"] == tip)]


def history(extra: dict) -> dict:
    days = (extra.get("history") or {}).get("days") or 0
    return {"days": days, "needed_days": so.HISTORY_MIN_DAYS, "sufficient": days >= so.HISTORY_MIN_DAYS}


def two_weeks(store, p: stats.Params, filters: dict, today: date):
    """(rows now, rows before, history) over the 14-day span, one cached read."""
    w = window(today)
    rows, extra = load(store, scoped(p, w["before"][0], w["now"][1]))
    return (select(rows, filters, *w["now"]), select(rows, filters, *w["before"]), history(extra))


def envelope(p: stats.Params, filters: dict, today: date, hist: dict) -> dict:
    return {"params": {**p.echo(), "operator": filters.get("operator") or None,
                       "tip": filters.get("tip") or None, "today": today.isoformat()},
            "window": window_echo(today), "history": hist,
            "generated_at": datetime.now(so.TZ).isoformat(timespec="seconds"),
            "cache_ttl_s": so._ttl()}
