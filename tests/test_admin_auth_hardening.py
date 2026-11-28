# © 2026 Andy217Ace
"""Per-IP admin login backoff (no global lock-out) + optional TOTP 2FA."""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app import admin, totp
from app.api import create_app
from app.config import Settings

TOKEN = "t" * 20 + "-secret-admin-token"
SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.delenv("ADMIN_TOTP_SECRET", raising=False)
    monkeypatch.setenv("CAPTURE_DIR", str(tmp_path / "captures"))
    monkeypatch.setattr(admin, "FAIL_DELAY_S", 0.0)
    monkeypatch.setattr(admin, "GLOBAL_SLOW_DELAY_S", 0.0)
    admin.reset_failures()
    yield
    admin.reset_failures()


@pytest.fixture
def app():
    s = Settings(db_path=":memory:", source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c",
                 tesseract_cmd="tesseract-does-not-exist", poller_restart_backoff=0.01)
    return create_app(s, start_poller=False)


def client_from(app, ip):
    return TestClient(app, base_url="https://testserver", client=(ip, 50000))


def fail(ip):
    asyncio.run(admin._fail(ip))


# -- rate limiter ------------------------------------------------------------------------

def test_attacker_ip_blocked_while_admin_ip_still_logs_in(app):
    with client_from(app, "203.0.113.9") as bad, client_from(app, "198.51.100.7") as good:
        for _ in range(admin.GLOBAL_FAIL_LIMIT + 10):  # also far past the global ceiling
            r = bad.post("/api/admin/login", json={"token": "wrong-guess"})
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
        assert bad.post("/api/admin/login", json={"token": TOKEN}).status_code == 429
        assert good.post("/api/admin/login", json={"token": TOKEN}).status_code == 200


def test_backoff_doubles_and_is_capped():
    now = time.monotonic()
    for _ in range(admin.FAIL_LIMIT - 1):
        fail("192.0.2.1")
    assert admin._blocked_for("192.0.2.1", now) == 0
    waits = []
    for _ in range(4):
        fail("192.0.2.1")
        waits.append(admin._blocked_for("192.0.2.1", time.monotonic()))
    for w, base in zip(waits, (60, 120, 240, 480)):
        assert base - 2 < w <= base
    for _ in range(20):
        fail("192.0.2.1")
    assert admin._blocked_for("192.0.2.1", time.monotonic()) <= admin.BLOCK_MAX_S
    # forgotten after the block plus FAIL_FORGET_S of quiet
    assert admin._blocked_for("192.0.2.1", time.monotonic() + admin.BLOCK_MAX_S
                              + admin.FAIL_FORGET_S + 1) == 0
    assert "192.0.2.1" not in admin._failures


def test_memory_is_capped(monkeypatch):
    monkeypatch.setattr(admin, "MAX_TRACKED_IPS", 50)
    for i in range(200):
        fail(f"10.0.{i // 256}.{i % 256}")
    assert len(admin._failures) <= 50
    assert "10.0.0.199" in admin._failures  # the newest are kept
    assert len(admin._global_failures) <= admin.GLOBAL_FAIL_LIMIT


def test_global_ceiling_only_slows(monkeypatch):
    slept = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(admin, "GLOBAL_SLOW_DELAY_S", 3.0)
    monkeypatch.setattr(admin.asyncio, "sleep", fake_sleep)
    for i in range(admin.GLOBAL_FAIL_LIMIT + 2):
        fail(f"10.1.0.{i}")
    assert slept[0] == 0.0 and slept[-1] == 3.0
    assert admin._blocked_for("192.0.2.200", time.monotonic()) == 0  # fresh IP never blocked


def test_success_resets_the_ip(app):
    with client_from(app, "198.51.100.8") as c:
        for _ in range(admin.FAIL_LIMIT - 1):
            assert c.post("/api/admin/login", json={"token": "nope"}).status_code == 401
        assert c.post("/api/admin/login", json={"token": TOKEN}).status_code == 200
        assert "198.51.100.8" not in admin._failures
        for _ in range(admin.FAIL_LIMIT - 1):  # a full fresh allowance again
            assert c.post("/api/admin/login", json={"token": "nope"}).status_code == 401


# -- TOTP ---------------------------------------------------------------------------------

RFC_KEY = b"12345678901234567890"


@pytest.mark.parametrize("t,code", [
    (59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
    (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")])
def test_rfc6238_sha1_vectors(t, code):
    assert totp.code_at(RFC_KEY, t // 30, digits=8) == code


def test_window_and_replay():
    key = totp.decode_secret(SECRET)
    now = 1_700_000_000
    t = now // 30
    for c in (t - 1, t, t + 1):
        assert totp.match(key, totp.code_at(key, c), now) == c
    assert totp.match(key, totp.code_at(key, t - 2), now) is None
    assert totp.match(key, totp.code_at(key, t + 2), now) is None
    assert totp.match(key, totp.code_at(key, t), now, after=t) is None  # already used
    assert totp.match(key, "12345", now) is None and totp.match(key, "abcdef", now) is None


def test_decode_secret():
    assert totp.decode_secret("jbsw y3dp ehpk 3pxp") == totp.decode_secret("JBSWY3DPEHPK3PXP")
    assert totp.decode_secret("not base32!") is None
    assert totp.decode_secret("JBSWY3DP") is None  # too short


def test_login_without_secret_needs_no_code(app):
    with client_from(app, "198.51.100.9") as c:
        assert c.get("/api/admin/session").json()["totp"] is False
        assert c.post("/api/admin/login", json={"token": TOKEN}).status_code == 200


def test_login_with_totp(app, monkeypatch):
    monkeypatch.setenv("ADMIN_TOTP_SECRET", SECRET)
    key = totp.decode_secret(SECRET)
    code = totp.code_at(key, int(time.time()) // 30)
    with client_from(app, "198.51.100.10") as c:
        assert c.get("/api/admin/session").json()["totp"] is True
        r = c.post("/api/admin/login", json={"token": TOKEN})
        assert r.status_code == 401 and r.json()["detail"] == "totp_required"
        assert c.post("/api/admin/login", json={"token": "wrong", "code": "000000"}).status_code == 401
        assert admin._totp_last[0] == -1  # a wrong key never burns a code
        assert c.post("/api/admin/login", json={"token": TOKEN, "code": "000000" if code != "000000"
                                                else "111111"}).status_code == 401
        assert c.post("/api/admin/login", json={"token": TOKEN, "code": code}).status_code == 200
        assert c.get("/api/admin/stats").status_code == 200
    with client_from(app, "198.51.100.11") as c2:  # replay from elsewhere
        assert c2.post("/api/admin/login", json={"token": TOKEN, "code": code}).status_code == 401


def test_totp_bearer_only_from_loopback(app, monkeypatch):
    monkeypatch.setenv("ADMIN_TOTP_SECRET", SECRET)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    with client_from(app, "127.0.0.1") as local, client_from(app, "203.0.113.20") as remote:
        assert local.get("/api/admin/stats", headers=auth).status_code == 200
        assert remote.get("/api/admin/stats", headers=auth).status_code == 401


def test_invalid_secret_disables_admin(app, monkeypatch):
    monkeypatch.setenv("ADMIN_TOTP_SECRET", "not base32!")
    with client_from(app, "198.51.100.12") as c:
        assert c.post("/api/admin/login", json={"token": TOKEN, "code": "123456"}).status_code == 503


def test_setup_script_secret_and_uri(capsys, monkeypatch):
    import importlib.util
    from pathlib import Path
    from urllib.parse import parse_qs, urlsplit
    spec = importlib.util.spec_from_file_location(
        "admin_totp_setup", Path(__file__).resolve().parent.parent / "scripts" / "admin_totp_setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    s = mod.new_secret()
    assert len(totp.decode_secret(s)) == 20
    u = urlsplit(mod.otpauth_uri(s, "admin"))
    assert u.scheme == "otpauth" and u.netloc == "totp" and parse_qs(u.query)["secret"] == [s]
    monkeypatch.setattr("sys.argv", ["admin_totp_setup.py"])
    mod.main()
    out = capsys.readouterr().out
    assert "ADMIN_TOTP_SECRET=" in out and "otpauth://totp/" in out


def test_session_invalidated_by_2fa_change(monkeypatch):
    other = "KRSXG5CTMVRXEZLUKRSXG5CTMVRXEZLU"
    old = admin.make_session(TOKEN)
    assert admin.check_session(TOKEN, old)  # no 2FA: unchanged behaviour
    monkeypatch.setenv("ADMIN_TOTP_SECRET", SECRET)
    assert not admin.check_session(TOKEN, old)  # 2FA turned on
    s1 = admin.make_session(TOKEN)
    assert admin.check_session(TOKEN, s1)  # a new session after the change works
    monkeypatch.setenv("ADMIN_TOTP_SECRET", other)
    assert not admin.check_session(TOKEN, s1)  # secret rotated
    s2 = admin.make_session(TOKEN)
    monkeypatch.delenv("ADMIN_TOTP_SECRET")
    assert not admin.check_session(TOKEN, s2)  # 2FA turned off
    assert admin.check_session(TOKEN, admin.make_session(TOKEN))
