# © 2026 Andy217Ace
"""Administration: token auth + the „Capturi OCR" API (raw CFR captures are private).

Auth: env ADMIN_TOKEN (at least 12 characters; unset/short -> every admin endpoint
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
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app import admin_settings, admin_tools, captures, observations
from app.ocr import stats as ocr_stats
from app.store import TZ

log = logging.getLogger(__name__)

COOKIE = "tabela_admin"
SESSION_S = 12 * 3600
MIN_TOKEN_LEN = 12  # the operator's chosen key; nginx + FAIL_LIMIT slow guessing
STRICT_TOKEN_LEN = 24  # ADMIN_TOKEN_STRICT=1
MAX_SETTINGS_BODY = 1024
FAIL_LIMIT = 5
GLOBAL_FAIL_LIMIT = 30  # wrong keys per FAIL_WINDOW_S from ALL clients (IP rotation)
FAIL_WINDOW_S = 60.0
FAIL_DELAY_S = 0.5
MAX_LOGIN_BODY = 1024
MAX_TOOLS_BODY = 512  # corpul cererilor din pagina #admin (confirmare + parametri)
DUPES_CONFIRM = "APLICA"
DUPES_RESTORE_CONFIRM = "RESTAUREAZA"
TESSERACT_CACHE_S = 300.0
NO_STORE = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}

_failures: dict[str, deque] = {}
_global_failures: deque = deque(maxlen=GLOBAL_FAIL_LIMIT * 2)
_fail_lock = threading.Lock()


def strict_key() -> bool:
    """ADMIN_TOKEN_STRICT=1: cheia trebuie să aibă cel puțin STRICT_TOKEN_LEN caractere. Oprit implicit."""
    return os.environ.get("ADMIN_TOKEN_STRICT", "0").strip().lower() in ("1", "true", "yes", "on")


def admin_token() -> str | None:
    t = os.environ.get("ADMIN_TOKEN", "").strip()
    return t if len(t) >= (STRICT_TOKEN_LEN if strict_key() else MIN_TOKEN_LEN) else None


def check_startup() -> None:
    """Refuză pornirea dacă modul strict e activ și cheia prezentă e prea scurtă. Mesajul nu
    conține cheia. Fără cheie deloc, doar administrarea rămâne dezactivată (site-ul merge)."""
    t = os.environ.get("ADMIN_TOKEN", "").strip()
    if strict_key() and t and len(t) < STRICT_TOKEN_LEN:
        raise RuntimeError(
            f"ADMIN_TOKEN_STRICT=1, dar ADMIN_TOKEN are {len(t)} caractere; minimum "
            f"{STRICT_TOKEN_LEN}. Schimbă cheia în /etc/tabela.env (vezi docs/admin-rotatie-cheie.md) "
            "sau scoate ADMIN_TOKEN_STRICT.")


def _err(status: int, msg: str, headers: dict | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail=msg, headers={**NO_STORE, **(headers or {})})


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _limited(ip: str, now: float) -> bool:
    with _fail_lock:
        while _global_failures and _global_failures[0] <= now - FAIL_WINDOW_S:
            _global_failures.popleft()
        if len(_global_failures) >= GLOBAL_FAIL_LIMIT:
            return True
        q = _failures.get(ip)
        if not q:
            return False
        while q and q[0] <= now - FAIL_WINDOW_S:
            q.popleft()
        return len(q) >= FAIL_LIMIT


async def _fail(ip: str) -> HTTPException:
    now = time.monotonic()
    with _fail_lock:
        if len(_failures) > 10000 and ip not in _failures:  # bounded memory: drop the oldest
            del _failures[next(iter(_failures))]
        _failures.setdefault(ip, deque(maxlen=FAIL_LIMIT * 4)).append(now)
        _global_failures.append(now)
    await asyncio.sleep(FAIL_DELAY_S)
    log.warning("admin: wrong credentials from %s", ip)
    return _err(401, "Autentificare necesară.", {"WWW-Authenticate": "Bearer"})


def reset_failures() -> None:
    with _fail_lock:
        _failures.clear()
        _global_failures.clear()


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


def csrf_token(token: str, session_value: str) -> str:
    """CSRF token of one session cookie: an HMAC only the server (and the page that asked
    for it with the cookie) can know; it changes with the session and with ADMIN_TOKEN."""
    return hmac.new(token.encode(), f"csrf:{session_value}".encode(), hashlib.sha256).hexdigest()


async def require_csrf(request: Request) -> None:
    """For state-changing admin calls. A request authenticated by ``Authorization: Bearer``
    carries no ambient credential a foreign page could ride on, so it needs nothing more.
    A cookie session needs ``X-CSRF-Token`` (from ``GET /api/admin/csrf``) and, when the
    browser sends an Origin, the same host as the request (SameSite=Strict is the first
    line; this is the second)."""
    token = admin_token()
    if token is None:
        raise _err(503, "Administrare dezactivată.")
    if request.headers.get("authorization", "")[:7].lower() == "bearer ":
        return
    origin = request.headers.get("origin")
    if origin:
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
        if (urlsplit(origin).hostname or "").lower() != host.strip("[]"):
            raise _err(403, "Origine nepermisă.")
    sess = request.cookies.get(COOKIE) or ""
    given = request.headers.get("x-csrf-token", "")
    if not sess or not hmac.compare_digest(given.encode(), csrf_token(token, sess).encode()):
        raise _err(403, "Token CSRF lipsă sau invalid.")


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


@guarded.get("/csrf")
def csrf(request: Request):
    """CSRF token for the current cookie session (empty for a bearer-token request)."""
    sess = request.cookies.get(COOKIE) or ""
    return _json({"token": csrf_token(admin_token(), sess) if sess else ""})


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
    p = await run_in_threadpool(captures.image_path, store, _cap_settings(request).dir, n)
    d = await run_in_threadpool(captures.capture_detail, store, n)
    if p is None or d is None:
        raise _err(404, "Imaginea nu mai este disponibilă (retenție expirată).")
    data = await run_in_threadpool(p.read_bytes)
    png = await run_in_threadpool(captures.overlay_png, data, d["observations"])
    if png is None:
        raise _err(422, "Imaginea nu poate fi decodată.")
    return Response(png, media_type="image/png", headers=NO_STORE)


@guarded.get("/stats")
async def stats(request: Request):
    store = request.app.state.store
    settings = request.app.state.settings
    out = await run_in_threadpool(captures.capture_system_stats, store, settings.db_path)
    age = await run_in_threadpool(store.last_ok_age, datetime.now(TZ))
    out["live_age_s"] = age
    out["ocr"] = ocr_stats.snapshot()
    out["tesseract"] = await run_in_threadpool(tesseract_status, settings.tesseract_cmd)
    cs = _cap_settings(request)
    days = await run_in_threadpool(admin_settings.effective, store, "capture_retention_days",
                                   cs.retention_days)
    out["capture"] = {"enabled": cs.enabled, "retention_days": days}
    last = out["last_capture_attempt"]
    src_age = None
    if last:
        src_age = (datetime.now(TZ) - datetime.fromisoformat(last)).total_seconds()
    # a new image arrives about once a minute while the CFR source is up
    out["source"] = {"last_image_age_s": src_age,
                     "available": src_age is not None and src_age <= 300,
                     "poller_enabled": bool(settings.poller_enabled)}
    return _json(out)


@guarded.get("/settings")
async def settings_get(request: Request):
    store = request.app.state.store
    return _json(await run_in_threadpool(admin_settings.view, store, _env_defaults()))


@guarded.post("/settings", dependencies=[Depends(require_csrf)])
async def settings_post(request: Request):
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_SETTINGS_BODY:
            raise _err(413, "Cererea este prea mare.")
    try:
        body = json.loads(bytes(buf).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _err(422, "Parametri invalizi.")
    if not isinstance(body, dict) or not body or set(body) - set(admin_settings.SPECS):
        raise _err(422, "Parametri invalizi.")
    try:
        await run_in_threadpool(admin_settings.save, request.app.state.store, body,
                                ip=_ip(request))
    except ValueError:
        raise _err(422, "Parametri invalizi.")
    log.info("admin: settings updated from %s", _ip(request))  # fără valori
    return _json(await run_in_threadpool(admin_settings.view, request.app.state.store,
                                         _env_defaults()))


async def _tools_body(request: Request) -> dict:
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_TOOLS_BODY:
            raise _err(413, "Cererea este prea mare.")
    try:
        body = json.loads(bytes(buf).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _err(422, "Parametri invalizi.")
    if not isinstance(body, dict):
        raise _err(422, "Parametri invalizi.")
    return body


def _min_age(value) -> int:
    if value is None:
        return 60
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1440:
        raise _err(422, "Parametri invalizi.")
    return value


@guarded.get("/tools/dupes")
async def dupes_report(request: Request):
    """Raportul curățării duplicatelor (dry run, read-only)."""
    rep = await run_in_threadpool(admin_tools.dupes_report, request.app.state.settings.db_path)
    return _json({"report": rep, "generated_at": datetime.now(TZ).isoformat(timespec="seconds")})


@guarded.post("/tools/dupes/apply", dependencies=[Depends(require_csrf)])
async def dupes_apply(request: Request):
    body = await _tools_body(request)
    if body.get("confirm") != DUPES_CONFIRM:
        raise _err(422, "Confirmarea lipsește.")
    min_age = _min_age(body.get("min_age_min"))
    log.info("admin: dupes apply from %s", _ip(request))  # fără valori
    try:
        out = await run_in_threadpool(admin_tools.dupes_apply, request.app.state.store, min_age)
    except RuntimeError as e:
        raise _err(500, str(e))
    return _json(out)


@guarded.post("/tools/dupes/restore", dependencies=[Depends(require_csrf)])
async def dupes_restore(request: Request):
    body = await _tools_body(request)
    if body.get("confirm") != DUPES_RESTORE_CONFIRM:
        raise _err(422, "Confirmarea lipsește.")
    batch = body.get("batch")
    if batch is not None and (not isinstance(batch, str) or not 1 <= len(batch) <= 64):
        raise _err(422, "Parametri invalizi.")
    log.info("admin: dupes restore from %s", _ip(request))
    try:
        out = await run_in_threadpool(admin_tools.dupes_restore, request.app.state.store, batch)
    except RuntimeError as e:
        raise _err(500, str(e))
    return _json(out)


@guarded.get("/tools/server")
async def server_tools(request: Request):
    """Starea serverului (read-only, fără CSRF)."""
    out = await run_in_threadpool(admin_tools.server_status, request.app.state.settings.db_path)
    return _json(out)


def _env_defaults() -> dict[str, int]:
    return {"capture_retention_days": captures.capture_settings().retention_days,
            "capture_min_free_mb": observations.min_free_mb_env()}


router.include_router(guarded)
