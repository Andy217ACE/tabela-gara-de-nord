# © 2026 Andy217Ace
"""Calitatea datelor pe zi, pentru administratori (read-only):

1. confirmation_daily  rata de confirmare a călătoriilor pe zi calendaristică (stările din
                       app.journeys, calculate în cod; fantomele nu sunt călătorii);
2. reading_daily       calitatea citirii pe zi (observations.validation_state);
3. coverage_hourly     acoperirea panoului: capturi reușite vs așteptate (60/oră) pe oră/zi.

Zilele se iau din orele locale (Europe/Bucharest) memorate în baza de date. Ziua curentă și
prima zi cu date sunt marcate `partial`. Doar SELECT-uri; nicio scriere în bază.
Rutele: /api/admin/quality-daily/* (admin.require_admin, ca restul /api/admin)."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request

from app import admin, journeys
from app.store import TZ

EXPECTED_PER_HOUR = 60        # panoul e capturat ~1/minut
GAP_THRESHOLD = 0.9           # sub 90 % din capturile așteptate = gol
TREND_PP = 2.0                # variație sub 2 puncte procentuale = stabil
TREND_WINDOW = 7              # zile complete comparate cu cele 7 dinainte
MAX_DAYS = 90
MAX_GAPS = 50

router = APIRouter(prefix="/api/admin/quality-daily",
                   dependencies=[Depends(admin.require_admin)])


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def trend(values: list[float | None]) -> dict:
    """Tendința unei serii de procente (vechi -> nou), fără zilele fără date: media ultimelor
    TREND_WINDOW valori față de media celor TREND_WINDOW dinaintea lor (sau, cu mai puține
    date, a doua jumătate față de prima). `unknown` sub 2 valori."""
    v = [x for x in values if x is not None]
    if len(v) < 2:
        return {"direction": "unknown", "delta_pp": None}
    if len(v) >= 2 * TREND_WINDOW:
        recent, prev = v[-TREND_WINDOW:], v[-2 * TREND_WINDOW:-TREND_WINDOW]
    else:
        half = len(v) // 2
        recent, prev = v[len(v) - half:], v[:half]
    delta = round(sum(recent) / len(recent) - sum(prev) / len(prev), 1)
    direction = "flat" if abs(delta) < TREND_PP else ("up" if delta > 0 else "down")
    return {"direction": direction, "delta_pp": delta}


def _window(now: datetime, days: int) -> tuple[str, str]:
    today = now.astimezone(TZ).date()
    return (today - timedelta(days=days - 1)).isoformat(), today.isoformat()


def _first_day(store, sql: str) -> str | None:
    with store._lock:
        row = store._conn.execute(sql).fetchone()
    return row[0] if row and row[0] else None


# -- 1 -----------------------------------------------------------------------------

def confirmation_daily(store, now: datetime, days: int = 14) -> dict:
    start, today = _window(now, days)
    rows = journeys.query(store, where=["s.service_date >= ?", "s.service_date <= ?",
                                        "COALESCE(q.ghost, 0) = 0"], args=[start, today])
    per: dict[str, Counter] = defaultdict(Counter)
    for s in rows:
        per[s["service_date"]][journeys.result(s)["state"]] += 1
    first = _first_day(store, "SELECT MIN(service_date) FROM services")
    out = []
    for d in sorted(per):
        c = per[d]
        decided = c["confirmed"] + c["unconfirmed"] + c["unknown"]
        out.append({
            "date": d, "confirmed": c["confirmed"], "unconfirmed": c["unconfirmed"],
            "in_progress": c["in_progress"], "unknown": c["unknown"],
            "total": decided + c["in_progress"],
            # procent din călătoriile încheiate: cele în curs nu au încă un rezultat
            "pct_confirmed": _pct(c["confirmed"], decided),
            "partial": d == today or d == first,
        })
    complete = [x["pct_confirmed"] for x in out if not x["partial"]]
    return {"days": out, "first_date": first, "today": today, "trend": trend(complete)}


# -- 2 -----------------------------------------------------------------------------

_STATES = {"ok": "ok", "uncertain": "uncertain", "incomplete": "incomplete",
           "rejected_low_conf": "rejected"}


def reading_daily(store, now: datetime, days: int = 14) -> dict:
    start, today = _window(now, days)
    with store._lock:
        rows = store._conn.execute(
            "SELECT substr(observed_at, 1, 10) AS d, validation_state, COUNT(*) FROM observations"
            " WHERE observed_at >= ? AND observed_at < ? GROUP BY d, validation_state",
            (start, (datetime.fromisoformat(today) + timedelta(days=1)).date().isoformat())
        ).fetchall()
    per: dict[str, Counter] = defaultdict(Counter)
    for d, st, n in rows:
        per[d][_STATES.get(st, "rejected")] += n
    first = _first_day(store, "SELECT MIN(substr(observed_at, 1, 10)) FROM observations")
    out = []
    for d in sorted(per):
        c = per[d]
        total = sum(c.values())
        out.append({
            "date": d, "ok": c["ok"], "uncertain": c["uncertain"],
            "incomplete": c["incomplete"], "rejected": c["rejected"], "total": total,
            "pct_ok": _pct(c["ok"], total), "pct_uncertain": _pct(c["uncertain"], total),
            "pct_incomplete": _pct(c["incomplete"], total), "pct_rejected": _pct(c["rejected"], total),
            "partial": d == today or d == first,
        })
    complete = [x["pct_ok"] for x in out if not x["partial"]]
    return {"days": out, "first_date": first, "today": today, "trend": trend(complete)}


# -- 3 -----------------------------------------------------------------------------

def coverage_hourly(store, now: datetime, days: int = 7,
                    threshold: float = GAP_THRESHOLD) -> dict:
    now = now.astimezone(TZ)
    start, today = _window(now, days)
    with store._lock:
        rows = store._conn.execute(
            "SELECT substr(captured_at, 1, 10), substr(captured_at, 12, 2), ok, COUNT(*)"
            " FROM captures WHERE captured_at >= ? AND captured_at < ? GROUP BY 1, 2, ok",
            (start, (now.date() + timedelta(days=1)).isoformat())).fetchall()
        first_row = store._conn.execute("SELECT MIN(captured_at) FROM captures").fetchone()
    ok_n: Counter = Counter()
    bad_n: Counter = Counter()
    for d, h, ok, n in rows:
        (ok_n if ok else bad_n)[(d, int(h))] += n
    first = first_row[0] if first_row else None
    hours: list[dict] = []
    if first:
        first_dt = datetime.fromisoformat(first).astimezone(TZ).replace(tzinfo=None)
        first_h = first_dt.replace(minute=0, second=0, microsecond=0)
        t = max(datetime.fromisoformat(start), first_h)  # naive local wall clock
        end = now.replace(minute=0, second=0, microsecond=0, tzinfo=None)
        while t <= end:
            key = (t.date().isoformat(), t.hour)
            is_now = t == end
            is_first = t == first_h
            expected = max(1, now.minute) if is_now else EXPECTED_PER_HOUR
            ok = ok_n[key]
            partial = is_now or is_first
            hours.append({
                "date": key[0], "hour": key[1], "ok": ok, "failed": bad_n[key],
                "expected": expected, "pct": _pct(ok, expected),
                "partial": partial,
                "gap": (not partial) and ok < threshold * expected,
            })
            t += timedelta(hours=1)
    per_day: dict[str, dict] = {}
    for h in hours:
        d = per_day.setdefault(h["date"], {"date": h["date"], "ok": 0, "failed": 0, "expected": 0,
                                           "hours_with_gap": 0, "partial": False})
        d["ok"] += h["ok"]
        d["failed"] += h["failed"]
        d["expected"] += h["expected"]
        d["hours_with_gap"] += h["gap"]
        d["partial"] = d["partial"] or h["partial"] or h["date"] == today
    day_list = []
    for d in sorted(per_day):
        x = per_day[d]
        x["pct"] = _pct(x["ok"], x["expected"])
        day_list.append(x)
    gaps = [h for h in reversed(hours) if h["gap"]][:MAX_GAPS]
    return {"days": day_list, "hours": hours, "gaps": gaps, "threshold": threshold,
            "expected_per_hour": EXPECTED_PER_HOUR, "today": today,
            "trend": trend([x["pct"] for x in day_list if not x["partial"]])}


# -- HTTP --------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(TZ)


@router.get("/confirmation")
def confirmation(request: Request, days: int = Query(14, ge=1, le=MAX_DAYS)):
    return confirmation_daily(request.app.state.store, _now(), days)


@router.get("/reading")
def reading(request: Request, days: int = Query(14, ge=1, le=MAX_DAYS)):
    return reading_daily(request.app.state.store, _now(), days)


@router.get("/coverage")
def coverage(request: Request, days: int = Query(7, ge=1, le=MAX_DAYS),
             threshold: float = Query(GAP_THRESHOLD, gt=0, le=1)):
    return coverage_hourly(request.app.state.store, _now(), days, threshold)
