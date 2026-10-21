# © 2026 Andy217Ace
"""Public, read-only train catalog: GET /api/trains and /api/trains/{no}.

No images, no raw OCR data. `journeys` (services) and `observations` (OCR
readings) are always reported as separate numbers.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app import observations

router = APIRouter(prefix="/api/trains")
MAX_QUERY = 40


def _bad(msg: str) -> HTTPException:
    return HTTPException(status_code=422, detail=msg)


@router.get("")
async def trains(request: Request):
    q = request.query_params
    query = (q.get("query") or "").strip()
    if len(query) > MAX_QUERY:
        raise _bad("Căutarea este prea lungă.")
    raw = q.get("limit") or "50"
    if not (raw.isascii() and raw.isdigit() and 1 <= int(raw) <= observations.TRAINS_MAX):
        raise _bad(f"Limită invalidă (1–{observations.TRAINS_MAX}).")
    items = await run_in_threadpool(observations.list_trains, request.app.state.store,
                                    query or None, int(raw))
    return {"trains": items, "n": len(items)}


@router.get("/{no}")
async def train(request: Request, no: str):
    if not (no.isascii() and no.isdigit() and len(no) <= 6 and 0 < int(no) < 1_000_000):
        raise _bad("Număr de tren invalid.")
    d = await run_in_threadpool(observations.train_detail, request.app.state.store, int(no))
    if d is None:
        raise HTTPException(status_code=404, detail="Trenul nu a fost observat.")
    return d
