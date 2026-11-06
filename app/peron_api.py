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
# Cifrele măsurate de backtest-ul walk-forward pe copia bazei live (2026-11-06, 7 zile de
# date): la pragul de afișare (n >= 5, cota >= 80%, nivelul a), predicția a fost corectă în
# 73,2% din cele 97 de cazuri (acoperire 97 din 2482 servicii). Poarta din spec (80%) NU e atinsă.
BACKTEST = {"accuracy_pct": 73.2, "n": 97, "measured_on": "2026-11-06"}
CACHE_TTL_S = 300.0  # istoricul se schimbă încet; evităm scanarea bazei la fiecare 10 s
_BOARDS = (("arrival", "arrivals"), ("departure", "departures"))


def _history(store, today) -> list[pp.Case]:
    since = (today - timedelta(days=pp.WINDOW_DAYS)).isoformat()
    with overview_v2._reader(store) as c:
        return pp.load_cases(c, since=since)


def compute(store, now: datetime) -> dict:
    board = store.current_board(now)
    cases = _history(store, now.date())
    est = {key: pp.estimate_board(cases, b, board.get(key, [])) for b, key in _BOARDS}
    return {"estimates": est, "note": NOTE, "backtest": BACKTEST,
            "threshold": {"min_n": pp.DISPLAY_MIN_N, "min_share_pct": pp.DISPLAY_MIN_SHARE_PCT}}


@router.get("/api/predict/peron")
async def peron(request: Request):
    store = request.app.state.store
    cache = getattr(request.app.state, "peron_cache", None)
    if cache and time.monotonic() - cache[0] < CACHE_TTL_S:
        return cache[1]
    d = await run_in_threadpool(compute, store, datetime.now(TZ))
    request.app.state.peron_cache = (time.monotonic(), d)
    return d
