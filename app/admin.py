# © 2026 Andy217Ace
"""Administration: token auth + the „Capturi OCR" API (raw CFR captures are private).

Auth: env ADMIN_TOKEN (at least 16 characters; unset/short -> every admin endpoint
answers 503 „Administrare dezactivată."). A request is authenticated by
``Authorization: Bearer <token>`` or by the session cookie set by
``POST /api/admin/login`` (HttpOnly, Secure, SameSite=Strict, 12 h). The cookie
holds an expiry and an HMAC of it keyed by the token, never the token itself;
changing ADMIN_TOKEN invalidates every session. Comparisons use
``hmac.compare_digest``. Wrong credentials are delayed and limited to
FAIL_LIMIT per minute per client IP (then 429). The token is never logged.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app import captures
from app.store import TZ

log = logging.getLogger(__name__)

COOKIE = "tabela_admin"
SESSION_S = 12 * 3600
MIN_TOKEN_LEN = 16
FAIL_LIMIT = 5
FAIL_WINDOW_S = 60.0
FAIL_DELAY_S = 0.5
MAX_LOGIN_BODY = 1024
TESSERACT_CACHE_S = 300.0
NO_STORE = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}

_failures: dict[str, deque] = {}
_fail_lock = threading.Lock()


def admin_token() -> str | None:
    t = os.environ.get("ADMIN_TOKEN", "").strip()
    return t if len(t) >= MIN_TOKEN_LEN else None


def _err(status: int, msg: str, headers: dict | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail=msg, headers={**NO_STORE, **(headers or {})})


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _limited(ip: str, now: float) -> bool:
    with _fail_lock:
        q = _failures.get(ip)
        if not q:
            return False
        while q and q[0] <= now - FAIL_WINDOW_S:
            q.popleft()
        return len(q) >= FAIL_LIMIT


async def _fail(ip: str) -> HTTPException:
    now = time.monotonic()
    with _fail_lock:
        if len(_failures) > 10000:  # bounded memory
            _failures.clear()
        _failures.setdefault(ip, deque(maxlen=FAIL_LIMIT * 4)).append(now)
    await asyncio.sleep(FAIL_DELAY_S)
    log.warning("admin: wrong credentials from %s", ip)
    return _err(401, "Autentificare necesară.", {"WWW-Authenticate": "Bearer"})


def reset_failures() -> None:
    with _fail_lock:
        _failures.clear()


def _sign(token: str, exp: int) -> str:
    return hmac.new(token.encode(), f"session:{exp}".encode(), hashlib.sha256).hexdigest()


def make_session(token: str, now: float | None = None) -> str:
    exp = int((now or time.time()) + SESSION_S)
    return f"{exp}.{_sign(token, exp)}"


def check_session(token: str, value: str | None, now: float | None = None) -> bool:
    if not value or "." not in value or len(value) > 200:
        return False
    exp_s, sig = value.split(".", 1)
    if not exp_s.isdigit():
        return False
    exp = int(exp_s)
    if exp < (now or time.time()):
        return False
    return hmac.compare_digest(_sign(token, exp), sig)


async def require_admin(request: Request) -> None:
    token = admin_token()
    if token is None:
        raise _err(503, "Administrare dezactivată.")
    ip = _ip(request)
    if _limited(ip, time.monotonic()):
        raise _err(429, "Prea multe încercări. Reîncearcă peste un minut.", {"Retry-After": "60"})
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        if hmac.compare_digest(auth[7:].strip().encode(), token.encode()):
            return
        raise await _fail(ip)
    if check_session(token, request.cookies.get(COOKIE)):
        return
    raise _err(401, "Autentificare necesară.", {"WWW-Authenticate": "Bearer"})


def _json(data, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers=NO_STORE)


_tess_cache: dict = {"at": None, "value": None}


def tesseract_status(cmd: str) -> dict:
    """`tesseract --version` (first line), cached TESSERACT_CACHE_S."""
    now = time.monotonic()
    if _tess_cache["at"] is not None and now - _tess_cache["at"] < TESSERACT_CACHE_S:
        return _tess_cache["value"]
    try:
        exe = cmd if os.path.isabs(cmd) else (shutil.which(cmd) or cmd)
        p = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
        first = ((p.stdout or p.stderr or "").strip().splitlines() or [""])[0]
        value = {"available": p.returncode == 0, "version": first[:80]}
    except (OSError, subprocess.SubprocessError):
        value = {"available": False, "version": None}
    _tess_cache.update(at=now, value=value)
    return value


def _cap_settings(request: Request) -> captures.CaptureSettings:
    s = getattr(request.app.state, "capture_settings", None)
    return s if s is not None else captures.capture_settings()


def _int_param(value, default: int | None, lo: int, hi: int) -> int | None:
    if value in (None, ""):
        return default
    if not (isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 9):
        raise _err(422, "Parametri invalizi.")
    n = int(value)
    if not lo <= n <= hi:
        raise _err(422, "Parametri invalizi.")
    return n


router = APIRouter(prefix="/api/admin")
guarded = APIRouter(dependencies=[Depends(require_admin)])


@router.post("/login")
async def login(request: Request):
    token = admin_token()
    if token is None:
        raise _err(503, "Administrare dezactivată.")
    ip = _ip(request)
    if _limited(ip, time.monotonic()):
        raise _err(429, "Prea multe încercări. Reîncearcă peste un minut.", {"Retry-After": "60"})
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_LOGIN_BODY:
            raise _err(413, "Cererea este prea mare.")
    try:
        given = json.loads(bytes(buf).decode("utf-8")).get("token")
    except (UnicodeDecodeError, ValueError, AttributeError):
        given = None
    if not isinstance(given, str) or not hmac.compare_digest(given.encode(), token.encode()):
        raise await _fail(ip)
    resp = _json({"ok": True})
    resp.set_cookie(COOKIE, make_session(token), max_age=SESSION_S, httponly=True,
                    secure=True, samesite="strict", path="/api/admin")
    return resp


@router.post("/logout")
async def logout():
    resp = _json({"ok": True})
    resp.delete_cookie(COOKIE, path="/api/admin", httponly=True, secure=True,
                       samesite="strict")
    return resp


@router.get("/session")
def session(request: Request):
    """Login state for the UI, always 200 (no failed request on a normal visit).
    Only the cookie is checked here; it never counts as a failed attempt."""
    token = admin_token()
    ok = token is not None and check_session(token, request.cookies.get(COOKIE))
    return _json({"enabled": token is not None, "authenticated": bool(ok)})


@guarded.get("/captures")
def captures_list(request: Request):
    q = request.query_params
    limit = _int_param(q.get("limit"), 50, 1, captures.LIST_MAX)
    before = _int_param(q.get("before"), None, 1, 10**12)
    items = captures.list_captures(request.app.state.store, limit, before)
    return _json({"captures": items,
                  "next_before": items[-1]["id"] if len(items) == limit else None})


def _cid(value: str) -> int:
    return _int_param(value, None, 1, 10**12)


@guarded.get("/captures/{cid}")
def capture_one(request: Request, cid: str):
    d = captures.capture_detail(request.app.state.store, _cid(cid))
    if d is None:
        raise _err(404, "Captura nu există.")
    return _json(d)


@guarded.get("/captures/{cid}/image")
def capture_image(request: Request, cid: str):
    p = captures.image_path(request.app.state.store, _cap_settings(request).dir, _cid(cid))
    if p is None:
        raise _err(404, "Imaginea nu mai este disponibilă (retenție expirată).")
    return Response(p.read_bytes(), media_type="image/jpeg", headers=NO_STORE)


@guarded.get("/captures/{cid}/overlay.png")
async def capture_overlay(request: Request, cid: str):
    store = request.app.state.store
    n = _cid(cid)
    p = captures.image_path(store, _cap_settings(request).dir, n)
    d = captures.capture_detail(store, n)
    if p is None or d is None:
        raise _err(404, "Imaginea nu mai este disponibilă (retenție expirată).")
    png = await run_in_threadpool(captures.overlay_png, p.read_bytes(), d["observations"])
    if png is None:
        raise _err(422, "Imaginea nu poate fi decodată.")
    return Response(png, media_type="image/png", headers=NO_STORE)


@guarded.get("/stats")
async def stats(request: Request):
    store = request.app.state.store
    settings = request.app.state.settings
    out = await run_in_threadpool(captures.capture_system_stats, store, settings.db_path)
    age = store.last_ok_age(datetime.now(TZ))
    out["live_age_s"] = age
    out["tesseract"] = await run_in_threadpool(tesseract_status, settings.tesseract_cmd)
    cs = _cap_settings(request)
    out["capture"] = {"enabled": cs.enabled, "retention_days": cs.retention_days}
    last = out["last_capture_attempt"]
    src_age = None
    if last:
        src_age = (datetime.now(TZ) - datetime.fromisoformat(last)).total_seconds()
    # a new image arrives about once a minute while the CFR source is up
    out["source"] = {"last_image_age_s": src_age,
                     "available": src_age is not None and src_age <= 300,
                     "poller_enabled": bool(settings.poller_enabled)}
    return _json(out)


router.include_router(guarded)
