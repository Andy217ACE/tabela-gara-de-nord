# © 2026 Andy217Ace
"""Admin API of the alternative-OCR journal (``/api/admin/ocr-alt*``, page #ocr2). Admin only;
the verdict POST also needs ``admin.require_csrf``. Nothing of it is public."""
from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from app import admin
from app.ocr import alt_journal, alt_reader
from app.ocr import stats as ocr_stats

router = APIRouter(prefix="/api/admin/ocr-alt", dependencies=[Depends(admin.require_admin)])


def _state() -> dict:
    path = os.environ.get("OCR_ALT_MODEL", "")
    try:
        loaded = alt_reader.get_model() is not None
    except Exception:
        loaded = False
    return {"enabled": alt_reader.enabled(), "shadow": alt_reader.shadow(),
            "model_path": path or None, "model_loaded": loaded,
            "since_start": dict(ocr_stats.snapshot()["alt"])}


def _view(e: dict) -> dict:
    return e | {"crops": {c: f"/api/admin/ocr-alt/crop/{e['id']}/{c}" for c in e["cols"]}}


@router.get("")
async def overview(limit: str = "50", before: str | None = None, only: str = "all"):
    lim = admin._int_param(limit, 50, 1, 200)
    if only not in ("all", "unverified") or (before and not alt_journal.ID_RE.match(before)):
        raise admin._err(422, "Parametri invalizi.")
    events, nxt = await run_in_threadpool(alt_journal.list_events, lim, before, only)
    return admin._json({"state": _state(), "totals": await run_in_threadpool(alt_journal.totals),
                        "events": [_view(e) for e in events], "next": nxt})


@router.get("/crop/{eid}/{col}")
async def crop(eid: str, col: str):
    p = alt_journal.crop_path(eid, col)
    if p is None:
        raise admin._err(404, "Decupaj inexistent.")
    return FileResponse(p, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400"})


@router.post("/{eid}/verdict", dependencies=[Depends(admin.require_csrf)])
async def verdict(eid: str, request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw.decode("utf-8")) if len(raw) <= 1024 else None
    except (UnicodeDecodeError, ValueError):
        body = None
    if (not isinstance(body, dict) or set(body) != {"verdict"}
            or body["verdict"] not in (*alt_journal.VERDICTS, None)):
        raise admin._err(422, "Verdict invalid.")
    if not alt_journal.ID_RE.match(eid) or not await run_in_threadpool(
            alt_journal.set_verdict, eid, body["verdict"]):
        raise admin._err(404, "Eveniment necunoscut.")
    return admin._json({"ok": True, "verdict": body["verdict"], "totals": alt_journal.totals()})
