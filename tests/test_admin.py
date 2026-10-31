# © 2026 Andy217Ace
"""Admin auth matrix + „Capturi OCR" API + public /api/trains."""
import hmac
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import admin, observations
from app.api import create_app
from app.config import Settings
from app.models import Row
from app.ocr.reader import read_board_debug
from tests.ocr_truth_images import capture

FIX = Path(__file__).parent / "fixtures"
BUC = ZoneInfo("Europe/Bucharest")
TOKEN = "t" * 20 + "-secret-admin-token"
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=BUC)


def settings(**kw):
    base = dict(db_path=":memory:", source_url="https://example.com/x",
                vapid_private_key="", vapid_public_key="", vapid_subject="mailto:a@b.c",
                tesseract_cmd="tesseract-does-not-exist", poller_restart_backoff=0.01)
    base.update(kw)
    return Settings(**base)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("CAPTURE_DIR", str(tmp_path / "captures"))
    monkeypatch.setattr(admin, "FAIL_DELAY_S", 0.0)
    admin.reset_failures()
    admin._tess_cache.update(at=None, value=None)
    yield
    admin.reset_failures()


@pytest.fixture
def client():
    app = create_app(settings(), start_poller=False)
    with TestClient(app, base_url="https://testserver") as c:
        yield c


AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(scope="module")
def board():
    data = capture(FIX / "board_1.jpg").read_bytes()
    rows, debug = read_board_debug(data)
    return data, rows, debug


def seed(c, board):
    data, rows, debug = board
    store = c.app.state.store
    store.ingest(rows, T0)
    return observations.record_capture(store, data, rows, debug, T0, duration_ms=900,
                                       capture_dir=c.app.state.capture_settings.dir)


ENDPOINTS = ["/api/admin/captures", "/api/admin/captures/1", "/api/admin/captures/1/image",
             "/api/admin/captures/1/overlay.png", "/api/admin/stats"]


# -- auth matrix ------------------------------------------------------------------

@pytest.mark.parametrize("path", ENDPOINTS)
def test_disabled_without_token_503(client, monkeypatch, path):
    monkeypatch.delenv("ADMIN_TOKEN")
    r = client.get(path, headers=AUTH)
    assert r.status_code == 503 and r.json()["detail"] == "Administrare dezactivată."


def test_session_endpoint_always_200(client, monkeypatch):
    r = client.get("/api/admin/session")
    assert r.status_code == 200 and r.json() == {"enabled": True, "authenticated": False}
    assert r.headers["cache-control"] == "private, no-store"
    monkeypatch.delenv("ADMIN_TOKEN")
    assert client.get("/api/admin/session").json() == {"enabled": False, "authenticated": False}


def test_short_token_counts_as_disabled(client, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "short")
    assert client.get("/api/admin/stats", headers={"Authorization": "Bearer short"}).status_code == 503
    assert client.post("/api/admin/login", json={"token": "short"}).status_code == 503


@pytest.mark.parametrize("path", ENDPOINTS)
def test_missing_credentials_401(client, path):
    r = client.get(path)
    assert r.status_code == 401
    assert "no-store" in r.headers["cache-control"]


@pytest.mark.parametrize("path", ENDPOINTS)
def test_wrong_token_401(client, path):
    assert client.get(path, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_right_token_200(client, board):
    seed(client, board)
    for path in ENDPOINTS:
        r = client.get(path, headers=AUTH)
        assert r.status_code == 200, path
        assert r.headers["cache-control"] == "private, no-store"


def test_compare_is_timing_safe(client, monkeypatch):
    calls = []
    real = hmac.compare_digest

    def spy(a, b):
        calls.append(1)
        return real(a, b)

    monkeypatch.setattr(admin.hmac, "compare_digest", spy)
    client.get("/api/admin/stats", headers=AUTH)
    client.post("/api/admin/login", json={"token": TOKEN})
    client.get("/api/admin/stats")  # cookie
    assert len(calls) >= 3


def test_login_sets_strict_cookie_and_logout_clears(client):
    r = client.post("/api/admin/login", json={"token": TOKEN})
    assert r.status_code == 200
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "secure" in sc and "samesite=strict" in sc
    assert "path=/api/admin" in sc and "max-age=43200" in sc
    assert TOKEN.lower() not in sc  # the token itself is never in the cookie
    assert client.get("/api/admin/session").json() == {"enabled": True, "authenticated": True}
    assert client.get("/api/admin/stats").status_code == 200  # cookie works
    out = client.post("/api/admin/logout")
    assert out.status_code == 200
    assert client.get("/api/admin/session").json() == {"enabled": True, "authenticated": False}
    assert client.get("/api/admin/stats").status_code == 401


def test_login_wrong_token_and_bad_body(client):
    assert client.post("/api/admin/login", json={"token": "wrong"}).status_code == 401
    assert client.post("/api/admin/login", content=b"{bad").status_code == 401
    assert client.post("/api/admin/login", content=b"x" * 5000).status_code == 413


def test_rate_limit_after_five_failures(client):
    for _ in range(5):
        assert client.post("/api/admin/login", json={"token": "wrong"}).status_code == 401
    r = client.post("/api/admin/login", json={"token": TOKEN})
    assert r.status_code == 429 and r.headers["retry-after"] == "60"
    assert client.get("/api/admin/stats", headers=AUTH).status_code == 429


def test_failure_delay_is_applied(client, monkeypatch):
    slept = []

    async def fake_sleep(d):
        slept.append(d)

    monkeypatch.setattr(admin, "FAIL_DELAY_S", 0.25)
    monkeypatch.setattr(admin.asyncio, "sleep", fake_sleep)
    client.post("/api/admin/login", json={"token": "wrong"})
    assert slept == [0.25]


def test_session_expiry_and_forgery():
    s = admin.make_session(TOKEN, now=1000)
    assert admin.check_session(TOKEN, s, now=1001)
    assert not admin.check_session(TOKEN, s, now=1000 + admin.SESSION_S + 1)
    assert not admin.check_session("other-token-0123456789", s, now=1001)
    exp, sig = s.split(".")
    assert not admin.check_session(TOKEN, f"{int(exp) + 999}.{sig}", now=1001)
    assert not admin.check_session(TOKEN, "garbage", now=1001)


def test_token_never_logged(client, caplog):
    client.post("/api/admin/login", json={"token": TOKEN + "x"})
    client.get("/api/admin/stats", headers={"Authorization": f"Bearer {TOKEN}y"})
    assert TOKEN not in caplog.text


# -- admin data ----------------------------------------------------------------------

def test_captures_list_and_detail(client, board):
    cid = seed(client, board)
    r = client.get("/api/admin/captures?limit=10", headers=AUTH).json()
    assert [c["id"] for c in r["captures"]] == [cid]
    c = r["captures"][0]
    assert c["ok"] and c["n_rows"] == 24 and c["duration_ms"] == 900 and len(c["hash8"]) == 8
    assert "path" not in c
    d = client.get(f"/api/admin/captures/{cid}", headers=AUTH).json()
    assert len(d["observations"]) >= 24
    o = d["observations"][0]
    assert {"raw", "norm", "conf", "bbox"} <= set(o["fields"]["station"])
    assert o["validation_state"] in observations.STATES
    for bad in ("0", "x", "-1", "99999999999999"):
        assert client.get(f"/api/admin/captures/{bad}", headers=AUTH).status_code in (404, 422)
    assert client.get("/api/admin/captures/999", headers=AUTH).status_code == 404
    assert client.get("/api/admin/captures?limit=0", headers=AUTH).status_code == 422
    assert client.get("/api/admin/captures?before=abc", headers=AUTH).status_code == 422


def test_image_is_original_and_private(client, board):
    cid = seed(client, board)
    r = client.get(f"/api/admin/captures/{cid}/image", headers=AUTH)
    assert r.content == board[0] and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "private, no-store"


def test_overlay_png_size(client, board):
    cid = seed(client, board)
    r = client.get(f"/api/admin/captures/{cid}/overlay.png", headers=AUTH)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
    orig = cv2.imdecode(np.frombuffer(board[0], np.uint8), cv2.IMREAD_COLOR)
    assert img.shape == orig.shape


def test_image_gone_after_retention_404(client, board):
    cid = seed(client, board)
    client.app.state.store._conn.execute("UPDATE captures SET path=NULL")
    assert client.get(f"/api/admin/captures/{cid}/image", headers=AUTH).status_code == 404
    assert client.get(f"/api/admin/captures/{cid}/overlay.png", headers=AUTH).status_code == 404
    assert client.get(f"/api/admin/captures/{cid}", headers=AUTH).status_code == 200


def test_stats_shape(client, board):
    seed(client, board)
    s = client.get("/api/admin/stats", headers=AUTH).json()
    assert {"last_capture_attempt", "last_capture_ok", "last_ocr_run", "duration_ms",
            "errors_24h", "rows_24h", "rows_with_errors_24h", "db_bytes", "images",
            "live_age_s", "tesseract", "capture", "source"} <= set(s)
    assert s["duration_ms"]["n"] == 1 and s["duration_ms"]["avg"] == 900
    assert s["tesseract"] == {"available": False, "version": None}
    assert s["images"]["count"] == 1 and s["capture"]["retention_days"] == 7
    assert {"last_image_age_s", "available", "poller_enabled"} <= set(s["source"])


def test_tesseract_check_cached(monkeypatch):
    calls = []

    def fake_run(*a, **k):
        calls.append(a)

        class P:
            returncode, stdout, stderr = 0, "tesseract 5.5.0\nleptonica", ""
        return P()

    monkeypatch.setattr(admin.subprocess, "run", fake_run)
    assert admin.tesseract_status("tesseract") == {"available": True,
                                                   "version": "tesseract 5.5.0"}
    admin.tesseract_status("tesseract")
    assert len(calls) == 1


# -- public catalog --------------------------------------------------------------------

def test_public_trains(client, board):
    seed(client, board)
    r = client.get("/api/trains")
    assert r.status_code == 200
    body = r.json()
    assert body["n"] == len(body["trains"]) > 0
    t = body["trains"][0]
    assert {"train_no", "first_seen", "last_seen", "operators", "routes", "journeys",
            "observations"} <= set(t)
    assert isinstance(t["journeys"], int) and isinstance(t["observations"], int)
    no = t["train_no"]
    d = client.get(f"/api/trains/{no}").json()
    assert d["train_no"] == no and d["journeys"] == len(d["journeys_list"])
    assert "raw_text" not in str(d) and "image" not in str(d)
    q = client.get(f"/api/trains?query={str(no)[:2]}&limit=5").json()
    assert 0 < q["n"] <= 5 and all(str(x["train_no"]).startswith(str(no)[:2])
                                   for x in q["trains"])


@pytest.mark.parametrize("url", ["/api/trains?limit=0", "/api/trains?limit=999",
                                 "/api/trains?limit=x", "/api/trains?query=" + "a" * 41,
                                 "/api/trains/abc", "/api/trains/0", "/api/trains/1234567"])
def test_public_trains_validation(client, url):
    assert client.get(url).status_code == 422


def test_public_train_unknown_404(client):
    assert client.get("/api/trains/4242").status_code == 404


def test_admin_unknown_path_still_404_json(client):
    assert client.get("/api/admin/nothing", headers=AUTH).status_code in (401, 404)


def test_operator_chosen_13_char_key_is_accepted(monkeypatch):
    from app import admin as adm
    monkeypatch.setenv("ADMIN_TOKEN", "x" * 13)
    assert adm.admin_token() == "x" * 13
    monkeypatch.setenv("ADMIN_TOKEN", "x" * 11)
    assert adm.admin_token() is None


def test_global_failure_cap_blocks_ip_rotation():
    from app import admin as adm
    adm.reset_failures()
    now = 1000.0
    for i in range(adm.GLOBAL_FAIL_LIMIT):
        adm._failures.setdefault(f"10.0.0.{i}", __import__("collections").deque()).append(now)
        adm._global_failures.append(now)
    assert adm._limited("192.0.2.1", now + 1)          # a fresh IP is limited too
    assert not adm._limited("192.0.2.1", now + adm.FAIL_WINDOW_S + 1)  # window expires
    adm.reset_failures()
