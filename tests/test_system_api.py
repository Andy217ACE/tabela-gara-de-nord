# © 2026 Andy217Ace
"""GET /api/system (public) and GET /api/admin/system (admin only) on a minimal app."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import system_api, system_status
from app.store import Store

TOKEN = "t" * 40


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.setattr(system_status, "_last_error", None)
    store = Store(str(tmp_path / "tabela.db"))
    store.migrate()
    app = FastAPI()
    app.include_router(system_api.router)
    app.include_router(system_api.admin_router)
    app.state.store = store
    app.state.settings = SimpleNamespace(db_path=str(tmp_path / "tabela.db"))
    with TestClient(app) as c:
        yield c
    store.close()


def test_public_system_is_200_and_minimal(client):
    r = client.get("/api/system")
    assert r.status_code == 200
    body = r.json()
    assert body["stare"] == "necunoscut"
    assert "ocr_window" not in body and "total_gb" not in body["disk"]
    assert "last_error_age_s" not in body["poller"]


def test_public_system_leaks_no_secret_or_path(client, tmp_path):
    text = client.get("/api/system").text
    assert TOKEN not in text
    assert str(tmp_path) not in text
    assert "Traceback" not in text


def test_admin_system_needs_the_admin_token(client):
    assert client.get("/api/admin/system").status_code == 401


def test_admin_system_with_token_has_details_and_no_paths(client, tmp_path):
    r = client.get("/api/admin/system", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    body = r.json()
    assert "ocr_window" in body and "total_gb" in body["disk"]
    assert str(tmp_path) not in json.dumps(body)
    assert TOKEN not in json.dumps(body)
