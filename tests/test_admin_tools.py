# © 2026 Andy217Ace
"""Pagina #admin: curățarea duplicatelor (GET/POST /api/admin/tools/dupes*) și starea
serverului (GET /api/admin/tools/server)."""
import hashlib
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import admin, admin_tools
from app.api import create_app
from app.config import Settings
from tests.test_merge_number_dups import _db

TOKEN = "t" * 20 + "-secret-admin-token"  # 40 caractere
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def settings(**kw):
    base = dict(db_path=":memory:", source_url="https://example.com/x",
                vapid_private_key="", vapid_public_key="", vapid_subject="mailto:a@b.c",
                tesseract_cmd="tesseract-does-not-exist", poller_restart_backoff=0.01)
    base.update(kw)
    return Settings(**base)


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.delenv("ADMIN_TOKEN_STRICT", raising=False)
    monkeypatch.setenv("CAPTURE_DIR", str(tmp_path / "captures"))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "bk"))
    monkeypatch.setattr(admin, "FAIL_DELAY_S", 0.0)
    admin.reset_failures()
    yield
    admin.reset_failures()


@pytest.fixture
def db(tmp_path):
    path, ids = _db(tmp_path)  # 92011 is a misread duplicate of RE 9209 (merged by apply)
    return path, ids


@pytest.fixture
def client(db):
    app = create_app(settings(db_path=str(db[0])), start_poller=False)
    with TestClient(app, base_url="https://testserver") as c:
        yield c


def login(c):
    assert c.post("/api/admin/login", json={"token": TOKEN}).status_code == 200


def csrf(c):
    return c.get("/api/admin/csrf").json()["token"]


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _numbers(path) -> set[int]:
    c = sqlite3.connect(path)
    try:
        return {r[0] for r in c.execute("SELECT train_no FROM services")}
    finally:
        c.close()


# -- autentificare --------------------------------------------------------------------

def test_tools_need_session_or_bearer_401(client):
    assert client.get("/api/admin/tools/server").status_code == 401
    assert client.get("/api/admin/tools/dupes").status_code == 401
    assert client.post("/api/admin/tools/dupes/apply",
                       json={"confirm": "APLICA"}).status_code == 401


def test_tools_disabled_without_token_503(client, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN")
    assert client.get("/api/admin/tools/server").status_code == 503


def test_apply_without_csrf_403(client):
    login(client)
    r = client.post("/api/admin/tools/dupes/apply", json={"confirm": "APLICA"})
    assert r.status_code == 403


# -- raport (read-only) ---------------------------------------------------------------

def test_dupes_report_is_read_only(client, db):
    path, _ = db
    before = _sha(path)
    r = client.get("/api/admin/tools/dupes", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"report", "generated_at"}
    assert body["generated_at"].endswith(("+02:00", "+03:00"))
    assert set(body["report"]) >= {"aliases", "merge", "listed_not_merged",
                                   "divergent_sched_listed_only"}
    assert body["report"]["merge"]["services_affected"] >= 1
    assert _sha(path) == before  # nimic scris


# -- aplicare / restaurare ---------------------------------------------------------------

def test_apply_wrong_confirm_422(client, db):
    login(client)
    r = client.post("/api/admin/tools/dupes/apply", headers={"X-CSRF-Token": csrf(client)},
                    json={"confirm": "da"})
    assert r.status_code == 422
    assert r.json()["detail"] == "Confirmarea lipsește."
    assert 92011 in _numbers(db[0])


def test_apply_then_restore_roundtrip(client, db, tmp_path):
    path, _ = db
    login(client)
    h = {"X-CSRF-Token": csrf(client)}
    r = client.post("/api/admin/tools/dupes/apply", headers=h,
                    json={"confirm": "APLICA", "min_age_min": 1})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["batch"].startswith("MD") and set(out) == {"batch", "summary", "backup"}
    assert (tmp_path / "bk" / out["backup"]).is_file()  # copia există înainte de scriere
    assert 92011 not in _numbers(path)
    r = client.post("/api/admin/tools/dupes/restore", headers=h,
                    json={"batch": out["batch"], "confirm": "RESTAUREAZA"})
    assert r.status_code == 200, r.text
    assert 92011 in _numbers(path)
    assert r.json()["backup"].endswith(".db")


def test_apply_bad_min_age_422(client):
    login(client)
    h = {"X-CSRF-Token": csrf(client)}
    for bad in (0, 1441, "60", True):
        r = client.post("/api/admin/tools/dupes/apply", headers=h,
                        json={"confirm": "APLICA", "min_age_min": bad})
        assert r.status_code == 422, bad


# -- starea serverului -------------------------------------------------------------------

def test_server_status_shape_and_null_without_proc(client, monkeypatch):
    monkeypatch.setattr(admin_tools.shutil, "which", lambda name: None)  # fără systemctl
    r = client.get("/api/admin/tools/server", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"generated_at", "load", "memory", "disk", "uptime_s", "process",
                         "services", "watchdog"}
    assert set(body["services"]) == {"tabela", "tabela-watchdog.timer", "nginx"}
    assert set(body["services"].values()) == {"unknown"}
    assert body["watchdog"] == {"failures": None, "last_restart": None}
    assert "/" not in str(body["services"]) and str(Path.home()) not in r.text
    if not Path("/proc/loadavg").exists():  # Windows / teste: câmpurile rămân null
        assert body["load"] is None and body["memory"] is None
        assert body["uptime_s"] is None and body["process"] == {"rss_mb": None}


def test_server_status_reads_watchdog_json(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    (tmp_path / "watchdog.json").write_text('{"failures": 2, "last_restart": 1700000000.0}')
    out = admin_tools.server_status(str(db))
    assert out["watchdog"]["failures"] == 2
    assert out["watchdog"]["last_restart"].startswith("2023-11-1")
    assert out["disk"]["total_gb"] > 0
