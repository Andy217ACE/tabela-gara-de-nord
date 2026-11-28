# © 2026 Andy217Ace
"""GET /api/predict/peron: estimări de peron pentru trenurile de pe panou care NU au peron
anunțat. Read-only (conexiune ``mode=ro``), nicio scriere. Estimare din istoricul observat,
nu informație oficială CFR. Pragul de afișare e în ``app.peron_predict`` (din backtest)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app import peron_predict as pp
from app import stats_overview as overview_v2
from app.store import TZ

router = APIRouter()

NOTE = "Estimare din istoricul observat, nu informație oficială CFR."
# Backtest pe 10 zile (18-27.11.2026), estimările reconstituite cu regula „linie ocupată
# ±10 min": 178 corecte din 206 (86,4%); fără regulă: 181 din 218 (83,0%).
BACKTEST = {"accuracy_pct": 86.4, "n": 206, "measured_on": "2026-11-28"}
CACHE_TTL_S = 300.0  # doar istoricul; ocuparea liniilor se schimbă la câteva secunde
_BOARDS = (("arrival", "arrivals"), ("departure", "departures"))


def _history(store, today) -> list[pp.Case]:
    since = (today - timedelta(days=pp.WINDOW_DAYS)).isoformat()
    with overview_v2._reader(store) as c:
        return pp.load_cases(c, since=since)


def _occupied(board: dict) -> list[tuple[int, str]]:
    out = []
    for _, key in _BOARDS:
        for t in board.get(key, []):
            try:
                if t.get("platform") not in (None, "") and t.get("sched_time"):
                    out.append((int(t["platform"]), t["sched_time"]))
            except (TypeError, ValueError):
                pass
    return out


def compute(store, now: datetime, cases: list[pp.Case] | None = None) -> dict:
    board = store.current_board(now)
    if cases is None:
        cases = _history(store, now.date())
    occ = _occupied(board)
    est = {key: pp.estimate_board(cases, b, board.get(key, []), occ) for b, key in _BOARDS}
    return {"estimates": est, "note": NOTE, "backtest": BACKTEST,
            "threshold": {"min_n": pp.DISPLAY_MIN_N, "min_share_pct": pp.DISPLAY_MIN_SHARE_PCT}}


@router.get("/api/predict/peron")
async def peron(request: Request):
    store = request.app.state.store
    now = datetime.now(TZ)
    cache = getattr(request.app.state, "peron_cache", None)  # (monotonic, zi, cases)
    if cache and cache[1] == now.date() and time.monotonic() - cache[0] < CACHE_TTL_S:
        cases = cache[2]
    else:
        cases = await run_in_threadpool(_history, store, now.date())
        request.app.state.peron_cache = (time.monotonic(), now.date(), cases)
    return await run_in_threadpool(compute, store, now, cases)
