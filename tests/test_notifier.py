# © 2026 Andy217Ace
import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app import notifier as notifier_mod
from app.models import Row
from app.notifier import Notifier, SubscriptionGone, make_webpush_sender
from app.store import Store, Subscription

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=BUC)
DAY = date(2026, 10, 20)
EP = "https://fcm.googleapis.com/fcm/send/abc"
EP2 = "https://fcm.googleapis.com/fcm/send/def"
EP3 = "https://fcm.googleapis.com/fcm/send/ghi"


def board(delay=0, platform=13, with_1636=True, conf=1.0):
    rows = [
        Row("arrival", "IR", 1621, "Brasov", "CFR", "12:10"),
        Row("arrival", "IR", 1622, "Brasov", "CFR", "12:20"),
        Row("departure", "IR", 1731, "Brasov", "CFR", "12:15"),
        Row("departure", "IR", 1732, "Brasov", "CFR", "12:30"),
    ]
    if with_1636:
        rows.append(Row("departure", "IR", 1636, "Constanta", "CFR", "12:40",
                        delay_min=delay, platform=platform, confidence=conf))
    return rows


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("app.store._today", lambda: DAY)


class Harness:
    def __init__(self, store, fail=None):
        self.store = store
        self.sent: list[tuple[Subscription, dict]] = []
        self.fail = fail or {}
        self.n = 0
        self.notifier = Notifier(store, self.send)

    async def send(self, sub, payload):
        if sub.endpoint in self.fail:
            raise self.fail[sub.endpoint]
        self.sent.append((sub, payload))

    def tick(self, rows):
        events = self.store.ingest(rows, T0 + timedelta(minutes=self.n))
        self.n += 1
        asyncio.run(self.notifier.handle(events, DAY))
        return events

    def bodies(self):
        return [p["body"] for _, p in self.sent]


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    s.subscribe(EP, "p", "a")
    s.follow(EP, 1636, DAY)
    yield s
    s.close()


@pytest.fixture
def h(store):
    return Harness(store)


def test_change_seen_once_sends_nothing(h):
    # Review Focus 4: a one-frame OCR misread produces 0 notifications.
    h.tick(board(delay=0))
    h.tick(board(delay=10))   # misread
    h.tick(board(delay=0))    # back
    h.tick(board(delay=0))
    h.tick(board(delay=0))
    assert h.sent == []


def test_change_confirmed_in_two_ingests_sends_once(h):
    h.tick(board(delay=0))
    h.tick(board(delay=10))
    assert h.sent == []
    h.tick(board(delay=10))
    assert h.bodies() == ["IR 1636: întârziere +10 min"]
    sub, payload = h.sent[0]
    assert sub == Subscription(EP, "p", "a")
    assert payload == {"title": "Gara de Nord", "body": "IR 1636: întârziere +10 min",
                       "tag": "1636-2026-10-20", "url": "/"}
    for _ in range(3):
        h.tick(board(delay=10))   # same value afterwards -> nothing
    assert len(h.sent) == 1


def test_misread_then_back_does_not_resend(h):
    h.tick(board(delay=0))
    h.tick(board(delay=10))
    h.tick(board(delay=10))       # sent +10
    h.tick(board(delay=15))       # misread
    h.tick(board(delay=10))       # back to the already-sent value
    h.tick(board(delay=10))
    h.tick(board(delay=10))
    assert h.bodies() == ["IR 1636: întârziere +10 min"]


def test_misread_relative_to_initial_value_is_silent(h):
    # Train first seen with +10 (no event); a one-frame misread must not lead
    # to a "+10" push when the value returns.
    h.tick(board(delay=10))
    h.tick(board(delay=20))
    h.tick(board(delay=10))
    h.tick(board(delay=10))
    assert h.sent == []


def test_back_on_time_message(h):
    h.tick(board(delay=10))
    h.tick(board(delay=0))
    h.tick(board(delay=0))
    assert h.bodies() == ["IR 1636: la timp"]


def test_platform_message(h):
    h.tick(board(platform=None))
    h.tick(board(platform=13))
    h.tick(board(platform=13))
    assert h.bodies() == ["IR 1636: linia 13"]


def test_platform_removed_is_not_pushed(h):
    h.tick(board(platform=13))
    h.tick(board(platform=None))
    h.tick(board(platform=None))
    assert h.sent == []


def test_failed_ingest_does_not_confirm(h):
    h.tick(board(delay=0))
    h.tick(board(delay=10))
    h.tick(board()[:2])           # failed run (too few rows): no new reading
    assert h.sent == []
    h.tick(board(delay=10))
    assert h.bodies() == ["IR 1636: întârziere +10 min"]


def test_gone_reappear_gone_notifies_per_transition(h):
    # Review Focus 5: one push per confirmed transition, no duplicates.
    gone_msg = "IR 1636: a ieșit de pe panou"
    h.tick(board())
    h.tick(board(with_1636=False))
    h.tick(board(with_1636=False))   # gone event (2 misses)
    assert h.sent == []
    h.tick(board(with_1636=False))   # still gone -> confirmed
    assert h.bodies() == [gone_msg]
    h.tick(board(with_1636=False))
    h.tick(board(with_1636=False))
    assert h.bodies() == [gone_msg]
    h.tick(board())                  # reappears (no push for appeared)
    h.tick(board())
    assert h.bodies() == [gone_msg]
    h.tick(board(with_1636=False))
    h.tick(board(with_1636=False))   # gone again
    h.tick(board(with_1636=False))   # confirmed
    h.tick(board(with_1636=False))
    assert h.bodies() == [gone_msg, gone_msg]


def test_gone_contradicted_is_dropped(h):
    h.tick(board())
    h.tick(board(with_1636=False))
    h.tick(board(with_1636=False))   # gone event
    h.tick(board())                  # back immediately -> gone not confirmed
    h.tick(board())
    assert h.sent == []


def test_only_followers_receive(store):
    store.subscribe(EP2, "q", "b")
    store.follow(EP2, 1621, DAY)                       # other train
    store.subscribe(EP3, "r", "c")
    store.follow(EP3, 1636, DAY + timedelta(days=1))   # other day
    h = Harness(store)
    h.tick(board(delay=0))
    h.tick(board(delay=10))
    h.tick(board(delay=10))
    assert [s.endpoint for s, _ in h.sent] == [EP]


def test_subscription_gone_is_deleted_and_others_still_sent(store):
    store.subscribe(EP2, "q", "b")
    store.follow(EP2, 1636, DAY)
    store.subscribe(EP3, "r", "c")
    store.follow(EP3, 1636, DAY)
    h = Harness(store, fail={EP: SubscriptionGone(EP), EP2: RuntimeError("boom")})
    h.tick(board(delay=0))
    h.tick(board(delay=10))
    h.tick(board(delay=10))
    assert [s.endpoint for s, _ in h.sent] == [EP3]
    assert store.list_follows(EP) == []
    assert store.followers(1636, DAY) == [Subscription(EP2, "q", "b"),
                                           Subscription(EP3, "r", "c")]


def test_confirm_one_sends_immediately(store):
    h = Harness(store)
    h.notifier = Notifier(store, h.send, confirm=1)
    h.tick(board(delay=0))
    h.tick(board(delay=7))
    assert h.bodies() == ["IR 1636: întârziere +7 min"]


# -- re-read requirement (fix round 1) ----------------------------------------

def test_misread_then_row_missing_then_back_no_push(h):
    h.tick(board(delay=0))
    h.tick(board(delay=10))              # misread
    h.tick(board(with_1636=False))       # row missing: must not confirm
    h.tick(board(delay=0))
    h.tick(board(delay=0))
    h.tick(board(delay=0))
    assert h.sent == []


def test_misread_then_low_confidence_row_then_back_no_push(h):
    h.tick(board(delay=0))
    h.tick(board(delay=10))              # misread
    h.tick(board(delay=0, conf=0.1))     # low confidence: must not confirm
    h.tick(board(delay=0))
    h.tick(board(delay=0))
    assert h.sent == []


def test_hold_while_not_reread_then_confirm(h):
    h.tick(board(delay=0))
    h.tick(board(delay=10))
    h.tick(board(delay=10, conf=0.1))    # hold 1
    h.tick(board(delay=10, conf=0.1))    # hold 2
    assert h.sent == []
    h.tick(board(delay=10))              # re-read -> confirmed
    assert h.bodies() == ["IR 1636: întârziere +10 min"]


def test_dropped_after_three_runs_without_reread(h):
    h.tick(board(delay=0))
    h.tick(board(delay=10))
    for _ in range(3):
        h.tick(board(delay=10, conf=0.1))
    h.tick(board(delay=10))
    h.tick(board(delay=10))
    assert h.sent == []


def test_successive_changes_before_confirmation(h):
    h.tick(board(delay=0))
    h.tick(board(delay=10))
    h.tick(board(delay=15))
    h.tick(board(delay=20))
    h.tick(board(delay=20))
    h.tick(board(delay=20))
    assert h.bodies() == ["IR 1636: întârziere +20 min"]


def test_change_and_resurrection_in_same_reading(h):
    gone_msg = "IR 1636: a ieșit de pe panou"
    h.tick(board(delay=0))
    h.tick(board(with_1636=False))
    h.tick(board(with_1636=False))       # gone
    h.tick(board(with_1636=False))       # gone confirmed
    ev = h.tick(board(delay=10))         # resurrection + delay change together
    assert {e.kind for e in ev if e.row.train_no == 1636} == {"appeared", "delay"}
    h.tick(board(delay=10))
    assert h.bodies() == [gone_msg, "IR 1636: întârziere +10 min"]
    h.tick(board(with_1636=False))
    h.tick(board(with_1636=False))
    h.tick(board(with_1636=False))
    assert h.bodies() == [gone_msg, "IR 1636: întârziere +10 min", gone_msg]


# -- concurrency (fix round 1) ------------------------------------------------

def test_overlapping_handle_calls_do_not_raise(store):
    sent = []

    async def slow_send(sub, payload):
        await asyncio.sleep(0.05)
        sent.append(payload["body"])

    n = Notifier(store, slow_send)
    store.ingest(board(delay=0), T0)
    e1 = store.ingest(board(delay=10), T0 + timedelta(minutes=1))

    async def main():
        await n.handle(e1, DAY)
        e2 = store.ingest(board(delay=10), T0 + timedelta(minutes=2))
        await asyncio.gather(n.handle(e2, DAY), n.handle(e2, DAY), n.handle([], DAY))

    asyncio.run(main())
    assert sent == ["IR 1636: întârziere +10 min"]


def test_slow_send_does_not_delay_others(store):
    for ep in (EP2, EP3):
        store.subscribe(ep, "q", "b")
        store.follow(ep, 1636, DAY)
    done = []

    async def send(sub, payload):
        if sub.endpoint == EP:           # first follower, dead endpoint
            await asyncio.sleep(5)
        done.append((sub.endpoint, asyncio.get_running_loop().time()))

    n = Notifier(store, send, send_timeout=0.6)
    store.ingest(board(delay=0), T0)
    e1 = store.ingest(board(delay=10), T0 + timedelta(minutes=1))

    async def main():
        await n.handle(e1, DAY)
        e2 = store.ingest(board(delay=10), T0 + timedelta(minutes=2))
        t = asyncio.get_running_loop().time()
        await n.handle(e2, DAY)
        return t, asyncio.get_running_loop().time() - t

    t0, elapsed = asyncio.run(main())
    assert sorted(ep for ep, _ in done) == sorted([EP2, EP3])
    assert all(at - t0 < 0.3 for _, at in done)   # not queued behind the dead one
    assert elapsed < 1.5                           # dead one cut off by the timeout
    assert store.followers(1636, DAY)[0].endpoint == EP  # timeout != gone: kept


def test_send_failure_logs_type_and_message(store, caplog):
    async def send(sub, payload):
        raise RuntimeError("web push failed: HTTP 500")

    n = Notifier(store, send)
    store.ingest(board(delay=0), T0)
    e1 = store.ingest(board(delay=10), T0 + timedelta(minutes=1))

    async def main():
        await n.handle(e1, DAY)
        await n.handle(store.ingest(board(delay=10), T0 + timedelta(minutes=2)), DAY)

    with caplog.at_level("WARNING", logger="app.notifier"):
        asyncio.run(main())
    assert "RuntimeError" in caplog.text and "HTTP 500" in caplog.text


# -- web push sender ----------------------------------------------------------

SETTINGS = SimpleNamespace(vapid_private_key="SECRET-KEY", vapid_public_key="pub",
                           vapid_subject="mailto:x@example.com")
SUB = Subscription(EP, "p256", "auth")


def test_webpush_sender_calls_pywebpush(monkeypatch):
    calls = []

    def fake(**kw):
        calls.append(kw)
        return SimpleNamespace(status_code=201)

    monkeypatch.setattr(notifier_mod, "webpush", fake)
    send = make_webpush_sender(SETTINGS)
    asyncio.run(send(SUB, {"title": "Gara de Nord", "body": "x", "tag": "t", "url": "/"}))
    kw = calls[0]
    assert kw["subscription_info"] == {"endpoint": EP, "keys": {"p256dh": "p256", "auth": "auth"}}
    assert '"body": "x"' in kw["data"]
    assert kw["vapid_private_key"] == "SECRET-KEY"
    assert kw["vapid_claims"]["sub"] == "mailto:x@example.com"


@pytest.mark.parametrize("status", [404, 410])
def test_webpush_sender_maps_gone(monkeypatch, status):
    def fake(**kw):
        raise notifier_mod.WebPushException("gone", response=SimpleNamespace(status_code=status))

    monkeypatch.setattr(notifier_mod, "webpush", fake)
    send = make_webpush_sender(SETTINGS)
    with pytest.raises(SubscriptionGone):
        asyncio.run(send(SUB, {"body": "x"}))


def test_webpush_sender_other_error_hides_key(monkeypatch):
    def fake(**kw):
        raise notifier_mod.WebPushException("bad SECRET-KEY",
                                             response=SimpleNamespace(status_code=500))

    monkeypatch.setattr(notifier_mod, "webpush", fake)
    send = make_webpush_sender(SETTINGS)
    with pytest.raises(Exception) as ei:
        asyncio.run(send(SUB, {"body": "x"}))
    assert not isinstance(ei.value, SubscriptionGone)
    assert "SECRET-KEY" not in str(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


def test_store_calls_run_off_the_event_loop_thread(store):
    import threading
    seen = []
    for name in ("last_ok_run", "service_state", "followers"):
        orig = getattr(store, name)

        def wrap(*a, _o=orig, _n=name, **k):
            seen.append((_n, threading.get_ident()))
            return _o(*a, **k)
        setattr(store, name, wrap)
    h = Harness(store)
    h.tick(board())
    h.tick(board(delay=5))
    h.tick(board(delay=5))
    h.tick(board(delay=5))
    names = {n for n, _ in seen}
    assert {"last_ok_run", "followers"} <= names
    assert all(t != threading.get_ident() for _, t in seen)
