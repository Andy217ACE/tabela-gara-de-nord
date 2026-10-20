# © 2026 Andy217Ace
"""HTTP API and application wiring.

`create_app` builds the FastAPI app. Its lifespan opens the Store, builds the
Notifier and (unless `start_poller=False`) runs the poller under a supervisor
that logs crashes and restarts it with backoff, so the web server stays up.
Each reading is ingested off the event loop; `notifier.handle` is scheduled as
a separate background task so a slow push service never stalls polling.

All validation errors are 422 with a Romanian `detail` message; JSON bodies
over MAX_BODY bytes are 413.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app import poller
from app.config import Settings, get_settings
from app.endpoints import check_push_endpoint
from app.notifier import Notifier, make_webpush_sender
from app.store import HISTORY_MAX, TZ, Store

log = logging.getLogger(__name__)

MAX_BODY = 4096
STALE_S = 180.0
MAX_STATION_LEN = 64
POLLER_STOP_TIMEOUT = 10.0
POLLER_MAX_BACKOFF = 300.0
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
ATTRIBUTION = {"source": "CFR", "url": "https://cfr.ro", "author": "Andy217Ace"}
BOARDS = ("arrival", "departure")

_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self'",
    "manifest-src 'self'",
    "worker-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": CSP,
}


def _today() -> date:
    """Today in Europe/Bucharest (patched in tests)."""
    return datetime.now(TZ).date()


def _bad(msg: str, status: int = 422) -> HTTPException:
    return HTTPException(status_code=status, detail=msg)


# -- validation helpers -----------------------------------------------------

def _parse_date(value: str | None, *, default_today: bool = True) -> date:
    if value is None or value == "":
        if default_today:
            return _today()
        raise _bad("Data lipsește (format AAAA-LL-ZZ).")
    if not isinstance(value, str) or not _DATE.match(value):
        raise _bad("Dată invalidă (format AAAA-LL-ZZ).")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _bad("Dată invalidă (format AAAA-LL-ZZ).") from None


def _parse_train(value) -> int:
    if isinstance(value, bool):
        raise _bad("Număr de tren invalid.")
    if isinstance(value, int):
        n = value
    elif isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= 6:
        n = int(value)
    else:
        raise _bad("Număr de tren invalid.")
    if not 0 < n < 1_000_000:
        raise _bad("Număr de tren invalid.")
    return n


def _parse_hhmm(value: str | None, name: str) -> str | None:
    if value is None or value == "":
        return None
    if not _HHMM.match(value):
        raise _bad(f"Ora „{name}” este invalidă (format HH:MM).")
    return value


def _check_push_endpoint(endpoint) -> str:
    """Allowlisted push-service URL (see app.endpoints); 422 otherwise."""
    try:
        check_push_endpoint(endpoint)
    except ValueError as e:
        raise _bad(str(e)) from None
    return endpoint


async def _json_body(request: Request) -> dict:
    """Read a JSON object body of at most MAX_BODY bytes (413 above, 422 if invalid)."""
    too_big = _bad("Cererea este prea mare (maxim 4 KB).", 413)
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > MAX_BODY:
                raise too_big
        except ValueError:
            raise _bad("Antet Content-Length invalid.") from None
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_BODY:
            raise too_big
    try:
        data = json.loads(bytes(buf).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _bad("Corpul cererii nu este JSON valid.") from None
    if not isinstance(data, dict):
        raise _bad("Corpul cererii trebuie să fie un obiect JSON.")
    return data


# -- poller wiring ----------------------------------------------------------

async def _supervise_poller(settings: Settings, on_rows, client: httpx.AsyncClient,
                            stop: asyncio.Event) -> None:
    """Run the poller; on crash (or unexpected return) log and restart with backoff."""
    first = max(0.0, settings.poller_restart_backoff)
    delay = first
    while not stop.is_set():
        try:
            await poller.run_poller(settings, on_rows, client, stop,
                                    last_image_path=settings.last_image_path)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("poller crashed; restarting in %.2fs", delay)
        else:
            if stop.is_set():
                break
            log.error("poller exited unexpectedly; restarting in %.2fs", delay)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
        delay = min(max(delay * 2, first), POLLER_MAX_BACKOFF)


def _make_sender(settings: Settings):
    if settings.vapid_private_key and settings.vapid_public_key:
        return make_webpush_sender(settings)
    warned = False

    async def noop(sub, data) -> None:
        nonlocal warned
        if not warned:
            warned = True
            log.warning("VAPID keys not configured; push notifications are disabled")

    return noop


# -- app --------------------------------------------------------------------

def create_app(settings: Settings | None = None, start_poller: bool = True) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(settings.db_path)
        store.migrate()
        notifier = Notifier(store, _make_sender(settings))
        notify_tasks: set[asyncio.Task] = set()

        def _notify_done(t: asyncio.Task) -> None:
            notify_tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                log.error("notifier failed", exc_info=t.exception())

        async def on_rows(rows, ts: float) -> None:
            when = datetime.fromtimestamp(ts, TZ)
            events = await asyncio.to_thread(store.ingest, rows, when, "")
            t = asyncio.create_task(notifier.handle(events, when.date()))
            notify_tasks.add(t)
            t.add_done_callback(_notify_done)

        app.state.settings = settings
        app.state.store = store
        app.state.notifier = notifier
        app.state.on_rows = on_rows

        client = stop = poller_task = None
        if start_poller and settings.poller_enabled:
            client = httpx.AsyncClient()
            stop = asyncio.Event()
            poller_task = asyncio.create_task(_supervise_poller(settings, on_rows, client, stop))
        try:
            yield
        finally:
            if poller_task is not None:
                stop.set()
                try:
                    await asyncio.wait_for(poller_task, POLLER_STOP_TIMEOUT)
                except asyncio.TimeoutError:
                    log.warning("poller did not stop in %.0fs; cancelled", POLLER_STOP_TIMEOUT)
                except Exception:
                    log.exception("poller task failed during shutdown")
            for t in list(notify_tasks):
                t.cancel()
            if notify_tasks:
                await asyncio.gather(*notify_tasks, return_exceptions=True)
            if client is not None:
                await client.aclose()
            store.close()

    app = FastAPI(title="Tabela Gara de Nord", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if not request.url.path.startswith("/api/"):
            # static frontend: always revalidate (ETag) so a deploy is picked up at once
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": "Parametri invalizi."})

    def store_of(request: Request) -> Store:
        return request.app.state.store

    # -- reads --------------------------------------------------------------

    @app.get("/api/board")
    def board(request: Request):
        store = store_of(request)
        out = store.current_board()
        age = store.last_ok_age(datetime.now(TZ))
        out["age_s"] = age
        out["stale"] = age is None or age > STALE_S
        out["attribution"] = ATTRIBUTION
        return out

    @app.get("/api/health")
    def health(request: Request):
        age = store_of(request).last_ok_age(datetime.now(TZ))
        return {"ok": age is not None and age <= STALE_S, "age_s": age}

    @app.get("/api/history")
    def history(request: Request, response: Response):
        q = request.query_params
        day = _parse_date(q.get("date"))
        train = _parse_train(q["train"]) if q.get("train") else None
        board_ = q.get("board") or None
        if board_ is not None and board_ not in BOARDS:
            raise _bad("Panou invalid (arrival sau departure).")
        station = q.get("station") or None
        if station is not None and len(station) > MAX_STATION_LEN:
            raise _bad("Numele stației este prea lung.")
        time_from = _parse_hhmm(q.get("from"), "de la")
        time_to = _parse_hhmm(q.get("to"), "până la")
        if time_from and time_to and time_from > time_to:
            raise _bad("Ora „de la” este după ora „până la”.")
        services = store_of(request).history(day, train=train, station=station, board=board_,
                                             time_from=time_from, time_to=time_to)
        if len(services) > HISTORY_MAX:  # store fetched one extra row to detect truncation
            services = services[:HISTORY_MAX]
            response.headers["X-Truncated"] = "1"
        return {"date": day.isoformat(), "services": services}

    @app.get("/api/train/{no}")
    def train_events(request: Request, no: str):
        n = _parse_train(no)
        day = _parse_date(request.query_params.get("date"))
        return {"train": n, "date": day.isoformat(),
                "events": store_of(request).train_events(n, day)}

    @app.get("/api/follows")
    def follows(request: Request):
        ep = _check_push_endpoint(request.query_params.get("endpoint"))
        return {"follows": store_of(request).list_follows(ep)}

    @app.get("/api/push/key")
    def push_key(request: Request):
        key = request.app.state.settings.vapid_public_key
        if not key:
            raise _bad("Notificările push nu sunt configurate.", 404)
        return {"key": key}

    # -- writes -------------------------------------------------------------

    @app.post("/api/push/subscribe")
    async def subscribe(request: Request):
        body = await _json_body(request)
        ep = _check_push_endpoint(body.get("endpoint"))
        keys = body.get("keys")
        if not isinstance(keys, dict):
            raise _bad("Cheile abonării lipsesc.")
        p256dh, auth = keys.get("p256dh"), keys.get("auth")
        try:
            await run_in_threadpool(store_of(request).subscribe, ep, p256dh, auth)
        except ValueError:
            raise _bad("Abonare invalidă.") from None
        return {"ok": True}

    @app.post("/api/push/unsubscribe")
    async def unsubscribe(request: Request):
        body = await _json_body(request)
        ep = _check_push_endpoint(body.get("endpoint"))
        await run_in_threadpool(store_of(request).unsubscribe, ep)
        return {"ok": True}

    async def _follow_args(request: Request) -> tuple[str, int, date]:
        body = await _json_body(request)
        ep = _check_push_endpoint(body.get("endpoint"))
        n = _parse_train(body.get("train"))
        d = body.get("date")
        if not isinstance(d, str):
            raise _bad("Data lipsește (format AAAA-LL-ZZ).")
        return ep, n, _parse_date(d, default_today=False)

    @app.post("/api/follow")
    async def follow(request: Request):
        ep, n, day = await _follow_args(request)
        today = _today()
        if day < today:
            raise _bad("Data trebuie să fie azi sau mai târziu.")
        try:
            await run_in_threadpool(lambda: store_of(request).follow(ep, n, day, today=today))
        except ValueError as e:
            msg = str(e)
            if msg == "abonare necunoscută":
                raise _bad("Abonare necunoscută; activează întâi notificările.") from None
            raise _bad(msg[:1].upper() + msg[1:] + "." if msg else "Cerere invalidă.") from None
        return {"ok": True}

    @app.delete("/api/follow")
    async def unfollow(request: Request):
        ep, n, day = await _follow_args(request)
        await run_in_threadpool(store_of(request).unfollow, ep, n, day)
        return {"ok": True}

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "DELETE"],
                   include_in_schema=False)
    def api_not_found(request: Request, rest: str):
        # A full match here beats a method mismatch on a real route: restore 405.
        path = request.url.path
        allowed = sorted({m for r in request.app.router.routes
                          if isinstance(r, APIRoute) and r.name != "api_not_found"
                          and r.path_regex.match(path) for m in (r.methods or ())})
        if allowed:
            return JSONResponse({"detail": "Metodă nepermisă."}, status_code=405,
                                headers={"Allow": ", ".join(allowed)})
        raise _bad("Nu există.", 404)

    # Static frontend last, so /api/* routes win. No disk writes here.
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    else:
        log.warning("web directory %s missing; static frontend not served", WEB_DIR)
    return app
