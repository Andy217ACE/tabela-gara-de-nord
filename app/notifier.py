# © 2026 Andy217Ace
"""Web Push notifications for followed trains.

Debounce: `handle(events, today)` is called after every ingest. Each pushable
event (delay / platform / gone) becomes a *pending* change keyed by
(service, kind) holding its new value and the id of the ok run it came from.
On later calls, once the store's latest ok run id has advanced (i.e. a new
successful reading exists; failed readings do not count), every pending change
is checked against the service's current stored state: still the same value
(or still `gone`) -> seen once more; different -> dropped silently. A change is
pushed once it has been seen in `confirm` consecutive successful readings, so a
one-frame OCR misread never produces a push.

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


class SubscriptionGone(Exception):
    """The push service says the subscription no longer exists (404/410)."""


@dataclass
class _Pending:
    event: Event
    value: str | None
    run_id: int | None
    seen: int = 1


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
                 confirm: int = 2):
        self.store = store
        self.send = send
        self.confirm = max(1, confirm)
        self._pending: dict[tuple, _Pending] = {}
        self._last: dict[tuple, str | None] = {}  # (svc, kind) -> last pushed / baseline

    # -- state helpers ----------------------------------------------------

    def _still_true(self, p: _Pending) -> bool:
        svc = _svc(p.event)
        st = self.store.service_state(p.event.row.board, svc[0], p.event.row.train_no,
                                      p.event.row.sched_time)
        if st is None:
            return False
        if p.event.kind == "gone":
            return st["status"] == "gone"
        if st["status"] != "listed":
            return False
        cur = st["delay"] if p.event.kind == "delay" else st["platform"]
        return (None if cur is None else str(cur)) == p.value

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

    async def handle(self, events: list[Event], today: date) -> None:
        run_id = self.store.last_ok_run_id()
        # 1. Re-check older pending changes against the new reading.
        for key, p in list(self._pending.items()):
            if p.run_id == run_id:
                continue  # no new successful reading since
            if self._still_true(p):
                p.seen += 1
                p.run_id = run_id
            else:
                del self._pending[key]
        # 2. Record this reading's changes.
        for ev in events:
            self._baseline(ev)
            if ev.kind in PUSH_KINDS and ev.service_date:
                self._pending[(_svc(ev), ev.kind)] = _Pending(ev, ev.new, run_id)
        # 3. Push the confirmed ones.
        for key, p in list(self._pending.items()):
            if p.seen < self.confirm:
                continue
            del self._pending[key]
            if key in self._last and (p.event.kind == "gone" or self._last[key] == p.value):
                continue  # same transition already pushed (or unchanged vs. baseline)
            self._last[key] = p.value
            if message(p.event) is None:
                continue
            await self._push(p.event)
        self._prune(today)

    async def _push(self, ev: Event) -> None:
        data = payload(ev)
        for sub in self.store.followers(ev.row.train_no, ev.service_date):
            try:
                await self.send(sub, data)
            except SubscriptionGone:
                log.info("push subscription gone; removing")
                self.store.unsubscribe(sub.endpoint)
            except Exception as e:  # one bad endpoint must not stop the others
                log.warning("push failed: %s", type(e).__name__)


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
