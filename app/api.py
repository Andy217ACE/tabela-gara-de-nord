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
import mimetypes
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import unquote

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.concurrency import run_in_threadpool

from app import (admin, captures, corrections, corrections_api, export, history_all, observations,
                 peron_api, poller, seasons, stats, stats_api, stats_quality_daily, system_api,
                 telegram, trains_api, weather)
from app import stats_dwell, stats_platform  # noqa: E402  (secțiuni publice noi #statistici)
from app import stats_read_errors  # noqa: E402  (erori de citire, public #statistici)
from app import ocr_alt_api  # noqa: E402  (#ocr2, admin)
from app import infofer_api  # noqa: E402  (#infofer, admin, spike intern)
from app import line_prediction, stats_overview  # noqa: E402  (Val 5: sezoane CSV, estimare per tren)
from app.config import Settings, get_settings
from app import perf, seo, stations, visitors
from app.ocr import stats as ocr_stats
from app.version import __version__, changelog
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

# self-hosted web fonts (web/fonts/*.woff2): not in every OS mime table (Windows, minimal
# images); with "nosniff" a wrong type could block them
mimetypes.add_type("font/woff2", ".woff2")

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "font-src 'self'",
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


DEFAULT_DELAY_THRESHOLDS = (5, 15, 30)
REFRESH_S = 10  # web/app.js polls /api/board this often


def panel_config() -> dict:
    """Read-only UI settings for the „Panou" view (GET /api/config).

    Delay colour thresholds in minutes come from env `DELAY_THRESHOLDS="low,mid,high"`
    (strictly increasing positive ints); anything else falls back to the defaults.
    """
    low, mid, high = DEFAULT_DELAY_THRESHOLDS
    raw = os.environ.get("DELAY_THRESHOLDS", "")
    parts = [p.strip() for p in raw.split(",")] if raw else []
    if len(parts) == 3 and all(p.isascii() and p.isdigit() for p in parts):
        a, b, c = (int(p) for p in parts)
        if 0 < a < b < c <= 1440:
            low, mid, high = a, b, c
    return {"delay_thresholds": {"low": low, "mid": mid, "high": high},
            "stale_after_s": int(STALE_S), "refresh_s": REFRESH_S}


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


# Proof of ownership: the subscription's keys.auth, which only the browser and this server know
# (the endpoint URL is also seen by the push service). Unknown endpoint and wrong proof look alike.
_NOT_OWNER = "Abonare necunoscută sau dovadă de abonare invalidă."


async def _check_owner(store: Store, endpoint: str, auth) -> None:
    if not await run_in_threadpool(store.owns, endpoint, auth):
        raise _bad(_NOT_OWNER, 403)


def _sub_keys(body: dict) -> tuple:
    keys = body.get("keys")
    if not isinstance(keys, dict):
        raise _bad("Cheile abonării lipsesc.")
    return keys.get("p256dh"), keys.get("auth")


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
                            stop: asyncio.Event, known_stations=None, on_capture=None) -> None:
    """Run the poller; on crash (or unexpected return) log and restart with backoff."""
    first = max(0.0, settings.poller_restart_backoff)
    delay = first
    while not stop.is_set():
        try:
            await poller.run_poller(settings, on_rows, client, stop,
                                    last_image_path=settings.last_image_path,
                                    known_stations=known_stations, on_capture=on_capture,
                                    rejected_dir=getattr(settings, "rejected_dir", None))
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

_HEAD_SUBS = (  # (key, exact Romanian head fragment with {} where the value goes)
    ("meta.title", "<title>{}</title>"),
    ("meta.description", '<meta name="description" content="{}">'),
    ("meta.ogTitle", '<meta property="og:title" content="{}">'),
    ("meta.ogDescription", '<meta property="og:description" content="{}">'),
    ("meta.ogLocale", '<meta property="og:locale" content="{}">'),
    ("meta.ogTitle", '<meta name="twitter:title" content="{}">'),
    ("meta.twitterDescription", '<meta name="twitter:description" content="{}">'),
)


def _index_en(html: str) -> str:
    """English head for index.html: plain replacement of the Romanian fragments."""
    import html as _html
    try:
        ro = json.loads((WEB_DIR / "i18n" / "ro.json").read_text(encoding="utf-8"))
        en = json.loads((WEB_DIR / "i18n" / "en.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return html
    out = html.replace('<html lang="ro">', '<html lang="en">', 1)
    for key, frag in _HEAD_SUBS:
        if key in ro and key in en:
            out = out.replace(frag.format(ro[key]),
                              frag.format(_html.escape(en[key], quote=True)), 1)
    return out


def create_app(settings: Settings | None = None, start_poller: bool = True) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(settings.db_path)
        store.migrate()
        tg_cfg = telegram.config_from_env()
        tg_channel = telegram.make_telegram_sender(tg_cfg) if tg_cfg else None
        notifier = Notifier(store, _make_sender(settings), telegram=tg_channel)
        notify_tasks: set[asyncio.Task] = set()

        def _notify_done(t: asyncio.Task) -> None:
            notify_tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                log.error("notifier failed", exc_info=t.exception())

        async def on_rows(rows, ts: float) -> dict[str, str]:
            """Ingest one reading; returns {panel: reason} for the rejected panels."""
            when = datetime.fromtimestamp(ts, TZ)

            def _ingest():
                fixed = corrections.correct_rows(store, rows, when)  # manual rules (v9)
                return (store.ingest(fixed, when, ""), dict(store.last_rejected),
                        set(store.last_ghost_numbers), fixed)

            events, rejected, ghosts, rows = await asyncio.to_thread(_ingest)
            try:  # public catalog follows the board even when captures are off/failing
                await asyncio.to_thread(observations.refresh_catalog, store, rows, ghosts)
            except Exception:
                log.exception("trains catalog refresh failed (board unaffected)")
            t = asyncio.create_task(notifier.handle(events, when.date()))
            notify_tasks.add(t)
            t.add_done_callback(_notify_done)
            return rejected

        app.state.settings = settings
        app.state.store = store
        app.state.notifier = notifier
        app.state.on_rows = on_rows

        cap_settings = captures.capture_settings()  # Etapa B: OCR captures + retention
        app.state.capture_settings = cap_settings
        on_capture = captures.make_on_capture(store, cap_settings) if cap_settings.enabled else None
        app.state.on_capture = on_capture
        cap_stop = asyncio.Event()
        retention_task = (asyncio.create_task(captures.retention_loop(store, cap_settings, cap_stop))
                          if start_poller else None)

        client = stop = poller_task = None
        if start_poller and settings.poller_enabled:
            client = httpx.AsyncClient()
            stop = asyncio.Event()
            poller_task = asyncio.create_task(_supervise_poller(settings, on_rows, client, stop,
                                                               store.known_stations, on_capture))
        # weather: own supervised task, independent of the poller (never affects health.ok)
        wx = weather.start(store, settings.weather) if start_poller and settings.weather else None
        try:
            yield
        finally:
            if wx is not None:
                await wx.stop()
            cap_stop.set()
            if retention_task is not None:
                await asyncio.gather(retention_task, return_exceptions=True)
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
        t0 = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")  # set by the router on a match: a template, not the raw path
        if response.status_code < 400 and not request.url.path.startswith("/api/admin/"):
            visitors.record(request.client.host if request.client else "",
                            request.headers.get("user-agent", ""), request.url.path)
        if route is not None and request.url.path.startswith("/api/"):
            perf.record_route(route.path, (time.perf_counter() - t0) * 1000)
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("X-Robots-Tag", "noindex")  # data, not pages (SEO)
        else:
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
        out = store.current_board(datetime.now(TZ), STALE_S)
        age = store.last_ok_age(datetime.now(TZ))
        out["age_s"] = age
        out["stale"] = age is None or age > STALE_S
        out["boards"] = _boards(store)
        out["attribution"] = ATTRIBUTION
        return out

    def _boards(store: Store) -> dict:
        """Per panel: seconds since its last accepted reading and whether it is fresh
        (a panel whose frames are rejected, e.g. partial reads, goes stale alone)."""
        ages = store.board_ages(datetime.now(TZ))
        return {key: {"age_s": ages[b], "ok": ages[b] is not None and ages[b] <= STALE_S,
                      "stale": ages[b] is None or ages[b] > STALE_S}
                for b, key in (("arrival", "arrivals"), ("departure", "departures"))}

    @app.api_route("/api/health", methods=["GET", "HEAD"])  # uptime monitors default to HEAD
    def health(request: Request):
        store = store_of(request)
        age = store.last_ok_age(datetime.now(TZ))
        return {"ok": age is not None and age <= STALE_S, "age_s": age, "version": __version__,
                "boards": _boards(store), "ocr": ocr_stats.snapshot(),
                "weather_age_s": weather.age_s(store.latest_weather(), datetime.now(timezone.utc))}

    @app.get("/api/changelog")
    def changelog_(response: Response):
        response.headers["Cache-Control"] = "no-cache"
        return {"version": __version__, "entries": changelog()}

    @app.get("/api/config")
    def config():
        return {**panel_config(), "weather": weather.ui_config(settings.weather is not None)}

    @app.get("/api/weather")
    def weather_now(request: Request):
        return weather.present(store_of(request).latest_weather(), datetime.now(timezone.utc))

    @app.get("/api/history")
    def history(request: Request, response: Response):
        q = request.query_params
        all_days = q.get("all") or "0"
        if all_days not in ("0", "1"):
            raise _bad("Parametru „all” invalid (0 sau 1).")
        if all_days == "1":
            return _history_all(request)
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

    def _history_all(request: Request) -> dict:
        """All days (optionally one `date`) of one `train` or — without it — of every
        train, newest first, `limit` per page (1–200) after `cursor`; see app.history_all."""
        q = request.query_params
        train = _parse_train(q["train"]) if q.get("train") else None
        day = _parse_date(q.get("date"), default_today=False) if q.get("date") else None
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
        limit = stats_api._int(q.get("limit"), "limit", 1, history_all.PAGE_MAX) or history_all.PAGE_MAX
        cursor = q.get("cursor") or None
        if cursor is not None:
            try:
                history_all.parse_cursor(cursor)
            except ValueError:
                raise _bad("Cursor de paginare invalid.") from None
        conf = q.get("doar_confirmate") or "0"
        if conf not in ("0", "1"):
            raise _bad("Parametru „doar_confirmate” invalid (0 sau 1).")
        p = stats.Params(on_time=stats_api._int(q.get("prag"), "prag", 0, 60),
                         min_sample=stats_api._int(q.get("min"), "min", 1, 1000),
                         board=board_, date_from=day, date_to=day, confirmed_only=conf == "1")
        d = history_all.page(store_of(request), train, p, station=station, time_from=time_from,
                             time_to=time_to, limit=limit, cursor=cursor)
        d["date"] = day.isoformat() if day else None
        return d

    @app.get("/api/train/{no}")
    def train_events(request: Request, no: str):
        n = _parse_train(no)
        day = _parse_date(request.query_params.get("date"))
        return {"train": n, "date": day.isoformat(),
                "events": store_of(request).train_events(n, day)}

    @app.get("/api/follows")
    async def follows(request: Request):
        ep = _check_push_endpoint(request.query_params.get("endpoint"))
        await _check_owner(store_of(request), ep, request.headers.get("x-push-auth"))  # header: not logged
        return {"follows": await run_in_threadpool(store_of(request).list_follows, ep)}

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
        p256dh, auth = _sub_keys(body)
        try:
            await run_in_threadpool(store_of(request).subscribe, ep, p256dh, auth)
        except PermissionError:
            raise _bad(_NOT_OWNER, 403) from None
        except ValueError:
            raise _bad("Abonare invalidă.") from None
        return {"ok": True}

    @app.post("/api/push/resubscribe")
    async def resubscribe(request: Request):
        """The browser re-subscribed with the current VAPID key: move the follows of
        `old_endpoint` (proven by `old_auth`, its keys.auth) to the new subscription, at most
        MAX_FOLLOWS, and drop the old one. `dropped`: follows cut by the cap."""
        body = await _json_body(request)
        old = _check_push_endpoint(body.get("old_endpoint"))
        ep = _check_push_endpoint(body.get("endpoint"))
        p256dh, auth = _sub_keys(body)
        try:
            _, dropped = await run_in_threadpool(store_of(request).resubscribe, old,
                                                 body.get("old_auth"), ep, p256dh, auth)
        except PermissionError:
            raise _bad(_NOT_OWNER, 403) from None
        except ValueError:
            raise _bad("Abonare invalidă.") from None
        return {"ok": True, "dropped": dropped}

    @app.post("/api/push/unsubscribe")
    async def unsubscribe(request: Request):
        body = await _json_body(request)
        ep = _check_push_endpoint(body.get("endpoint"))
        await _check_owner(store_of(request), ep, body.get("auth"))
        await run_in_threadpool(store_of(request).unsubscribe, ep)
        return {"ok": True}

    async def _follow_args(request: Request) -> tuple[str, int, date]:
        body = await _json_body(request)
        ep = _check_push_endpoint(body.get("endpoint"))
        n = _parse_train(body.get("train"))
        d = body.get("date")
        if not isinstance(d, str):
            raise _bad("Data lipsește (format AAAA-LL-ZZ).")
        day = _parse_date(d, default_today=False)
        await _check_owner(store_of(request), ep, body.get("auth"))
        return ep, n, day

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

    app.include_router(admin.router)       # /api/admin/* (auth, „Capturi OCR")
    app.include_router(corrections_api.router)  # /api/admin/corrections* (admin only, v9)
    app.include_router(ocr_alt_api.router)  # /api/admin/ocr-alt* (admin only, #ocr2)
    app.include_router(infofer_api.router)  # /api/admin/infofer (admin only, #infofer)
    app.include_router(stats_api.router)   # /api/journeys, /api/trains/stats, /api/stats*
    app.include_router(stats_platform.router)  # /api/stats/platform-changes
    app.include_router(stats_dwell.router)     # /api/stats/dwell
    app.include_router(stats_read_errors.router)  # /api/stats/read-errors
    app.include_router(peron_api.router)       # /api/predict/peron (estimare, read-only)
    app.include_router(trains_api.router)  # /api/trains (public catalog)
    app.include_router(system_api.router)  # /api/system (public, minimal)
    app.include_router(system_api.admin_router)  # /api/admin/system (admin, Sistem)
    app.include_router(stats_quality_daily.router)  # /api/admin/quality-daily/* (admin, Sistem)

    @app.get("/api/export/history.csv", include_in_schema=False)
    async def export_history_csv(request: Request):
        # Export CSV al istoricului (Val 4b). Limitat per client; baza în mod doar-citire.
        q = request.query_params
        ip = request.client.host if request.client else "?"
        try:
            export.admit(ip)
            text, truncated = await run_in_threadpool(
                export.history_csv, store_of(request).path,
                q.get("from"), q.get("to"), q.get("train"))
        except export.ExportRefused as e:
            return JSONResponse({"detail": e.msg}, status_code=e.status,
                                headers={"Cache-Control": "no-store"})
        name = f"istoric-{q.get('from') or 'start'}-{q.get('to') or 'azi'}.csv"
        headers = {"Content-Disposition": f'attachment; filename="{name}"',
                   "Cache-Control": "no-store"}
        if truncated:
            headers["X-Truncated"] = "1"
        # BOM UTF-8: Excel citește corect diacriticele doar cu el.
        return Response(content=("﻿" + text).encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers=headers)

    @app.get("/api/stats/seasons", include_in_schema=False)
    async def stats_seasons(request: Request, format: str = "json"):
        # Comparație sezoane și meteo (Val 5a); parametrii ca la /api/stats/overview.
        p = stats_api.stats_params(request)
        d = await run_in_threadpool(seasons.overview, store_of(request), p)
        if format == "csv":
            return Response(content=("﻿" + seasons.to_csv(d)).encode("utf-8"),
                            media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": 'attachment; filename="sezoane.csv"'})
        return d

    @app.get("/api/trains/{no}/prediction", include_in_schema=False)
    async def train_prediction(request: Request, no: int):
        # Estimarea întârzierii finale per tren (Val 5b). Cache 5 min: poarta rulează backtestul.
        import time
        from datetime import datetime
        cache = getattr(request.app.state, "prediction_cache", None) or {}
        hit = cache.get(no)
        if hit and time.monotonic() - hit[0] < 300:
            return hit[1]

        def run():
            with stats_overview._reader(store_of(request)) as c:
                return line_prediction.compute(c, no, datetime.now(TZ).date())
        d = await run_in_threadpool(run)
        cache[no] = (time.monotonic(), d)
        request.app.state.prediction_cache = cache
        return d

    # The head of a public page as JSON, for the SPA after an in-app navigation / language change
    # (web/app.js syncHead): the same Page and URL rules as the server-rendered HTML (_html below;
    # seo_cache is assigned there, before any request).
    @app.get("/api/meta")
    def page_meta(request: Request, path: str = "/", lang: str = "ro"):
        lang = "en" if lang == "en" else "ro"
        parts, page = path.split("/"), None
        if path == "/" or len(parts) == 2 and parts[1] in seo.PUBLIC:
            name = parts[1] or "tabela"
            page = seo.cached(seo_cache, ("page", name, lang), seo.TTL_PAGE,
                              lambda: seo.static_page(name, lang, store_of(request), seo_cache))
        elif len(parts) == 3 and parts[1] == "tren":
            no = parts[2]
            if no.isascii() and no.isdigit() and len(no) <= 6 and 0 < int(no) < 1_000_000:
                page = seo.train_page(int(no), lang, store_of(request), seo_cache)
        elif len(parts) == 3 and parts[1] == "statie":
            name = unquote(parts[2])
            key = stations.canonical(name) if 0 < len(name) <= MAX_STATION_LEN else ""
            page = seo.station_page(key, lang, store_of(request), seo_cache) if key else None
        if page is None:
            page = seo.not_found_page(path[:200], lang)
        me, ok = seo.url(page.path, lang), seo.indexable_page(page)
        return {"status": page.status, "title": page.title, "description": page.description, "url": me,
                "canonical": me if ok else None, "robots": None if ok else "noindex",
                "alternates": {c: seo.url(page.path, lg) for c, lg in (("ro", "ro"), ("en", "en"),
                                                                       ("x-default", "ro"))} if ok else None,
                "jsonld": seo._jsonld(page, lang) if ok else None}

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

    # PWA files with explicit types (the OS mimetypes table may lack them).
    # The service worker must always be revalidated so a deploy reaches clients.
    @app.api_route("/sw.js", methods=["GET", "HEAD"], include_in_schema=False)
    def service_worker():
        return FileResponse(WEB_DIR / "sw.js", media_type="text/javascript",
                            headers={"Cache-Control": "no-cache"})

    @app.api_route("/manifest.webmanifest", methods=["GET", "HEAD"], include_in_schema=False)
    def manifest():
        return FileResponse(WEB_DIR / "manifest.webmanifest",
                            media_type="application/manifest+json",
                            headers={"Cache-Control": "no-cache"})

    # index.html for every public page (SEO, app/seo.py): own head, canonical, hreflang, JSON-LD
    # and a plain-HTML version of the content; ?lang=en serves the English head and content.
    seo_cache: dict = {}

    def _shell(lang: str) -> str:
        raw = (WEB_DIR / "index.html").read_bytes().decode("utf-8")
        return _index_en(raw) if lang == "en" else raw

    def _html(request: Request, make) -> Response:
        if not (WEB_DIR / "index.html").is_file():
            raise _bad("Nu există.", 404)
        lang = "en" if request.query_params.get("lang") == "en" else "ro"
        page = make(lang)
        if page is None:
            page = seo.not_found_page(request.url.path, lang)
        key = ("html", page.path, page.status, lang)
        body = seo.cached(seo_cache, key, seo.TTL_PAGE, lambda: seo.render(_shell(lang), page, lang))
        headers = None if seo.indexable_page(page) else {"X-Robots-Tag": "noindex"}
        return Response(body, status_code=page.status, media_type="text/html; charset=utf-8",
                        headers=headers)

    def _static_page(name: str):
        def handler(request: Request):
            return _html(request, lambda lang: seo.cached(
                seo_cache, ("page", name, lang), seo.TTL_PAGE,
                lambda: seo.static_page(name, lang, store_of(request), seo_cache)))
        return handler

    app.add_api_route("/", _static_page("tabela"), methods=["GET", "HEAD"], include_in_schema=False)
    app.add_api_route("/index.html", _static_page("tabela"), methods=["GET", "HEAD"], include_in_schema=False)
    for _name in seo.PUBLIC:
        app.add_api_route("/" + _name, _static_page(_name), methods=["GET", "HEAD"], include_in_schema=False)

    def _private(name: str):
        def handler(request: Request):  # the page itself lives at /#name (hash route, never indexed)
            return RedirectResponse("/#" + name, status_code=302, headers={"X-Robots-Tag": "noindex"})
        return handler
    for _name in seo.PRIVATE:
        app.add_api_route("/" + _name, _private(_name), methods=["GET", "HEAD"], include_in_schema=False)

    @app.api_route("/tren", methods=["GET", "HEAD"], include_in_schema=False)
    @app.api_route("/statie", methods=["GET", "HEAD"], include_in_schema=False)
    def detail_index(request: Request):
        return RedirectResponse("/trenuri" if request.url.path == "/tren" else "/statii", status_code=301)

    @app.api_route("/tren/{no}", methods=["GET", "HEAD"], include_in_schema=False)
    def train_page(request: Request, no: str):
        if no.isascii() and no.isdigit() and len(no) <= 7 and 0 < int(no) < 1_000_000 and str(int(no)) != no:
            return RedirectResponse(f"/tren/{int(no)}" + _query(request), status_code=301)  # leading zeros
        ok = no.isascii() and no.isdigit() and len(no) <= 6 and 0 < int(no) < 1_000_000
        return _html(request, lambda lang: seo.train_page(int(no), lang, store_of(request), seo_cache)
                     if ok else None)

    @app.api_route("/statie/{name:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def station_page(request: Request, name: str):
        key = stations.canonical(name) if 0 < len(name) <= MAX_STATION_LEN else ""
        if key and key != name:  # case / display-name form → the stored key's URL
            return RedirectResponse(seo.station_path(key) + _query(request), status_code=301)
        return _html(request, lambda lang: seo.station_page(key, lang, store_of(request), seo_cache)
                     if key else None)

    def _query(request: Request) -> str:
        return "?" + request.url.query if request.url.query else ""

    @app.api_route("/robots.txt", methods=["GET", "HEAD"], include_in_schema=False)
    def robots():
        return Response(seo.robots_txt(), media_type="text/plain; charset=utf-8")

    @app.api_route("/sitemap.xml", methods=["GET", "HEAD"], include_in_schema=False)
    def sitemap(request: Request):
        body = seo.cached(seo_cache, ("sitemap",), seo.TTL_DATA, lambda: seo.sitemap_xml(store_of(request)))
        return Response(body, media_type="application/xml; charset=utf-8")

    @app.exception_handler(StarletteHTTPException)
    async def not_found(request: Request, exc: StarletteHTTPException):
        path = request.url.path
        if (exc.status_code != 404 or path.startswith("/api/") or request.method not in ("GET", "HEAD")
                or not (WEB_DIR / "index.html").is_file()):
            return await http_exception_handler(request, exc)
        # trailing slash / upper case of a public page → its canonical path
        parts = path.rstrip("/").split("/")
        if len(parts) > 1:
            parts[1] = parts[1].lower()
        target = "/".join(parts) or "/"
        if target != path and (target == "/" or parts[1] in seo.PUBLIC and len(parts) == 2
                               or parts[1] in ("tren", "statie") and len(parts) >= 3):
            return RedirectResponse(target + _query(request), status_code=301)
        return await run_in_threadpool(_html, request, lambda lang: None)

    # Static frontend last, so /api/* routes win. No disk writes here.
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    else:
        log.warning("web directory %s missing; static frontend not served", WEB_DIR)
    return app
