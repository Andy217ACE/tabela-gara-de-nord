# © 2026 Andy217Ace
"""Administration: token auth + the „Capturi OCR" API (raw CFR captures are private).

Auth: env ADMIN_TOKEN (at least 12 characters; unset/short -> every admin endpoint
answers 503 „Administrare dezactivată."). A request is authenticated by
``Authorization: Bearer <token>`` or by the session cookie set by
``POST /api/admin/login`` (HttpOnly, Secure, SameSite=Strict, 12 h). The cookie
holds an expiry and an HMAC of it keyed by the token, never the token itself;
changing ADMIN_TOKEN invalidates every session. Comparisons use
``hmac.compare_digest``. Wrong credentials are delayed; after FAIL_LIMIT failures a
client IP is refused (429) for a backoff that doubles with each further failure. A
global ceiling only slows failures down, so an attacker cannot lock the admin out. A
success clears the IP's count. The token is never logged.

Optional 2FA (OFF unless env ADMIN_TOTP_SECRET holds a base32 secret): the login then
also needs a TOTP code (RFC 6238, ±1 step, each code accepted once) and a Bearer token is
accepted only from the server itself (loopback). See docs/admin-rotatie-cheie.md.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import re
import shutil
import subprocess
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app.notifier import KeyMismatch, SubscriptionGone
from app import visitors, admin_settings, admin_tools, captures, observations, security_status, totp
from app.ocr import stats as ocr_stats
from app.store import TZ

log = logging.getLogger(__name__)

COOKIE = "tabela_admin"
SESSION_S = 12 * 3600
MIN_TOKEN_LEN = 12  # the operator's chosen key; nginx + FAIL_LIMIT slow guessing
STRICT_TOKEN_LEN = 24  # ADMIN_TOKEN_STRICT=1
MAX_SETTINGS_BODY = 1024
FAIL_LIMIT = 5  # failures per IP before it is refused
BLOCK_BASE_S = 60.0  # refusal after the FAIL_LIMIT-th failure, doubled for each one after
BLOCK_MAX_S = 3600.0
FAIL_FORGET_S = 3600.0  # an IP quiet this long after its block is forgotten
MAX_TRACKED_IPS = 10000
GLOBAL_FAIL_LIMIT = 30  # wrong keys per FAIL_WINDOW_S from ALL clients (IP rotation) ...
GLOBAL_SLOW_DELAY_S = 3.0  # ... above it every failure waits this long (never a block)
FAIL_WINDOW_S = 60.0
FAIL_DELAY_S = 0.5
MAX_LOGIN_BODY = 1024
MAX_TOOLS_BODY = 512  # corpul cererilor din pagina #admin (confirmare + parametri)
DUPES_CONFIRM = "APLICA"
DUPES_RESTORE_CONFIRM = "RESTAUREAZA"
TESSERACT_CACHE_S = 300.0
NO_STORE = {"Cache-Control": "private, no-store", "Pragma": "no-cache"}

_failures: OrderedDict[str, tuple[int, float]] = OrderedDict()  # ip -> (failures, blocked until)
_global_failures: deque = deque(maxlen=GLOBAL_FAIL_LIMIT)
_totp_last = [-1]  # last accepted TOTP counter (replay protection; one worker)
_fail_lock = threading.Lock()
LOOPBACK = ("127.0.0.1", "::1")


def strict_key() -> bool:
    """ADMIN_TOKEN_STRICT=1: cheia trebuie să aibă cel puțin STRICT_TOKEN_LEN caractere. Oprit implicit."""
    return os.environ.get("ADMIN_TOKEN_STRICT", "0").strip().lower() in ("1", "true", "yes", "on")


def admin_token() -> str | None:
    t = os.environ.get("ADMIN_TOKEN", "").strip()
    if totp_on() and totp_key() is None:
        log.error("admin: ADMIN_TOTP_SECRET is not valid base32 (>= 16 chars); administration disabled")
        return None
    return t if len(t) >= (STRICT_TOKEN_LEN if strict_key() else MIN_TOKEN_LEN) else None


def totp_key() -> bytes | None:
    """ADMIN_TOTP_SECRET decoded, or None when 2FA is off (unset) or the value is invalid."""
    v = os.environ.get("ADMIN_TOTP_SECRET", "").strip()
    return totp.decode_secret(v) if v else None


def totp_on() -> bool:
    """2FA is on as soon as the variable is set; an invalid value disables administration
    (admin_token() -> None, fail closed) instead of silently dropping the second factor."""
    return bool(os.environ.get("ADMIN_TOTP_SECRET", "").strip())


def _totp_ok(code, now: float | None = None) -> bool:
    key = totp_key()
    if key is None or not isinstance(code, str):
        return False
    with _fail_lock:
        c = totp.match(key, code.strip(), time.time() if now is None else now, _totp_last[0])
        if c is None:
            return False
        _totp_last[0] = c
        return True


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


def _blocked_for(ip: str, now: float) -> float:
    """Seconds this IP must still wait (0 = may try). Only per-IP: no global value can
    lock the real admin out; the global ceiling only slows failures down (see _fail)."""
    with _fail_lock:
        e = _failures.get(ip)
        if e and now - e[1] > FAIL_FORGET_S:
            del _failures[ip]
            return 0.0
        return max(0.0, e[1] - now) if e and e[0] >= FAIL_LIMIT else 0.0


def _retry_after(wait: float) -> HTTPException:
    return _err(429, "Prea multe încercări. Reîncearcă mai târziu.",
                {"Retry-After": str(max(1, math.ceil(wait)))})


def _check_ip(ip: str) -> None:
    wait = _blocked_for(ip, time.monotonic())
    if wait > 0:
        raise _retry_after(wait)


async def _fail(ip: str) -> HTTPException:
    now = time.monotonic()
    with _fail_lock:
        while _failures:  # drop expired entries (oldest updates first), then enforce the cap
            k, (_, until) = next(iter(_failures.items()))
            if now - until <= FAIL_FORGET_S and len(_failures) < MAX_TRACKED_IPS:
                break
            del _failures[k]
        prev, until = _failures.pop(ip, (0, now))
        count = (0 if now - until > FAIL_FORGET_S else prev) + 1
        block = min(BLOCK_MAX_S, BLOCK_BASE_S * 2 ** (count - FAIL_LIMIT)) if count >= FAIL_LIMIT else 0
        _failures[ip] = (count, now + block)  # re-inserted at the end: most recent last
        busy = len(_global_failures) == GLOBAL_FAIL_LIMIT and _global_failures[0] > now - FAIL_WINDOW_S
        _global_failures.append(now)
    await asyncio.sleep(GLOBAL_SLOW_DELAY_S if busy else FAIL_DELAY_S)
    log.warning("admin: wrong credentials from %s", ip)
    return _err(401, "Autentificare necesară.", {"WWW-Authenticate": "Bearer"})


def _succeeded(ip: str) -> None:
    with _fail_lock:
        _failures.pop(ip, None)


def reset_failures() -> None:
    with _fail_lock:
        _failures.clear()
        _global_failures.clear()
        _totp_last[0] = -1


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
    _check_ip(ip)
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        ok = hmac.compare_digest(auth[7:].strip().encode(), token.encode())
        if ok and (not totp_on() or ip in LOOPBACK):  # with 2FA, Bearer only from the server
            _succeeded(ip)
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
    _check_ip(ip)
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_LOGIN_BODY:
            raise _err(413, "Cererea este prea mare.")
    try:
        body = json.loads(bytes(buf).decode("utf-8"))
        given, code = body.get("token"), body.get("code")
    except (UnicodeDecodeError, ValueError, AttributeError):
        given = code = None
    if totp_on() and not code:
        # asked before the key is checked, so this answer says nothing about the key
        raise _err(401, "totp_required", {"WWW-Authenticate": "Bearer"})
    ok = isinstance(given, str) and hmac.compare_digest(given.encode(), token.encode())
    if not ok or (totp_on() and not _totp_ok(code)):  # code checked only with the right key
        raise await _fail(ip)
    _succeeded(ip)
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
    return _json({"enabled": token is not None, "authenticated": bool(ok), "totp": totp_on()})


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


@guarded.get("/tools/nvme")
async def nvme_tools(request: Request):
    """Discul NVMe (read-only, fără CSRF): citește nvme.json scris de colectorul root."""
    now = datetime.now(TZ)
    out = await run_in_threadpool(admin_tools.nvme_snapshot, request.app.state.settings.db_path,
                                  now.timestamp())
    out["generated_at"] = now.isoformat(timespec="seconds")
    return _json(out)


@guarded.get("/security")
async def security(request: Request):
    """Securitate (read-only, fără CSRF): IP-uri banate de fail2ban și cereri din log-ul nginx,
    din snapshot.json scris de exportatorul root (aplicația nu are privilegii)."""
    now = datetime.now(TZ)
    path = security_status.snapshot_path(request.app.state.settings.db_path)
    if path is None:
        out = {"available": False, "reason": "missing"}
    else:
        out = await run_in_threadpool(security_status.read_snapshot, path, now.timestamp())
    out["now"] = now.isoformat(timespec="seconds")
    return _json(out)


@guarded.get("/visitors")
async def visitors_online(request: Request):
    """Vizitatori online (ultimele 5 min), din memorie; IP mascat, fără boți."""
    return _json({"window_s": visitors.ONLINE_S, "visitors": visitors.online(),
                  "now": time.time()})


_push_test_last = 0.0


@guarded.post("/push-test", dependencies=[Depends(require_csrf)])
async def push_test(request: Request):
    """O notificare de test către un endpoint abonat (verificare Web Push pe telefon)."""
    global _push_test_last
    now = time.monotonic()
    if now - _push_test_last < 10:
        return _json({"result": "rate_limited"}, 429)
    _push_test_last = now
    try:
        endpoint = (await request.json()).get("endpoint")
    except Exception:
        endpoint = None
    app = request.app
    sub = (await run_in_threadpool(app.state.store.get_subscription, endpoint)
           if isinstance(endpoint, str) and endpoint else None)
    if sub is None:
        return _json({"result": "not_subscribed"})
    st = app.state.settings
    if not (st.vapid_private_key and st.vapid_public_key):
        return _json({"result": "not_configured"})
    try:
        await app.state.notifier.send(sub, {"title": "Gara de Nord", "body": "Notificare de test",
                                            "tag": "admin-test", "url": "/"})
    except SubscriptionGone:  # 404/410: same cleanup as the notifier
        await run_in_threadpool(app.state.store.unsubscribe, endpoint)
        return _json({"result": "gone"})
    except KeyMismatch:  # 403: old VAPID key; the page re-subscribes (admin.js) and retries
        return _json({"result": "key_mismatch"})
    except Exception as e:  # RuntimeError("... HTTP <status>")
        m = re.search(r"HTTP (\d+)", str(e))
        return _json({"result": "error", "status": int(m.group(1)) if m else None})
    return _json({"result": "sent"})


def _env_defaults() -> dict[str, int]:
    return {"capture_retention_days": captures.capture_settings().retention_days,
            "capture_min_free_mb": observations.min_free_mb_env()}


router.include_router(guarded)
