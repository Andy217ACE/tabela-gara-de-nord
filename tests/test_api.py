# © 2026 Andy217Ace
import asyncio
import logging
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.models import Row

BUC = ZoneInfo("Europe/Bucharest")
DAY = date(2026, 10, 20)
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=BUC)
EP = "https://fcm.googleapis.com/fcm/send/abc"
SUB = {"endpoint": EP, "keys": {"p256dh": "p" * 20, "auth": "a" * 10}}


def settings(**kw):
    base = dict(db_path=":memory:", source_url="https://example.com/x",
                vapid_private_key="", vapid_public_key="", vapid_subject="mailto:a@b.c",
                tesseract_cmd="tesseract", poller_restart_backoff=0.01)
    base.update(kw)
    return Settings(**base)


def rows():
    return [
        Row("arrival", "IR", 1636, "BRASOV", "CFR Calatori", "12:10", 5, 3),
        Row("arrival", "R", 3001, "PLOIESTI SUD", "Regio Calatori", "12:20"),
        Row("departure", "IC", 531, "CONSTANTA", "CFR Calatori", "12:30", 0, 7),
        Row("departure", "IR", 1741, "BRASOV", "Astra", "12:40", 10, None),
    ]


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("app.store._today", lambda: DAY)
    monkeypatch.setattr("app.api._today", lambda: DAY)


@pytest.fixture
def client():
    app = create_app(settings(), start_poller=False)
    with TestClient(app) as c:
        yield c


def ingest(c, ts=T0):
    return c.app.state.store.ingest(rows(), ts)


# -- board / health -------------------------------------------------------

def test_board_returns_arrivals_and_departures(client):
    ingest(client)
    r = client.get("/api/board")
    assert r.status_code == 200
    b = r.json()
    assert [x["train_no"] for x in b["arrivals"]] == [1636, 3001]
    assert [x["train_no"] for x in b["departures"]] == [531, 1741]
    assert b["updated_at"].startswith("2026-10-20T12:00")
    assert all(x["service_date"] == "2026-10-20" for x in b["arrivals"] + b["departures"])
    assert b["stale"] is True and b["age_s"] > 180  # T0 is in the past
    assert b["attribution"] == {"source": "CFR", "url": "https://cfr.ro", "author": "Andy217Ace"}


def test_board_fresh_not_stale(client):
    ingest(client, datetime.now(BUC))
    b = client.get("/api/board").json()
    assert b["stale"] is False and 0 <= b["age_s"] < 60


def test_health_false_without_data(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "age_s": None}


def test_health_ok_with_fresh_data_and_false_when_old(client):
    ingest(client, datetime.now(BUC) - timedelta(seconds=10))
    h = client.get("/api/health").json()
    assert h["ok"] is True and 5 < h["age_s"] < 60
    ingest(client, datetime.now(BUC) - timedelta(seconds=400))  # older ok run, newer id
    h = client.get("/api/health").json()
    assert h["ok"] is False and h["age_s"] > 180


# -- history / train ------------------------------------------------------

def test_history_by_station(client):
    ingest(client)
    r = client.get("/api/history", params={"date": "2026-10-20", "station": "brasov"})
    assert r.status_code == 200
    j = r.json()
    assert j["date"] == "2026-10-20"
    assert sorted(x["train_no"] for x in j["services"]) == [1636, 1741]


def test_history_filters_board_train_and_time(client):
    ingest(client)
    q = {"date": "2026-10-20", "board": "departure", "from": "12:35", "to": "12:59"}
    assert [x["train_no"] for x in client.get("/api/history", params=q).json()["services"]] \
        == [1741]
    q = {"date": "2026-10-20", "train": "3001"}
    assert [x["train_no"] for x in client.get("/api/history", params=q).json()["services"]] \
        == [3001]


def test_history_defaults_to_today(client):
    ingest(client)
    assert len(client.get("/api/history").json()["services"]) == 4


@pytest.mark.parametrize("q", [
    {"date": "nu-e-data"}, {"date": "2026-13-01"}, {"train": "abc"}, {"board": "sosire"},
    {"from": "25:00"}, {"to": "1230"}, {"from": "12:3"}, {"station": "x" * 200},
])
def test_history_rejects_bad_params(client, q):
    r = client.get("/api/history", params=q)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str) and r.json()["detail"]


def test_train_events(client):
    ingest(client)
    r = client.get("/api/train/1636", params={"date": "2026-10-20"})
    assert r.status_code == 200
    j = r.json()
    assert j["train"] == 1636 and j["date"] == "2026-10-20"
    assert [e["kind"] for e in j["events"]] == ["appeared"]


def test_train_rejects_non_int_and_bad_date(client):
    assert client.get("/api/train/abc").status_code == 422
    assert client.get("/api/train/1636", params={"date": "ieri"}).status_code == 422


# -- push / follow --------------------------------------------------------

def test_follow_unfollow_roundtrip(client):
    assert client.post("/api/push/subscribe", json=SUB).status_code == 200
    r = client.post("/api/follow", json={"endpoint": EP, "train": 1636, "date": "2026-10-20"})
    assert r.status_code == 200, r.text
    assert client.post("/api/follow",
                       json={"endpoint": EP, "train": 531, "date": "2026-10-21"}).status_code == 200
    r = client.get("/api/follows", params={"endpoint": EP})
    assert r.json()["follows"] == [{"train_no": 1636, "date": "2026-10-20", "on_board": False},
                                   {"train_no": 531, "date": "2026-10-21", "on_board": False}]
    r = client.request("DELETE", "/api/follow",
                       json={"endpoint": EP, "train": 1636, "date": "2026-10-20"})
    assert r.status_code == 200
    assert client.get("/api/follows", params={"endpoint": EP}).json()["follows"] == \
        [{"train_no": 531, "date": "2026-10-21", "on_board": False}]
    assert client.post("/api/push/unsubscribe", json={"endpoint": EP}).status_code == 200
    assert client.get("/api/follows", params={"endpoint": EP}).json()["follows"] == []


def test_follow_past_date_rejected(client):
    client.post("/api/push/subscribe", json=SUB)
    r = client.post("/api/follow", json={"endpoint": EP, "train": 1636, "date": "2026-10-19"})
    assert r.status_code == 422
    assert "dat" in r.json()["detail"].lower()


def test_follow_unknown_subscription_rejected(client):
    r = client.post("/api/follow", json={"endpoint": EP, "train": 1636, "date": "2026-10-20"})
    assert r.status_code == 422


@pytest.mark.parametrize("body", [
    {"endpoint": EP, "train": "x", "date": "2026-10-20"},
    {"endpoint": EP, "train": True, "date": "2026-10-20"},
    {"endpoint": EP, "train": 1636, "date": "20.10.2026"},
    {"endpoint": EP, "train": 1636},
    [1, 2],
])
def test_follow_bad_body(client, body):
    client.post("/api/push/subscribe", json=SUB)
    assert client.post("/api/follow", json=body).status_code == 422


def test_invalid_json_rejected(client):
    r = client.post("/api/push/subscribe", content=b"{nu e json",
                    headers={"content-type": "application/json"})
    assert r.status_code == 422


def test_oversized_body_413(client):
    big = dict(SUB, pad="x" * 5000)
    assert client.post("/api/push/subscribe", json=big).status_code == 413


@pytest.mark.parametrize("ep", [
    "https://127.1/x", "https://0x7f.1/x", "https://0x7f000001/x", "https://2130706433/x",
    "http://push.example.com/x", "ftp://push.example.com/x", "https://localhost/x",
    "https://10.0.0.1/x", "https://[::1]/x", "javascript:alert(1)", "",
])
def test_bad_endpoint_rejected(client, ep):
    r = client.post("/api/push/subscribe", json={"endpoint": ep, "keys": SUB["keys"]})
    assert r.status_code == 422
    assert client.get("/api/follows", params={"endpoint": ep}).status_code == 422


def test_push_key(client, monkeypatch):
    assert client.get("/api/push/key").status_code == 404
    app = create_app(settings(vapid_public_key="BPUBKEY"), start_poller=False)
    with TestClient(app) as c:
        assert c.get("/api/push/key").json() == {"key": "BPUBKEY"}


# -- static / headers -----------------------------------------------------

def test_security_headers_and_static(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Andy217Ace" in r.text
    for resp in (r, client.get("/api/health")):
        h = resp.headers
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer"
        assert h["x-frame-options"] == "DENY"
        csp = h["content-security-policy"]
        assert "default-src 'self'" in csp and "script-src 'self'" in csp
        assert "https://fonts.googleapis.com" in csp and "https://fonts.gstatic.com" in csp
        assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
    assert "access-control-allow-origin" not in r.headers


def test_main_import_does_not_create_app(monkeypatch):
    import importlib

    import app.main as m
    calls = []
    monkeypatch.setattr("app.api.create_app", lambda *a, **k: calls.append(1))
    importlib.reload(m)
    assert calls == []


# -- lifespan / poller wiring ---------------------------------------------

def test_lifespan_starts_and_stops_poller(monkeypatch):
    started, stopped = threading.Event(), threading.Event()

    async def fake_run_poller(settings, on_rows, client, stop, **kw):
        started.set()
        await stop.wait()
        stopped.set()

    monkeypatch.setattr("app.poller.run_poller", fake_run_poller)
    app = create_app(settings(), start_poller=True)
    with TestClient(app) as c:
        assert started.wait(2)
        assert c.get("/api/health").status_code == 200
    assert stopped.is_set()


def test_poller_gets_last_image_path_from_settings(monkeypatch):
    seen = {}
    got = threading.Event()

    async def fake_run_poller(settings, on_rows, client, stop, **kw):
        seen.update(kw)
        got.set()
        await stop.wait()

    monkeypatch.setattr("app.poller.run_poller", fake_run_poller)
    app = create_app(settings(last_image_path="/srv/x/last.jpg"), start_poller=True)
    with TestClient(app):
        assert got.wait(2)
    assert seen.get("last_image_path") == "/srv/x/last.jpg"


def test_poller_crash_is_logged_and_restarted(monkeypatch, caplog):
    calls = []
    restarted = threading.Event()

    async def flaky(settings, on_rows, client, stop, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        restarted.set()
        await stop.wait()

    monkeypatch.setattr("app.poller.run_poller", flaky)
    caplog.set_level(logging.ERROR)
    app = create_app(settings(), start_poller=True)
    with TestClient(app) as c:
        assert restarted.wait(2)
        assert c.get("/api/health").status_code == 200  # web server still up
    assert len(calls) == 2
    assert any("boom" in (r.exc_text or "") or "poller" in r.getMessage().lower()
               for r in caplog.records)


def test_on_rows_ingests_and_schedules_notifier_without_waiting(monkeypatch):
    handled, released, done = threading.Event(), None, threading.Event()
    result = {}

    class SlowNotifier:
        def __init__(self, store, send, **kw):
            self.store = store

        async def handle(self, events, today):
            result["events"] = events
            result["today"] = today
            handled.set()
            await asyncio.sleep(30)  # slow push endpoint

    async def fake_run_poller(settings, on_rows, client, stop, **kw):
        t = time.monotonic()
        await on_rows(rows(), T0.timestamp())
        result["elapsed"] = time.monotonic() - t
        done.set()
        await stop.wait()

    monkeypatch.setattr("app.api.Notifier", SlowNotifier)
    monkeypatch.setattr("app.poller.run_poller", fake_run_poller)
    app = create_app(settings(), start_poller=True)
    t0 = time.monotonic()
    with TestClient(app) as c:
        assert done.wait(2) and handled.wait(2)
        assert result["elapsed"] < 1.0
        assert len(result["events"]) == 4 and {e.kind for e in result["events"]} == {"appeared"}
        assert result["today"] == DAY
        assert len(c.get("/api/board").json()["arrivals"]) == 2
    assert time.monotonic() - t0 < 10  # shutdown cancelled the slow notify task


# -- fix round 1 ----------------------------------------------------------

@pytest.mark.parametrize("ep", [
    "https://fcm.googleapis.com.nip.io/x", "https://127.0.0.1.nip.io/x",
    "https://fcm.googleapis.com:8443/fcm/send/x", "https://fcm.googleapis.com:80/x",
    "https://user:pw@fcm.googleapis.com/x", "https://user@fcm.googleapis.com/x",
    "https://fcm.googleapis.com./x", "https://evil.com/fcm.googleapis.com",
    "https://googleapis.com/x", "https://push.services.mozilla.com/x",
    "https://xnotify.windows.com/x", "https://push.example.com/sub/abc",
    "https://fcm.googleapis.com\@evil.com/x", "https://fcm.googleapis.com:abc/x",
])
def test_endpoint_allowlist_rejects(client, ep):
    r = client.post("/api/push/subscribe", json={"endpoint": ep, "keys": SUB["keys"]})
    assert r.status_code == 422
    assert r.json()["detail"] == "Endpoint de notificare invalid."


@pytest.mark.parametrize("ep", [
    "https://fcm.googleapis.com/fcm/send/abc",
    "https://FCM.GoogleAPIs.com/fcm/send/abc",
    "https://fcm.googleapis.com:443/fcm/send/abc",
    "https://updates.push.services.mozilla.com/wpush/v2/abc",
    "https://autopush.prod.push.services.mozilla.com/wpush/v2/abc",
    "https://wns2-db5p.notify.windows.com/w/?token=x",
    "https://web.push.apple.com/QX", "https://api.push.apple.com/3/x",
])
def test_endpoint_allowlist_accepts(client, ep):
    r = client.post("/api/push/subscribe", json={"endpoint": ep, "keys": SUB["keys"]})
    assert r.status_code == 200, r.text


def test_api_and_store_share_endpoint_check():
    import app.api as api_mod
    import app.store as store_mod
    from app.endpoints import check_push_endpoint
    assert store_mod.check_push_endpoint is check_push_endpoint
    assert not hasattr(store_mod, "_check_endpoint")
    assert "_check_endpoint" not in vars(api_mod)


def test_history_from_after_to_rejected(client):
    r = client.get("/api/history", params={"from": "13:00", "to": "12:00"})
    assert r.status_code == 422
    assert "după" in r.json()["detail"]
    assert client.get("/api/history", params={"from": "12:00", "to": "12:00"}).status_code == 200


def test_create_app_without_web_dir(monkeypatch, tmp_path):
    missing = tmp_path / "nu-exista"
    monkeypatch.setattr("app.api.WEB_DIR", missing)
    app = create_app(settings(), start_poller=False)
    assert not missing.exists()
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/").status_code == 404


def test_unknown_api_path_is_romanian_404(client):
    for path in ("/api/nimic", "/api/push/altceva", "/api/"):
        r = client.get(path)
        assert r.status_code == 404
        assert r.json() == {"detail": "Nu există."}
    assert client.post("/api/nimic", json={}).status_code == 404
    assert client.post("/api/board").status_code == 405
    assert client.put("/api/follow", json={}).status_code == 405


def test_history_caps_at_500_rows_with_truncated_header(client):
    many = [Row("arrival" if i % 2 else "departure", "R", 2000 + i, "BRASOV", "CFR",
                "%02d:%02d" % (i // 60 % 24, i % 60), 0, None) for i in range(520)]
    client.app.state.store.ingest(many, T0)
    r = client.get("/api/history", params={"date": "2026-10-20"})
    assert r.status_code == 200
    assert isinstance(r.json()["services"], list) and len(r.json()["services"]) == 500
    assert r.headers.get("x-truncated") == "1"
    # under the cap: no header
    r2 = client.get("/api/history", params={"date": "2026-10-20", "board": "arrival",
                                            "to": "00:10"})
    assert "x-truncated" not in r2.headers


def test_poller_gets_known_stations_from_store(monkeypatch):
    seen = {}
    got = threading.Event()

    async def fake_run_poller(settings, on_rows, client, stop, **kw):
        seen.update(kw)
        got.set()
        await stop.wait()

    monkeypatch.setattr("app.poller.run_poller", fake_run_poller)
    app = create_app(settings(), start_poller=True)
    with TestClient(app):
        assert got.wait(2)
        assert seen["known_stations"]() == set()


def test_board_rows_carry_delay_read(client):
    from dataclasses import replace
    store = client.app.state.store
    store.ingest(rows(), T0)
    unread = rows()
    unread[0] = replace(unread[0], delay_min=0, delay_read=False)
    store.ingest(unread, T0 + timedelta(minutes=1))
    b = client.get("/api/board").json()
    flags = [r["delay_read"] for r in b["arrivals"] + b["departures"]]
    assert flags.count(False) == 1 and all(isinstance(f, bool) for f in flags)
