# © 2026 Andy217Ace
"""Statistici — „Peroane schimbate după anunț” (public, read-only).

Un serviciu „și-a schimbat peronul” când panoul a arătat cel puțin două valori DISTINCTE de
peron valide pentru el (events kind='platform', coloana `new`; `old` e mereu NULL). Reguli:

- valorile ne-numerice sau în afara 1..PLATFORM_MAX (14 linii la Gara de Nord, vezi
  app.normalize) sunt citiri OCR greșite și se ignoră (numărate în `ignored_values`);
- duplicatele consecutive se comprimă; perechile din→în sunt tranzițiile consecutive
  (3→4→3 dă 3→4 și 4→3 și numără ca un serviciu schimbat);
- numitorul = serviciile cu cel puțin un peron valid (cele fără peron nu se pot compara);
- sub `min_sample` servicii nu se afișează procent; sub SMALL_N servicii sau SMALL_CHANGED
  schimbări, `small_sample` = True („date puține”);
- sosirile și plecările nu se amestecă în procentul pe panou (`boards`).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app import journeys, stats
from app import stats_overview as overview_v2
from app.normalize import PLATFORM_MAX

router = APIRouter()
SMALL_N = 30            # sub atâtea servicii cu peron: „date puține”
SMALL_CHANGED = 5       # sub atâtea schimbări: topurile sunt orientative
TOP = 8
BOARDS = ("arrival", "departure")


# ---- pure parts -----------------------------------------------------------------------------

def clean_values(raw) -> tuple[list[int], int]:
    """Valid platform numbers in order (consecutive duplicates collapsed) + ignored count."""
    out: list[int] = []
    ignored = 0
    for v in raw:
        s = str(v).strip() if v is not None else ""
        if not (s.isascii() and s.isdigit() and 1 <= int(s) <= PLATFORM_MAX):
            ignored += 1
            continue
        n = int(s)
        if not out or out[-1] != n:
            out.append(n)
    return out, ignored


def transitions(vals: list[int]) -> list[tuple[int, int]]:
    return list(zip(vals, vals[1:]))


def _pct(k: int, n: int, min_sample: int) -> float | None:
    return round(100.0 * k / n, 1) if n and n >= min_sample else None


def compute(services: list[dict], min_sample: int) -> dict:
    ignored = 0
    n = changed = 0
    pairs: Counter = Counter()
    boards = {b: {"n": 0, "changed": 0} for b in BOARDS}
    trains: dict = defaultdict(lambda: {"seen": 0, "changed": 0, "pairs": Counter()})
    sts: dict = defaultdict(lambda: {"seen": 0, "changed": 0})
    for s in services:
        vals, ign = clean_values(s["values"])
        ignored += ign
        if not vals:
            continue
        n += 1
        tr = transitions(vals)
        is_ch = len(set(vals)) > 1
        key = (s["train_type"], s["train_no"], s["station"], s["board"])
        t, st = trains[key], sts[s["station"]]
        t["seen"] += 1
        st["seen"] += 1
        if s["board"] in boards:
            boards[s["board"]]["n"] += 1
        if is_ch:
            changed += 1
            t["changed"] += 1
            st["changed"] += 1
            if s["board"] in boards:
                boards[s["board"]]["changed"] += 1
            for a, b in tr:
                pairs[(a, b)] += 1
                t["pairs"][(a, b)] += 1
    out_trains = []
    for (tt, no, station, board), t in trains.items():
        if not t["changed"]:
            continue
        a, b = sorted(t["pairs"].items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        out_trains.append({"train_type": tt, "train_no": no, "station": station, "board": board,
                           "changed": t["changed"], "seen": t["seen"], "pair": {"from": a, "to": b}})
    out_trains.sort(key=lambda x: (-x["changed"], -x["changed"] / x["seen"], x["train_no"]))
    out_st = [{"station": k, "changed": v["changed"], "seen": v["seen"],
               "pct": _pct(v["changed"], v["seen"], min_sample)}
              for k, v in sts.items() if v["changed"]]
    out_st.sort(key=lambda x: (-x["changed"], -x["changed"] / x["seen"], x["station"]))
    small = n < SMALL_N or changed < SMALL_CHANGED
    return {
        "status": "ok" if n else "empty",
        "n_with_platform": n, "n_changed": changed,
        "pct_changed": _pct(changed, n, min_sample),
        "small_sample": small, "min_sample": min_sample,
        "ignored_values": ignored, "platform_max": PLATFORM_MAX,
        "boards": {b: {"n": v["n"], "changed": v["changed"],
                      "pct": _pct(v["changed"], v["n"], min_sample)} for b, v in boards.items()},
        "pairs": [{"from": a, "to": b, "n": k} for (a, b), k in
                  sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP * 2]],
        "trains": out_trains[:TOP], "stations": out_st[:TOP],
    }


# ---- reading --------------------------------------------------------------------------------

def fetch(store, date_from: date | None, date_to: date | None, board: str | None) -> list[dict]:
    where, args = [], []
    if date_from:
        where.append("s.service_date >= ?")
        args.append(date_from.isoformat())
    if date_to:
        where.append("s.service_date <= ?")
        args.append(date_to.isoformat())
    if board:
        where.append("s.board = ?")
        args.append(board)
    sql = ("SELECT s.id, s.board, s.train_type, s.train_no, s.station FROM services s"
           + (" WHERE " + " AND ".join(where) if where else ""))
    with overview_v2._reader(store) as c:
        rows = c.execute(sql, args).fetchall()
        by_id = {r["id"]: {"id": r["id"], "board": r["board"], "train_type": r["train_type"],
                           "train_no": r["train_no"], "station": r["station"], "values": []}
                 for r in rows}
        for e in c.execute("SELECT e.service_id, e.new FROM events e JOIN services s"
                           " ON s.id = e.service_id WHERE e.kind = 'platform'"
                           + (" AND " + " AND ".join(where) if where else "")
                           + " ORDER BY e.ts, e.id", args):
            if e["service_id"] in by_id:
                by_id[e["service_id"]]["values"].append(e["new"])
    return list(by_id.values())


def read_filters(request: Request) -> tuple[date | None, date | None, str | None]:
    """`perioada` (1|7|30|all) and `board`; 422 on anything else."""
    q = request.query_params
    perioada = q.get("perioada") or "all"
    if perioada not in overview_v2.PERIODS:
        raise HTTPException(status_code=422, detail="Perioadă invalidă (1, 7, 30 sau all).")
    board = q.get("board") or None
    if board is not None and board not in BOARDS:
        raise HTTPException(status_code=422, detail="Panou invalid (arrival sau departure).")
    d0, d1 = overview_v2.period_range(perioada, datetime.now(journeys.TZ).date())
    return d0, d1, board


@router.get("/api/stats/platform-changes")
async def platform_changes(request: Request):
    d0, d1, board = read_filters(request)
    store = request.app.state.store

    def run():
        return compute(fetch(store, d0, d1, board), stats.default_min_sample())

    d = await run_in_threadpool(run)
    d["params"] = {"perioada": request.query_params.get("perioada") or "all", "board": board}
    return d
