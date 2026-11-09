# © 2026 Andy217Ace
"""GET /api/admin/security: citește snapshot.json scris de exportatorul root
(scripts/security_snapshot.py), protejat ca restul administrării; nimic în API-urile publice."""
import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import admin, security_status
from app.api import create_app
from tests.test_admin_tools import AUTH, TOKEN, settings

ROOT = Path(__file__).resolve().parent.parent


def snapshot(now: float, **over) -> dict:
    s = {
        "schema": 1, "generated_ts": now - 60, "generated_at": "2026-11-09T17:59:00+00:00",
        "errors": [], "probe_rule": "filter", "duration_ms": 351, "ips_truncated": False,
        "fail2ban": {"available": True, "log_available": True,
                     "jails": [{"name": "nginx-tabela-probes", "banned_now": 1},
                               {"name": "sshd", "banned_now": 0}]},
        "totals": {"banned_now": 1, "bans_24h": 2, "bans_7d": 5, "probes_24h": 554,
                   "probe_ips_24h": 26, "requests_24h": 2052, "probes_7d": 2637,
                   "requests_7d": 26616},
        "banned": [{"ip": "195.178.110.159", "jail": "nginx-tabela-probes",
                    "banned_at": "2026-11-09T17:10:14+00:00",
                    "expires_at": "2026-11-10T17:10:14+00:00", "permanent": False,
                    "bancount": 1}],
        "history": [{"at": "2026-11-09T17:10:15+00:00", "event": "ban",
                     "jail": "nginx-tabela-probes", "ip": "195.178.110.159"}],
        "ips": {"195.178.110.159": {
            "24h": {"requests": 4, "probes": 3, "first_seen": "2026-11-09T17:10:13+00:00",
                    "last_seen": "2026-11-09T17:10:14+00:00",
                    "paths": [{"path": "/.env", "count": 2}]},
            "7d": {"requests": 5, "probes": 4, "first_seen": "2026-11-06T09:00:00+00:00",
                   "last_seen": "2026-11-09T17:10:14+00:00",
                   "paths": [{"path": "/.env", "count": 2}]}}},
        "top": [{"ip": "195.178.110.159", "probes_24h": 3, "probes_7d": 4, "requests_7d": 5,
                 "last_seen": "2026-11-09T17:10:14+00:00", "banned": True}],
        "access_log": {"available": True, "files": 8, "lines": 29822, "parse_errors": 0,
                       "truncated": False},
    }
    s.update(over)
    return s


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.delenv("ADMIN_TOKEN_STRICT", raising=False)
    monkeypatch.setenv("CAPTURE_DIR", str(tmp_path / "captures"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setattr(admin, "FAIL_DELAY_S", 0.0)
    admin.reset_failures()
    security_status.clear_cache()
    yield
    admin.reset_failures()


@pytest.fixture
def client(tmp_path):
    app = create_app(settings(db_path=str(tmp_path / "t.db")), start_poller=False)
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def write(tmp_path, data, mtime=None):
    d = tmp_path / "security"
    d.mkdir(exist_ok=True)
    p = d / "snapshot.json"
    p.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


# -- autentificare și izolare --------------------------------------------------------------

def test_needs_admin_session(client, tmp_path):
    write(tmp_path, snapshot(time.time()))
    r = client.get("/api/admin/security")
    assert r.status_code == 401
    assert "195.178" not in r.text


def test_wrong_bearer_is_rejected(client, tmp_path):
    write(tmp_path, snapshot(time.time()))
    r = client.get("/api/admin/security", headers={"Authorization": "Bearer " + "x" * 30})
    assert r.status_code == 401


def test_disabled_admin_answers_503(client, tmp_path, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN")
    assert client.get("/api/admin/security", headers=AUTH).status_code == 503


def test_public_api_does_not_expose_security_data(client, tmp_path):
    write(tmp_path, snapshot(time.time()))
    for url in ("/api/board", "/api/health", "/api/version", "/openapi.json"):
        r = client.get(url)
        assert "195.178.110.159" not in r.text and "fail2ban" not in r.text.lower(), url


# -- conținut ------------------------------------------------------------------------------

def test_returns_snapshot_with_age(client, tmp_path):
    now = time.time()
    write(tmp_path, snapshot(now))
    r = client.get("/api/admin/security", headers=AUTH)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "private, no-store"
    d = r.json()
    assert d["available"] is True and d["stale"] is False
    assert 55 <= d["age_s"] <= 70
    assert d["totals"]["banned_now"] == 1 and d["banned"][0]["ip"] == "195.178.110.159"
    assert d["ips"]["195.178.110.159"]["24h"]["paths"] == [{"path": "/.env", "count": 2}]
    assert d["generated_at"] == "2026-11-09T17:59:00+00:00" and "now" in d


def test_missing_snapshot(client):
    d = client.get("/api/admin/security", headers=AUTH).json()
    assert d == {"available": False, "reason": "missing", "now": d["now"]}


@pytest.mark.parametrize("raw", ["{not json", "[]", json.dumps({"schema": 99}), "null"])
def test_invalid_snapshot(client, tmp_path, raw):
    write(tmp_path, raw)
    d = client.get("/api/admin/security", headers=AUTH).json()
    assert d["available"] is False and d["reason"] == "invalid"


def test_stale_snapshot_reports_age(client, tmp_path):
    now = time.time()
    write(tmp_path, snapshot(now, generated_ts=now - 3600))
    d = client.get("/api/admin/security", headers=AUTH).json()
    assert d["available"] is False and d["reason"] == "stale" and d["stale"] is True
    assert 3590 <= d["age_s"] <= 3700
    assert d["generated_at"] == "2026-11-09T17:59:00+00:00"
    assert "banned" not in d


# -- sanitizare (datele vin din trafic ostil) ----------------------------------------------

def test_sanitizes_hostile_and_oversized_values(tmp_path):
    now = 1_800_000_000.0
    evil = "<img src=x onerror=alert(1)>" + "A" * 1000
    s = snapshot(now)
    s["ips"]["195.178.110.159"]["24h"]["paths"] = [{"path": evil, "count": 3}] * 50
    s["banned"] = s["banned"] * 5000
    s["history"] = [{"at": "x", "event": "<b>", "jail": "j", "ip": "1.1.1.1"}] * 1000
    s["totals"]["probes_24h"] = "lots"
    s["totals"]["bans_7d"] = True
    s["extra"] = {"secret": 1}
    p = write(tmp_path, s)
    d = security_status.read_snapshot(p, now)
    w = d["ips"]["195.178.110.159"]["24h"]
    assert len(w["paths"]) == security_status.TOP_PATHS
    assert len(w["paths"][0]["path"]) == security_status.MAX_PATH_LEN
    assert w["paths"][0]["path"].startswith("<img")          # textul rămâne text (UI: textContent)
    assert len(d["banned"]) == security_status.MAX_BANNED
    assert len(d["history"]) == security_status.MAX_HISTORY
    assert all(h["event"] is None for h in d["history"])      # eveniment necunoscut
    assert d["totals"]["probes_24h"] is None and d["totals"]["bans_7d"] is None
    assert "extra" not in d


def test_cache_follows_file_changes(tmp_path):
    now = time.time()
    p = write(tmp_path, snapshot(now))
    assert security_status.read_snapshot(p, now)["totals"]["banned_now"] == 1
    s = snapshot(now)
    s["totals"]["banned_now"] = 7
    p.write_text(json.dumps(s) + " " * 10, encoding="utf-8")   # altă dimensiune
    os.utime(p, (now + 5, now + 5))
    assert security_status.read_snapshot(p, now)["totals"]["banned_now"] == 7
