# © 2026 Andy217Ace
"""Statistici — „Cât stă trenul pe panou” (public, read-only).

Durata = services.last_seen − services.first_seen, doar pentru servicii cu status 'gone'
(cele încă pe panou nu au durată finală). Este FEREASTRA DE CONSULTARE observată pe panoul
București Nord (de la prima până la ultima citire), nu orarul real al trenului.

Reguli: mediana ȘI media (media e trasă de cazuri extreme); p90 ca reper; sosirile și
plecările nu se amestecă; duratele negative sau peste MAX_MINUTES (24 h — probabil serviciu
„lipicit” peste o pauză de citire) se exclud; topurile pe tip / stație cer cel puțin
`min_group` servicii, restul se numără în `small_groups_omitted`.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app import stats
from app import stats_overview as overview_v2
from app.stats_platform import read_filters

router = APIRouter()
MAX_MINUTES = 24 * 60
TOP = 8
BOARDS = ("arrival", "departure")
NOTE = ("Este fereastra de consultare observată pe panou (de la prima până la ultima citire), "
        "nu orarul real al trenului.")


def minutes_between(first: str, last: str) -> float | None:
    try:
        m = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds() / 60.0
    except (TypeError, ValueError):
        return None
    return round(m, 1) if 0 <= m <= MAX_MINUTES else None


def summarize(vals) -> dict:
    v = sorted(vals)
    if not v:
        return {"n": 0, "median": None, "mean": None, "p90": None}
    return {"n": len(v), "median": stats._r(stats.percentile(v, 0.5)),
            "mean": stats._r(sum(v) / len(v)), "p90": stats._r(stats.percentile(v, 0.9))}


def _groups(rows: list[dict], field: str, min_group: int) -> tuple[list[dict], int]:
    g: dict = defaultdict(list)
    for r in rows:
        g[r[field]].append(r["minutes"])
    kept = [{field: k, **summarize(v)} for k, v in g.items() if len(v) >= min_group]
    kept.sort(key=lambda x: (-x["n"], str(x[field])))
    return kept[:TOP], sum(1 for v in g.values() if len(v) < min_group)


def compute(rows: list[dict], min_group: int) -> dict:
    types, _ = _groups(rows, "train_type", min_group)
    stations, omitted = _groups(rows, "station", min_group)
    return {
        "status": "ok" if rows else "empty", "n": len(rows), "note": NOTE,
        "min_group": min_group,
        "overall": summarize([r["minutes"] for r in rows]),
        "boards": {b: summarize([r["minutes"] for r in rows if r["board"] == b]) for b in BOARDS},
        "types": types, "stations": stations, "small_groups_omitted": omitted,
    }


def fetch(store, date_from: date | None, date_to: date | None, board: str | None) -> list[dict]:
    where, args = ["s.status = 'gone'"], []
    if date_from:
        where.append("s.service_date >= ?")
        args.append(date_from.isoformat())
    if date_to:
        where.append("s.service_date <= ?")
        args.append(date_to.isoformat())
    if board:
        where.append("s.board = ?")
        args.append(board)
    sql = ("SELECT s.board, s.train_type, s.train_no, s.station, s.first_seen, s.last_seen"
           " FROM services s WHERE " + " AND ".join(where))
    out = []
    with overview_v2._reader(store) as c:
        for r in c.execute(sql, args):
            m = minutes_between(r["first_seen"], r["last_seen"])
            if m is not None:
                out.append({"board": r["board"], "train_type": r["train_type"],
                            "train_no": r["train_no"], "station": r["station"], "minutes": m})
    return out


@router.get("/api/stats/dwell")
async def dwell(request: Request):
    d0, d1, board = read_filters(request)
    store = request.app.state.store

    def run():
        return compute(fetch(store, d0, d1, board), stats.default_min_sample())

    d = await run_in_threadpool(run)
    d["params"] = {"perioada": request.query_params.get("perioada") or "all", "board": board}
    return d
