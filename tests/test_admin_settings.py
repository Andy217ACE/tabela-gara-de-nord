# © 2026 Andy217Ace
"""Val 4c: cheie strictă opțională, rotația cheii, pagina Setări (GET/POST /api/admin/settings)."""
import pytest
from fastapi.testclient import TestClient

from app import admin, admin_settings, captures, observations
from app.api import create_app
from app.config import Settings

TOKEN = "t" * 20 + "-secret-admin-token"  # 40 caractere
OLD_TOKEN = "o" * 30 + "-vechea-cheie"  # rotație: aceasta devine cheia veche
SHORT = "s" * 13  # peste 12 (mod normal), sub 24 (mod strict)


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
    monkeypatch.setattr(admin, "FAIL_DELAY_S", 0.0)
    admin.reset_failures()
    yield
    admin.reset_failures()


@pytest.fixture
def client():
    app = create_app(settings(), start_poller=False)
    with TestClient(app, base_url="https://testserver") as c:
        yield c


AUTH = {"Authorization": f"Bearer {TOKEN}"}


def login(c, token=TOKEN):
    r = c.post("/api/admin/login", json={"token": token})
    assert r.status_code == 200
    return r


def csrf(c):
    return c.get("/api/admin/csrf").json()["token"]


# -- cheie strictă ----------------------------------------------------------------

def test_strict_off_by_default_accepts_12_chars(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", SHORT)
    assert admin.admin_token() == SHORT
    admin.check_startup()  # nu aruncă


def test_strict_on_rejects_short_key_at_startup_without_leaking_it(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN_STRICT", "1")
    monkeypatch.setenv("ADMIN_TOKEN", SHORT)
    assert admin.admin_token() is None  # admin dezactivat, nu acceptă cheia scurtă
    with pytest.raises(RuntimeError) as exc:
        admin.check_startup()
    assert "24" in str(exc.value)
    assert SHORT not in str(exc.value)


def test_strict_on_refuses_service_start(monkeypatch):
    from app import main
    monkeypatch.setenv("ADMIN_TOKEN_STRICT", "1")
    monkeypatch.setenv("ADMIN_TOKEN", SHORT)
    with pytest.raises(RuntimeError):
        main.create()


def test_strict_on_accepts_24_chars(monkeypatch):
    key = "k" * 24
    monkeypatch.setenv("ADMIN_TOKEN_STRICT", "1")
    monkeypatch.setenv("ADMIN_TOKEN", key)
    assert admin.admin_token() == key
    admin.check_startup()


def test_strict_on_without_key_only_disables_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN_STRICT", "1")
    monkeypatch.delenv("ADMIN_TOKEN")
    admin.check_startup()  # nu oprește site-ul public
    assert admin.admin_token() is None


# -- rotația cheii ----------------------------------------------------------------

def test_old_session_cookie_refused_after_rotation(client, monkeypatch):
    login(client)
    assert client.get("/api/admin/stats").status_code == 200
    monkeypatch.setenv("ADMIN_TOKEN", OLD_TOKEN)  # rotația din /etc/tabela.env + restart
    assert client.get("/api/admin/stats").status_code == 401


# -- pagina Setări ----------------------------------------------------------------

def test_get_settings_defaults_and_auth(client):
    assert client.get("/api/admin/settings").status_code == 401
    r = client.get("/api/admin/settings", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["capture_retention_days"]["value"] == 7
    assert body["capture_retention_days"]["min"] == 1
    assert body["capture_retention_days"]["max"] == 30
    assert "capture_min_free_mb" in body
    assert TOKEN not in r.text


def test_post_out_of_range_422_changes_nothing(client):
    for bad in (0, 31, -1, "7", True, 7.5, None):
        r = client.post("/api/admin/settings", headers=AUTH,
                        json={"capture_retention_days": bad})
        assert r.status_code == 422, bad
    r = client.post("/api/admin/settings", headers=AUTH,
                    json={"capture_retention_days": 14, "nu_exista": 1})
    assert r.status_code == 422
    assert client.get("/api/admin/settings", headers=AUTH).json()[
        "capture_retention_days"]["value"] == 7


def test_post_valid_persists_and_is_audited(client):
    r = client.post("/api/admin/settings", headers=AUTH,
                    json={"capture_retention_days": 14, "capture_min_free_mb": 4096})
    assert r.status_code == 200
    assert client.get("/api/admin/settings", headers=AUTH).json()[
        "capture_retention_days"]["value"] == 14
    store = client.app.state.store
    assert admin_settings.effective(store, "capture_retention_days", 7) == 14
    assert observations.min_free_bytes(store) == 4096 * 1024 * 1024
    rows = store._conn.execute(
        "SELECT action, actor, detail_json FROM correction_audit WHERE action='setting'"
    ).fetchall()
    assert len(rows) == 2
    joined = " ".join(r["detail_json"] for r in rows)
    assert "capture_retention_days" in joined and TOKEN not in joined


def test_post_without_csrf_refused_for_cookie_session(client):
    login(client)
    r = client.post("/api/admin/settings", json={"capture_retention_days": 14})
    assert r.status_code == 403
    assert client.get("/api/admin/settings").json()["capture_retention_days"]["value"] == 7
    r = client.post("/api/admin/settings", json={"capture_retention_days": 14},
                    headers={"X-CSRF-Token": csrf(client)})
    assert r.status_code == 200


def test_retention_loop_reads_current_setting(client):
    store = client.app.state.store
    cs = captures.CaptureSettings(True, "/x", 7)
    assert admin_settings.effective(store, "capture_retention_days", cs.retention_days) == 7
    client.post("/api/admin/settings", headers=AUTH, json={"capture_retention_days": 3})
    assert admin_settings.effective(store, "capture_retention_days", cs.retention_days) == 3


def test_effective_uses_env_without_row_and_falls_back_on_bad_row(client):
    store = client.app.state.store
    assert admin_settings.effective(store, "capture_retention_days", 0) == 0  # mediu, ca atare
    store._conn.execute("INSERT INTO settings(key,value,updated_at) VALUES(?,?,?)",
                        ("capture_retention_days", "999", "2026-10-31T00:00:00"))
    assert admin_settings.effective(store, "capture_retention_days", 7) == 7


def test_secret_absent_from_settings_page_and_repo_files():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for p in list((root / "app").glob("*.py")) + list((root / "web").glob("*.js")):
        assert TOKEN not in p.read_text(encoding="utf-8"), p.name


def test_setari_js_is_csp_safe_and_shows_no_key():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "web" / "setari.js").read_text(encoding="utf-8")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", ".style", "eval("):
        assert bad not in src, bad
    assert "ADMIN_TOKEN" not in src and "csrf" in src.lower()
