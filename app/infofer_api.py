# © 2026 Andy217Ace
"""Admin view of the INTERNAL Infofer spike (``GET /api/admin/infofer``, page #infofer).

Reads ``INFOFER_DB`` (default /var/lib/tabela/infofer.db, written by scripts/infofer_collect.py)
and the main DB, both READ-ONLY. Admin only, ``no-store``: Infofer terms forbid public display.
Never a 500: a locked/broken DB gives an ``error`` field instead."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app import admin
from app.journeys import TZ, sched_at

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/infofer", dependencies=[Depends(admin.require_admin)])

DEFAULT_DB = "/var/lib/tabela/infofer.db"
SPIKE_DAYS = 7
STALE_PASSED = 15  # same threshold as scripts/infofer_analyze.MAX_PASSED
OK_MAX_GAP = timedelta(minutes=10)
OK_MAX_FAIL_PCT = 20.0
LIVE_AHEAD = timedelta(hours=3)
LIVE_BEHIND = timedelta(hours=6)  # still on the board (status listed) but late
ACCURACY_TTL_S = 300.0
_acc: dict = {"key": None, "at": 0.0, "value": None}
_acc_lock = threading.Lock()


def db_path() -> str:
    return os.environ.get("INFOFER_DB", DEFAULT_DB)


def _ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True, timeout=3)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def health(conn: sqlite3.Connection, now: datetime) -> tuple[dict, list[dict]]:
    since = _iso(now.astimezone(timezone.utc) - timedelta(hours=24))  # fetched_at is UTC ISO: lexical compare
    fail = "(error IS NOT NULL OR n_markers = 0)"
    total, first = conn.execute("SELECT COUNT(*), MIN(fetched_at) FROM infofer_runs").fetchone()
    runs24, failed24, avg24 = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM({fail}), 0), AVG(n_markers) FROM infofer_runs"
        " WHERE fetched_at >= ?", (since,)).fetchone()
    last = conn.execute("SELECT fetched_at, http_status, n_markers, bytes, error FROM infofer_runs"
                        " ORDER BY fetched_at DESC LIMIT 1").fetchone()
    last_ok = conn.execute(f"SELECT MAX(fetched_at) FROM infofer_runs WHERE NOT {fail}").fetchone()[0]
    fail_pct = round(100 * failed24 / runs24, 1) if runs24 else None
    problems = []
    if not last_ok or now - datetime.fromisoformat(last_ok) > OK_MAX_GAP:
        problems.append("stale")
    if fail_pct is not None and fail_pct > OK_MAX_FAIL_PCT:
        problems.append("failures")
    days = (now - datetime.fromisoformat(first)).total_seconds() / 86400 if first else None
    h = {"ok": not problems, "problems": problems, "runs_total": total, "runs_24h": runs24,
         "failed_24h": failed24, "fail_pct_24h": fail_pct,
         "avg_markers_24h": round(avg24, 1) if avg24 is not None else None,
         "last_run": dict(zip(("at", "http_status", "n_markers", "bytes", "error"), last)) if last else None,
         "last_ok_at": last_ok, "first_run_at": first,
         "days_elapsed": round(days, 1) if days is not None else None, "days_target": SPIKE_DAYS}
    hourly = [{"hour": hr + ":00:00+00:00", "runs": n, "failed": f,
               "avg_markers": round(a, 1) if a is not None else None}
              for hr, n, f, a in conn.execute(
                  f"SELECT substr(fetched_at, 1, 13) AS hr, COUNT(*), SUM({fail}), AVG(n_markers)"
                  " FROM infofer_runs WHERE fetched_at >= ? GROUP BY hr ORDER BY hr", (since,))]
    return h, hourly


def live(conn: sqlite3.Connection, main: sqlite3.Connection, now: datetime) -> dict:
    """Trains of the latest Infofer snapshot that are also on our arrival board now."""
    at = conn.execute("SELECT MAX(fetched_at) FROM infofer_obs").fetchone()[0]
    if not at:
        return {"fetched_at": None, "trains": []}
    inf = {}
    for sd, no, cat, dl, rep, passed in conn.execute(
            "SELECT service_date, train_no, category, delay_min, report_hhmm, passed_time"
            " FROM infofer_obs WHERE fetched_at = ?", (at,)):
        inf[(sd, no.lstrip("0") or "0")] = (cat, dl, rep, passed)
    today = now.astimezone(TZ).date()
    days = [(today - timedelta(days=1)).isoformat(), today.isoformat()]
    trains = []
    for sd, no, tt, st, station, last_delay in main.execute(
            "SELECT service_date, train_no, train_type, sched_time, station, last_delay FROM services"
            " WHERE board = 'arrival' AND status = 'listed' AND service_date IN (?, ?)", days):
        sch = sched_at(sd, st)
        if not now - LIVE_BEHIND <= sch <= now + LIVE_AHEAD:
            continue
        # Infofer's date is the train's departure day: an after-midnight arrival may carry the day before
        prev = (date.fromisoformat(sd) - timedelta(days=1)).isoformat()
        hit = inf.get((sd, str(no))) or inf.get((prev, str(no)))
        if not hit:
            continue
        cat, dl, rep, passed = hit
        trains.append({"train_no": no, "train_type": tt, "category": cat, "station": station,
                       "service_date": sd, "sched_time": st, "board_delay": last_delay,
                       "infofer_delay": dl, "report_hhmm": rep, "passed_time": passed,
                       "stale": passed is not None and passed >= STALE_PASSED})
    trains.sort(key=lambda t: (t["service_date"], t["sched_time"]))
    return {"fetched_at": at, "trains": trains}


def accuracy(inf_path: str, main_path: str) -> dict:
    """scripts/infofer_analyze.analyze (no duplicate logic), cached ACCURACY_TTL_S."""
    key = (inf_path, main_path)
    with _acc_lock:
        if _acc["key"] == key and time.monotonic() - _acc["at"] < ACCURACY_TTL_S:
            return _acc["value"]
    from scripts import infofer_analyze  # lazy: heavy, and only this page needs it
    inf, main = _ro(inf_path), _ro(main_path)
    try:
        r = infofer_analyze.analyze(inf, main)
    finally:
        inf.close()
        main.close()
    value = {"period": list(r["period"]), "horizons": {str(h): s for h, s in r["horizons"].items()},
             "computed_at": _iso(datetime.now(timezone.utc))}
    with _acc_lock:
        _acc.update(key=key, at=time.monotonic(), value=value)
    return value


def overview(inf_path: str, main_path: str, now: datetime | None = None) -> dict:
    if not os.path.isfile(inf_path):
        return {"enabled": False}
    now = now or datetime.now(timezone.utc)
    out: dict = {"enabled": True, "now": _iso(now)}
    try:
        conn, main = _ro(inf_path), _ro(main_path)
        try:
            out["health"], out["hourly"] = health(conn, now)
            out["live"] = live(conn, main, now)
        finally:
            conn.close()
            main.close()
    except Exception as e:  # locked / corrupt / schema drift: report, never 500
        log.warning("infofer: citire esuata (%s)", type(e).__name__)
        out["error"] = f"{type(e).__name__}: {e}"[:200]
        return out
    try:
        out["accuracy"] = accuracy(inf_path, main_path)
    except Exception as e:
        log.warning("infofer: analiza esuata (%s)", type(e).__name__)
        out["accuracy_error"] = f"{type(e).__name__}: {e}"[:200]
    return out


@router.get("")
async def get_infofer(request: Request):
    return admin._json(await run_in_threadpool(
        overview, db_path(), request.app.state.settings.db_path))
