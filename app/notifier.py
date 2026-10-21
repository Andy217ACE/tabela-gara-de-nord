# © 2026 Andy217Ace
"""Web Push notifications for followed trains.

Debounce: `handle(events, today)` is called after every ingest. Each pushable
event (delay / platform / gone) becomes a *pending* change keyed by
(service, kind) holding its new value and the id of the ok run it came from.
On later calls, once the store's latest ok run has advanced (failed readings do
not count), every pending change is checked against `store.service_state`:
- delay/platform: only if the service was re-read with a *confident* row in
  that run (`last_read == run ts`). Same value -> seen once more; different ->
  dropped. Not re-read (row missing or low confidence) -> held: neither
  confirmed nor dropped; dropped after MAX_HOLD consecutive such runs.
- gone: back on the board -> dropped; seen only at low confidence in that run
  (`last_seen == run ts`) -> held; otherwise (still absent) -> seen once more.
A change is pushed once seen in `confirm` successful readings, so a one-frame
OCR misread never produces a push. If several ingests happen between two
`handle` calls, only the latest run is checked.

Concurrency: `handle` calls are serialized with an asyncio.Lock; pushes go to
all followers concurrently (at most MAX_CONCURRENCY at once), each bounded by
`send_timeout`. The API wiring (Task 9) runs `handle` as a background task,
not inline in the poller path.

Dedup: per (service, kind) the last pushed value is remembered (seeded from the
value at first sighting / the event's `old` value), and a confirmed change equal
to it is not pushed again. A service that reappears after `gone` clears the
remembered `gone`, so a later `gone` is a new transition and may push again.
`appeared` events are never pushed. A platform cleared to "none" is not pushed.

State is kept in memory (lost on restart) and pruned to services of
`today - 1` and later.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Awaitable, Callable

from pywebpush import WebPushException, webpush

from app.models import Event
from app.store import Subscription

log = logging.getLogger(__name__)

PUSH_KINDS = ("delay", "platform", "gone")
TITLE = "Gara de Nord"
MAX_HOLD = 3          # drop a pending change after this many ok runs without a re-read
SEND_TIMEOUT = 10.0   # seconds per push
MAX_CONCURRENCY = 10  # simultaneous pushes per notification


class SubscriptionGone(Exception):
    """The push service says the subscription no longer exists (404/410)."""


@dataclass
class _Pending:
    event: Event
    value: str | None
    run_id: int | None
    seen: int = 1
    misses: int = 0  # consecutive ok runs without a confident re-read


def _svc(ev: Event) -> tuple[str, int, str, str]:
    return (ev.service_date or "", ev.row.train_no, ev.row.board, ev.row.sched_time)


def message(ev: Event) -> str | None:
    head = f"{ev.row.train_type} {ev.row.train_no}"
    if ev.kind == "delay":
        n = int(ev.new or 0)
        return f"{head}: la timp" if n == 0 else f"{head}: întârziere +{n} min"
    if ev.kind == "platform":
        return None if ev.new is None else f"{head}: linia {ev.new}"
    if ev.kind == "gone":
        return f"{head}: a ieșit de pe panou"
    return None


def payload(ev: Event) -> dict:
    return {"title": TITLE, "body": message(ev),
            "tag": f"{ev.row.train_no}-{ev.service_date}", "url": "/"}


class Notifier:
    def __init__(self, store, send: Callable[[Subscription, dict], Awaitable[None]],
                 confirm: int = 2, *, send_timeout: float = SEND_TIMEOUT,
                 max_concurrency: int = MAX_CONCURRENCY):
        self.store = store
        self.send = send
        self.confirm = max(1, confirm)
        self.send_timeout = send_timeout
        self.max_concurrency = max_concurrency
        self._pending: dict[tuple, _Pending] = {}
        self._last: dict[tuple, str | None] = {}  # (svc, kind) -> last pushed / baseline
        self._lock: asyncio.Lock | None = None
        self._lock_loop = None

    # -- state helpers ----------------------------------------------------

    def _check(self, p: _Pending, run_ts: str) -> str:
        """'confirm' | 'hold' | 'drop' for a pending change against the latest ok run."""
        svc = _svc(p.event)
        st = self.store.service_state(p.event.row.board, svc[0], p.event.row.train_no,
                                      p.event.row.sched_time)
        if st is None:
            return "drop"
        if p.event.kind == "gone":
            if st["status"] == "listed":
                return "drop"  # back on the board
            # Still gone; a low-confidence sighting in this run is no proof of absence.
            return "hold" if st["last_seen"] == run_ts else "confirm"
        if st["last_read"] != run_ts:
            return "hold"  # not re-read confidently in this run: neither confirm nor drop
        if p.event.kind == "delay" and not st.get("delay_read", True):
            # the delay cell was unreadable in this run (the stored value is the previous
            # reading): like a missing row - neither confirm nor drop, counts to MAX_HOLD
            return "hold"
        cur = st["delay"] if p.event.kind == "delay" else st["platform"]
        return "confirm" if (None if cur is None else str(cur)) == p.value else "drop"

    def _baseline(self, ev: Event) -> None:
        svc = _svc(ev)
        if ev.kind == "appeared":
            self._last.setdefault((svc, "delay"), str(ev.row.delay_min))
            self._last.setdefault((svc, "platform"),
                                  None if ev.row.platform is None else str(ev.row.platform))
            self._last.pop((svc, "gone"), None)  # a later gone is a new transition
        elif ev.kind in ("delay", "platform"):
            self._last.setdefault((svc, ev.kind), ev.old)

    def _prune(self, today: date) -> None:
        keep = (today - timedelta(days=1)).isoformat()
        for d in (self._pending, self._last):
            for k in [k for k in d if k[0][0] < keep]:
                del d[k]

    # -- main entry -------------------------------------------------------

    def _get_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock, self._lock_loop = asyncio.Lock(), loop
        return self._lock

    async def handle(self, events: list[Event], today: date) -> None:
        """Process one ingest's events. Calls are serialized (safe to overlap)."""
        async with self._get_lock():
            # _process only touches the Store (blocking sqlite) and this notifier's state,
            # which the lock serialises: run it off the event loop.
            to_push = await asyncio.to_thread(self._process, events, today)
            for ev in to_push:
                await self._push(ev)

    def _process(self, events: list[Event], today: date) -> list[Event]:
        run = self.store.last_ok_run()
        run_id, run_ts = run if run else (None, None)
        # 1. Re-check older pending changes against the latest ok reading.
        for key, p in list(self._pending.items()):
            if p.run_id == run_id:
                continue  # no new successful reading since
            p.run_id = run_id
            verdict = self._check(p, run_ts)
            if verdict == "confirm":
                p.seen += 1
                p.misses = 0
            elif verdict == "hold":
                p.misses += 1
                if p.misses >= MAX_HOLD:
                    del self._pending[key]
            else:
                del self._pending[key]
        # 2. Record this reading's changes (a newer value replaces a pending one).
        for ev in events:
            self._baseline(ev)
            if ev.kind in PUSH_KINDS and ev.service_date:
                self._pending[(_svc(ev), ev.kind)] = _Pending(ev, ev.new, run_id)
        # 3. Collect the confirmed ones.
        out: list[Event] = []
        for key, p in list(self._pending.items()):
            if p.seen < self.confirm:
                continue
            del self._pending[key]
            if key in self._last and (p.event.kind == "gone" or self._last[key] == p.value):
                continue  # same transition already pushed (or unchanged vs. baseline)
            self._last[key] = p.value
            if message(p.event) is not None:
                out.append(p.event)
        self._prune(today)
        return out

    async def _push(self, ev: Event) -> None:
        """Send to all followers concurrently (bounded); each send has a timeout."""
        data = payload(ev)
        sem = asyncio.Semaphore(self.max_concurrency)

        async def one(sub: Subscription) -> None:
            async with sem:
                try:
                    await asyncio.wait_for(self.send(sub, data), self.send_timeout)
                except SubscriptionGone:
                    log.info("push subscription gone; removing")
                    await asyncio.to_thread(self.store.unsubscribe, sub.endpoint)
                except asyncio.TimeoutError:
                    log.warning("push failed: timeout after %.0fs", self.send_timeout)
                except Exception as e:  # one bad endpoint must not stop the others
                    log.warning("push failed: %s: %s", type(e).__name__, e)

        followers = await asyncio.to_thread(self.store.followers, ev.row.train_no,
                                            ev.service_date)
        await asyncio.gather(*(one(s) for s in followers))


def make_webpush_sender(settings) -> Callable[[Subscription, dict], Awaitable[None]]:
    """`send` that delivers via pywebpush with the VAPID keys from `settings`.

    404/410 from the push service -> SubscriptionGone. Other failures are
    re-raised as RuntimeError with only the HTTP status (never the key).
    """

    def _blocking(sub: Subscription, data: dict) -> None:
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint,
                                   "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=json.dumps(data, ensure_ascii=False),
                vapid_private_key=settings.vapid_private_key,
                vapid_claims={"sub": settings.vapid_subject},  # fresh dict: webpush mutates it
                ttl=3600,
                timeout=10,
            )
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                raise SubscriptionGone(f"HTTP {status}") from None
            raise RuntimeError(f"web push failed: HTTP {status}") from None
        except Exception as e:
            raise RuntimeError(f"web push failed: {type(e).__name__}") from None

    async def send(sub: Subscription, data: dict) -> None:
        await asyncio.to_thread(_blocking, sub, data)

    return send
