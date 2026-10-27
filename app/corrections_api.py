# © 2026 Andy217Ace
"""Admin API of the manual corrections (``/api/admin/corrections*``). Everything here sits
behind ``admin.require_admin``; state-changing calls also need ``admin.require_csrf``.
Nothing of it is reachable without the admin key, and no public endpoint reads these
tables."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool

from app import admin, corrections
from app.corrections import CorrectionError

MAX_BODY = 8192

router = APIRouter(prefix="/api/admin/corrections", dependencies=[Depends(admin.require_admin)])
csrf = [Depends(admin.require_csrf)]


async def _body(request: Request) -> dict:
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_BODY:
            raise admin._err(413, "Cererea este prea mare.")
    if not buf:
        return {}
    try:
        data = json.loads(bytes(buf).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise admin._err(422, "Cerere invalidă.") from None
    if not isinstance(data, dict):
        raise admin._err(422, "Cerere invalidă.")
    return data


def _fail(e: CorrectionError):
    return admin._err(e.status, str(e))


def _rid(value: str) -> int:
    return admin._int_param(value, None, 1, 10**9)


def _ip(request: Request) -> str:
    return admin._ip(request)


async def _run(fn, *a, **kw):
    try:
        return await run_in_threadpool(fn, *a, **kw)
    except CorrectionError as e:
        raise _fail(e) from None


def _store(request: Request):
    return request.app.state.store


@router.get("")
async def list_(request: Request):
    status = request.query_params.get("status", "active")
    if status not in ("active", "deleted", "all"):
        raise admin._err(422, "Parametri invalizi.")
    return admin._json({"corrections": await _run(corrections.list_rules, _store(request), status)})


@router.get("/audit")
async def audit(request: Request):
    limit = admin._int_param(request.query_params.get("limit"), 100, 1, 500)
    return admin._json({"audit": await _run(corrections.audit_log, _store(request), limit)})


@router.post("/preview", dependencies=csrf)
async def preview_new(request: Request):
    """Dry run of a rule that does not exist yet (validates it, writes nothing)."""
    rule = await _run(corrections.validate_rule, await _body(request))
    return admin._json({"rule": rule, "preview": await _run(corrections.preview, _store(request),
                                                           rule)})


@router.post("", dependencies=csrf)
async def create(request: Request):
    rule = await _run(corrections.validate_rule, await _body(request))
    made = await _run(corrections.create_rule, _store(request), rule, ip=_ip(request))
    return admin._json({"correction": made}, 201)


def _existing(store, rid: int) -> dict:
    with store._lock:
        r = corrections.get_rule(store._conn, rid)
    if r is None:
        raise CorrectionError("Regula nu există.", 404)
    return r


@router.post("/{rid}/preview", dependencies=csrf)
async def preview_rule(request: Request, rid: str):
    store = _store(request)
    rule = await _run(_existing, store, _rid(rid))
    return admin._json({"preview": await _run(corrections.preview, store, rule)})


@router.post("/{rid}/apply", dependencies=csrf)
async def apply_rule(request: Request, rid: str):
    data = await _body(request)
    h = data.get("plan_hash")
    if not isinstance(h, str) or not (8 <= len(h) <= 64):
        raise admin._err(422, "Aplicarea cere previzualizarea (plan_hash).")
    out = await _run(corrections.apply, _store(request), _rid(rid), h, ip=_ip(request))
    return admin._json(out)


@router.post("/batches/{batch}/restore", dependencies=csrf)
async def restore_batch(request: Request, batch: str):
    if not (1 <= len(batch) <= 60) or not all(c.isalnum() or c in "-." for c in batch):
        raise admin._err(422, "Parametri invalizi.")
    return admin._json(await _run(corrections.restore, _store(request), batch,
                                  ip=_ip(request)))


@router.delete("/{rid}", dependencies=csrf)
async def delete(request: Request, rid: str):
    restore = request.query_params.get("restore") in ("1", "true")
    return admin._json(await _run(corrections.soft_delete, _store(request), _rid(rid),
                                  restore_batches=restore, ip=_ip(request)))
