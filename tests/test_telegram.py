# © 2026 Andy217Ace
import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import telegram as tg
from app.models import Row
from app.notifier import Notifier, event_key
from app.store import Store, Subscription

pytestmark = pytest.mark.usefixtures("legacy_rules")

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=BUC)
DAY = date(2026, 10, 20)
EP = "https://fcm.googleapis.com/fcm/send/abc"
TOKEN = "123456:SECRET-TOKEN-XYZ"
CHAT = "424242"


def cfg(tmp_path, **kw):
    return tg.TelegramConfig(token=TOKEN, chat_id=CHAT,
                             state_path=str(tmp_path / "sent.json"), **kw)


def fixed_clock():
    return datetime(2026, 10, 20, 12, 34, tzinfo=BUC)


# -- configuration ----------------------------------------------------------

def test_disabled_without_token_or_chat():
    assert tg.config_from_env({}) is None
    assert tg.config_from_env({"TELEGRAM_BOT_TOKEN": TOKEN}) is None
    assert tg.config_from_env({"TELEGRAM_CHAT_ID": CHAT}) is None


def test_enabled_from_env_and_token_hidden_in_repr():
    c = tg.config_from_env({"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_CHAT_ID": CHAT})
    assert c is not None and c.token == TOKEN and c.chat_id == CHAT
    assert TOKEN not in repr(c)


# -- sending ----------------------------------------------------------------

def client_with(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_sends_romanian_text_with_reading_time(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    ch = tg.TelegramChannel(cfg(tmp_path), client=client_with(handler), clock=fixed_clock)
    data = {"title": "Gara de Nord", "body": "IR 1636: întârziere +10 min", "url": "/"}
    asyncio.run(ch.send(None, data))
    assert len(calls) == 1
    req = calls[0]
    assert req.url.path == f"/bot{TOKEN}/sendMessage"
    body = req.read().decode()
    assert "întârziere +10 min" in body
    assert "12:34" in body
    assert CHAT in body


def test_errors_are_not_raised_and_token_never_logged(tmp_path, caplog):
    def handler(request):
        raise httpx.ConnectError(f"boom {request.url}")  # str(e) carries the token URL

    caplog.set_level(logging.WARNING, logger="app.telegram")
    ch = tg.TelegramChannel(cfg(tmp_path), client=client_with(handler), clock=fixed_clock)
    asyncio.run(ch.send(None, {"body": "x"}))
    assert TOKEN not in caplog.text
    assert "ConnectError" in caplog.text


def test_http_error_logged_at_most_once_per_ten_minutes(tmp_path, caplog, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(tg.time, "monotonic", lambda: now[0])
    caplog.set_level(logging.WARNING, logger="app.telegram")

    def handler(request):
        return httpx.Response(429, json={"ok": False})

    ch = tg.TelegramChannel(cfg(tmp_path), client=client_with(handler), clock=fixed_clock)
    for _ in range(3):
        asyncio.run(ch.send(None, {"body": "x"}))
    assert caplog.text.count("HTTP 429") == 1
    now[0] += 601
    asyncio.run(ch.send(None, {"body": "x"}))
    assert caplog.text.count("HTTP 429") == 2
    assert TOKEN not in caplog.text


# -- persistent sent log ----------------------------------------------------

def test_sent_log_survives_restart_and_prunes_old_days(tmp_path):
    path = str(tmp_path / "sent.json")
    log1 = tg.SentLog(path)
    log1.record("k-today", "2026-10-20", date(2026, 10, 20))
    log1.record("k-old", "2026-10-10", date(2026, 10, 20))
    log2 = tg.SentLog(path)  # a "restart"
    assert log2.has("k-today")
    assert not log2.has("k-old")


def test_sent_log_unreadable_file_starts_empty(tmp_path):
    p = tmp_path / "sent.json"
    p.write_text("not json", encoding="utf-8")
    assert not tg.SentLog(str(p)).has("anything")


# -- notifier integration ---------------------------------------------------

class FakeChannel:
    def __init__(self, store_path=None, hang=False, boom=False):
        self.sent = []
        self.keys = set()
        self.hang, self.boom = hang, boom

    def has(self, key):
        return key in self.keys

    def record(self, key, service_date, today):
        self.keys.add(key)

    async def send(self, sub, data):
        if self.hang:
            await asyncio.sleep(3600)
        if self.boom:
            raise RuntimeError("boom")
        self.sent.append(data)


def board(delay=0):
    return [
        Row("arrival", "IR", 1621, "Brasov", "CFR", "12:10"),
        Row("arrival", "IR", 1622, "Brasov", "CFR", "12:20"),
        Row("departure", "IR", 1731, "Brasov", "CFR", "12:15"),
        Row("departure", "IR", 1732, "Brasov", "CFR", "12:30"),
        Row("departure", "IR", 1636, "Constanta", "CFR", "12:40", delay_min=delay,
            platform=13, confidence=1.0, delay_read=True),
    ]


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("app.store._today", lambda: DAY)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    s.subscribe(EP, "p", "a")
    s.follow(EP, 1636, DAY)
    yield s
    s.close()


def run_ticks(notifier, store, delays, start=0):
    for i, d in enumerate(delays, start=start):
        events = store.ingest(board(delay=d), T0 + timedelta(minutes=i))
        asyncio.run(notifier.handle(events, DAY))


def test_followed_train_goes_to_telegram_once(store):
    ch = FakeChannel()
    n = Notifier(store, lambda s, d: asyncio.sleep(0), telegram=ch)
    run_ticks(n, store, [0, 10, 10, 10, 10])
    assert [d["body"] for d in ch.sent] == ["IR 1636: întârziere +10 min"]


def test_untracked_train_is_not_sent_to_telegram(store):
    ch = FakeChannel()
    store.unfollow(EP, 1636, DAY)
    n = Notifier(store, lambda s, d: asyncio.sleep(0), telegram=ch)
    run_ticks(n, store, [0, 10, 10, 10])
    assert ch.sent == []


def test_same_event_not_sent_twice_across_restart(store, tmp_path):
    path = str(tmp_path / "sent.json")
    ch1 = tg.TelegramChannel(cfg(tmp_path), client=client_with(
        lambda r: httpx.Response(200, json={"ok": True})), clock=fixed_clock)
    ch1.sent = tg.SentLog(path)
    n1 = Notifier(store, lambda s, d: asyncio.sleep(0), telegram=ch1)
    run_ticks(n1, store, [0, 10, 10])
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    ch2 = tg.TelegramChannel(cfg(tmp_path), client=client_with(handler), clock=fixed_clock)
    n2 = Notifier(store, lambda s, d: asyncio.sleep(0), telegram=ch2)  # restarted process
    run_ticks(n2, store, [10, 10], start=3)
    assert calls == []  # the event was already attempted before the restart


def test_failing_telegram_does_not_block_handle_or_web_push(store):
    pushed = []

    async def web(sub, data):
        pushed.append(data)

    n = Notifier(store, web, telegram=FakeChannel(boom=True))
    run_ticks(n, store, [0, 10, 10])
    assert len(pushed) == 1


def test_hanging_telegram_is_bounded_by_send_timeout(store):
    n = Notifier(store, lambda s, d: asyncio.sleep(0), telegram=FakeChannel(hang=True),
                 send_timeout=0.05)
    start = datetime.now()
    run_ticks(n, store, [0, 10, 10])
    assert (datetime.now() - start).total_seconds() < 5


def test_event_key_identifies_service_kind_and_value(store):
    ev_a = store.ingest(board(delay=0), T0)
    ev_b = store.ingest(board(delay=10), T0 + timedelta(minutes=1))
    assert ev_b and ev_b[0].kind == "delay"
    assert "1636" in event_key(ev_b[0])
    ev_c = store.ingest(board(delay=20), T0 + timedelta(minutes=2))
    assert ev_c and event_key(ev_c[0]) != event_key(ev_b[0])
