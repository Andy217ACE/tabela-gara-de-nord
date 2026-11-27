# © 2026 Andy217Ace
"""Vizitatori online (app.visitors, GET /api/admin/visitors) și POST /api/admin/push-test."""
import pytest
from fastapi.testclient import TestClient

from app import admin, visitors
from app.api import create_app
from tests.test_admin_tools import AUTH, TOKEN, settings

CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/130.0 Safari/537.36")
EP = "https://fcm.googleapis.com/fcm/send/abc123"


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.delenv("ADMIN_TOKEN_STRICT", raising=False)
    monkeypatch.setenv("CAPTURE_DIR", str(tmp_path / "captures"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setattr(admin, "FAIL_DELAY_S", 0.0)
    monkeypatch.setattr(admin, "_push_test_last", 0.0)
    admin.reset_failures()
    visitors.reset()
    yield
    visitors.reset()


def test_mask_ip():
    assert visitors.mask_ip("203.0.113.77") == "203.0.113.x"
    assert visitors.mask_ip("2001:db8:1234:5678::1") == "2001:db8:1234:x"


def test_parse_ua():
    assert visitors.parse_ua(CHROME) == "Chrome / Windows"
    assert visitors.parse_ua("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit Version/17 Safari/604") == "Safari / iOS"


@pytest.mark.parametrize("ua", ["", "curl/8.0", "Mozilla/5.0 (compatible; Googlebot/2.1)",
                                "python-requests/2.31", "Mozilla/5.0 HeadlessChrome/120",
                                "Mozilla/5.0 UptimeRobot/2.0", "Go-http-client/1.1"])
def test_bots_and_non_browsers_excluded(ua):
    visitors.record("203.0.113.1", ua, "/", 1000.0)
    assert visitors.online(1000.0) == []


def test_assets_ignored_and_counts():
    visitors.record("203.0.113.1", CHROME, "/app.js", 1000.0)
    visitors.record("203.0.113.1", CHROME, "/", 1000.0)
    visitors.record("203.0.113.1", CHROME, "/api/trains", 1010.0)
    (v,) = visitors.online(1020.0)
    assert (v["requests"], v["path"], v["first_seen"], v["last_seen"]) == (2, "/api/trains", 1000.0, 1010.0)
    assert v["ip"] == "203.0.113.x"


def test_five_minute_window():
    visitors.record("203.0.113.1", CHROME, "/", 1000.0)
    assert len(visitors.online(1000.0 + visitors.ONLINE_S)) == 1
    assert visitors.online(1000.0 + visitors.ONLINE_S + 1) == []


def test_cap_drops_oldest(monkeypatch):
    monkeypatch.setattr(visitors, "MAX_ENTRIES", 3)
    for i in range(5):
        visitors.record(f"198.51.100.{i}", CHROME, "/", 1000.0 + i)
    ips = [v["ip"] for v in visitors.online(1005.0)]
    assert ips == ["198.51.100.x"] * 3 and len(visitors._seen) == 3
    assert "198.51.100.0" not in visitors._seen and "198.51.100.4" in visitors._seen


@pytest.fixture
def client(tmp_path):
    app = create_app(settings(db_path=str(tmp_path / "t.db")), start_poller=False)
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def login(c):
    assert c.post("/api/admin/login", json={"token": TOKEN}).status_code == 200


def test_visitors_requires_admin(client):
    assert client.get("/api/admin/visitors").status_code == 401


def test_visitors_lists_browser_and_not_admin_polling(client):
    client.get("/api/health", headers={"User-Agent": CHROME})
    r = client.get("/api/admin/visitors", headers={**AUTH, "User-Agent": CHROME})
    assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store"
    vs = r.json()["visitors"]
    assert len(vs) == 1 and vs[0]["client"] == "Chrome / Windows"


def test_push_test_requires_admin_and_csrf(client):
    assert client.post("/api/admin/push-test", json={"endpoint": EP}).status_code == 401
    login(client)
    assert client.post("/api/admin/push-test", json={"endpoint": EP}).status_code == 403


def test_push_test_not_subscribed_does_not_send(client):
    login(client)
    sent = []

    async def fake(sub, data):
        sent.append(sub)

    client.app.state.notifier.send = fake
    tok = client.get("/api/admin/csrf").json()["token"]
    r = client.post("/api/admin/push-test", json={"endpoint": EP}, headers={"X-CSRF-Token": tok})
    assert r.status_code == 200 and r.json() == {"result": "not_subscribed"} and not sent


def test_push_test_sent_error_and_rate_limit(client, monkeypatch):
    login(client)
    client.app.state.store.subscribe(EP, "p" * 10, "a" * 10)
    client.app.state.settings = settings(db_path=":memory:", vapid_private_key="k", vapid_public_key="K")
    calls = []

    async def fake(sub, data):
        calls.append(sub.endpoint)
        if len(calls) == 2:
            raise RuntimeError("web push failed: HTTP 403")

    client.app.state.notifier.send = fake
    h = {"X-CSRF-Token": client.get("/api/admin/csrf").json()["token"]}
    assert client.post("/api/admin/push-test", json={"endpoint": EP}, headers=h).json() == {"result": "sent"}
    assert client.post("/api/admin/push-test", json={"endpoint": EP}, headers=h).status_code == 429
    monkeypatch.setattr(admin, "_push_test_last", 0.0)
    assert client.post("/api/admin/push-test", json={"endpoint": EP}, headers=h).json() == {
        "result": "error", "status": 403}


def test_push_test_not_configured(client):
    login(client)
    client.app.state.store.subscribe(EP, "p" * 10, "a" * 10)
    h = {"X-CSRF-Token": client.get("/api/admin/csrf").json()["token"]}
    r = client.post("/api/admin/push-test", json={"endpoint": EP}, headers=h)
    assert r.json() == {"result": "not_configured"}


def test_push_test_gone_removes_subscription(client):
    from app.notifier import SubscriptionGone
    login(client)
    client.app.state.store.subscribe(EP, "p" * 10, "a" * 10)
    client.app.state.settings = settings(db_path=":memory:", vapid_private_key="k", vapid_public_key="K")

    async def fake(sub, data):
        raise SubscriptionGone("HTTP 410")

    client.app.state.notifier.send = fake
    h = {"X-CSRF-Token": client.get("/api/admin/csrf").json()["token"]}
    assert client.post("/api/admin/push-test", json={"endpoint": EP}, headers=h).json() == {"result": "gone"}
    assert client.app.state.store.get_subscription(EP) is None


def test_push_test_403_is_key_mismatch_and_keeps_subscription(client, monkeypatch):
    from types import SimpleNamespace

    from app import notifier as notifier_mod
    login(client)
    client.app.state.store.subscribe(EP, "p" * 10, "a" * 10)
    st = settings(db_path=":memory:", vapid_private_key="k", vapid_public_key="K")
    client.app.state.settings = st

    def fake(**kw):
        raise notifier_mod.WebPushException("forbidden", response=SimpleNamespace(status_code=403))

    monkeypatch.setattr(notifier_mod, "webpush", fake)
    client.app.state.notifier.send = notifier_mod.make_webpush_sender(st)
    h = {"X-CSRF-Token": client.get("/api/admin/csrf").json()["token"]}
    r = client.post("/api/admin/push-test", json={"endpoint": EP}, headers=h)
    assert r.json() == {"result": "key_mismatch"}
    assert client.app.state.store.get_subscription(EP) is not None


def test_admin_paths_not_recorded(client):
    client.get("/api/admin/session", headers={"User-Agent": CHROME})
    assert visitors.online() == []
