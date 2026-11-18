# © 2026 Andy217Ace
"""Val 5b: payload-ul estimării întârzierii finale pentru un tren (GET /api/trains/{no}/prediction).

Strat subțire peste `app.predict` (ierarhie, praguri, poartă). Estimare, nu citire: etichetă
„Estimare”, N, interval P25–P75. Nu scrie nimic. Dacă poarta nu trece, nu are cifre, doar motivul.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from app import predict as pr

LABEL = "Estimare"
NOTE = ("Estimare din istoricul observat (mediană, interval P25–P75, N afișat), nu întârziere "
        "citită și nu promisiune. La plecări, întârzierea citită e cea anunțată înainte de plecare.")


def estimate(journeys: list[pr.Journey], train_no: int, today: date, *, published: bool,
             reason: str = "") -> dict:
    """Estimările pentru fiecare (bord, stație) în care trenul apare în istoric, pentru ziua
    `today`. Fără poartă trecută sau sub prag: listă goală."""
    out = {"label": LABEL, "note": NOTE, "train_no": train_no, "published": published,
           "reason": reason, "estimates": []}
    if not published:
        return out
    mine = [j for j in journeys if j.train_no == train_no]
    if not mine:
        return out
    pool = pr.build_pool([j for j in journeys if j.service_date < today.isoformat()])
    latest: dict[tuple, pr.Journey] = {}
    for j in sorted(mine, key=lambda x: (x.service_date, x.service_id)):
        latest[(j.board, j.station)] = j
    for (board, station), j in sorted(latest.items()):
        target = pr.Journey(0, train_no, board, station, today.isoformat(), j.sched_time, 0, 0)
        p = pr.predict_final(pool, target)
        if p is not None:
            out["estimates"].append({"board": board, "station": station, "sched_time": j.sched_time,
                                     "delay_min": p.delay_min, "low": p.low, "high": p.high,
                                     "n": p.n, "basis": p.basis})
    return out


def compute(conn: sqlite3.Connection, train_no: int, today: date) -> dict:
    """Citește călătoriile (SELECT), rulează poarta pe backtest și întoarce payload-ul."""
    js = pr.load_journeys(conn)
    g = pr.gate(pr.report(pr.walk_forward(js), js))
    return estimate(js, train_no, today, published=g.published, reason=g.reason)
