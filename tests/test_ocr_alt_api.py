# © 2026 Andy217Ace
"""API admin a jurnalului alternativei OCR: auth, CSRF, validare, PNG."""
import json

import pytest
from fastapi.testclient import TestClient

from app import admin
from app.api import create_app
from app.config import Settings
from app.ocr import alt_journal as j
from tests.test_ocr_alt_journal import NOW, _id, _seed

TOKEN = "t" * 20 + "-secret-admin-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
B = "/api/admin/ocr-alt"


@pytest.fixture
def raw(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("CAPTURE_DIR", str(tmp_path / "captures"))
    monkeypatch.delenv("OCR_ALT_MODEL", raising=False)
    monkeypatch.delenv("OCR_ALT", raising=False)
    monkeypatch.delenv("OCR_ALT_SHADOW", raising=False)
    monkeypatch.setattr(admin, "FAIL_DELAY_S", 0.0)
    admin.reset_failures()
    st = Settings(db_path=":memory:", source_url="https://example.com/x", vapid_private_key="",
                  vapid_public_key="", vapid_subject="mailto:a@b.c",
                  tesseract_cmd="tesseract-does-not-exist", poller_restart_backoff=0.01)
    with TestClient(create_app(st, start_poller=False), base_url="https://testserver") as c:
        yield c
    admin.reset_failures()


@pytest.fixture
def client(raw):
    raw.headers.update(AUTH)
    return raw


def test_requires_admin(raw):
    for m, p in (("get", ""), ("get", f"/crop/{_id(1)}/no"), ("post", f"/{_id(1)}/verdict")):
        assert getattr(raw, m)(B + p).status_code == 401


def test_overview_shape(client, monkeypatch):
    _seed([(_id(n), NOW) for n in range(1, 4)], verdicts=False)
    (j.journal_dir() / "verdicts.json").write_text(json.dumps({_id(2): {"verdict": "correct"}}))
    monkeypatch.setenv("OCR_ALT", "1")
    d = client.get(B + "?limit=2").json()
    print(json.dumps(d, indent=1))
    assert d["state"] == {"enabled": True, "shadow": False, "model_path": None,
                          "model_loaded": False,
                          "since_start": {"frames": 0, "tried": 0, "recovered": 0}}
    assert d["totals"]["events"] == 3 and d["totals"]["precision"] == 1.0
    assert [e["id"] for e in d["events"]] == [_id(3), _id(2)] and d["next"] == _id(2)
    assert d["events"][1]["verdict"] == "correct" and d["events"][0]["verdict"] is None
    assert d["events"][0]["crops"] == {"no": f"{B}/crop/{_id(3)}/no"}
    d = client.get(B, params={"before": _id(2), "only": "unverified"}).json()
    assert [e["id"] for e in d["events"]] == [_id(1)] and d["next"] is None


@pytest.mark.parametrize("q", ["limit=0", "limit=x", "only=bad", "before=../x"])
def test_overview_rejects_bad_params(client, q):
    assert client.get(f"{B}?{q}").status_code == 422


def test_crop_png_and_404(client):
    _seed([(_id(1), NOW)])
    (j.journal_dir() / "crops" / f"{_id(1)}_no.png").write_bytes(b"\x89PNG\r\n\x1a\nxx")
    r = client.get(f"{B}/crop/{_id(1)}/no")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "private, max-age=86400"
    assert client.get(f"{B}/crop/{_id(1)}/time").status_code == 404
    assert client.get(f"{B}/crop/{_id(2)}/no").status_code == 404


@pytest.mark.parametrize("eid,col", [("..%2F..%2Fevents.jsonl", "no"), (_id(1), "..%2Fx"),
                                     ("20261123T120001-arrival-1%00", "no"), (_id(1), "no.png"),
                                     ("..", "no"), (_id(1), "station")])
def test_crop_traversal_rejected(client, eid, col):
    _seed([(_id(1), NOW)])
    assert client.get(f"{B}/crop/{eid}/{col}").status_code == 404


def test_verdict_flow(client):
    _seed([(_id(1), NOW)], verdicts=False)
    r = client.post(f"{B}/{_id(1)}/verdict", json={"verdict": "wrong"})
    assert r.status_code == 200 and r.json()["totals"]["wrong"] == 1
    assert client.get(B).json()["events"][0]["verdict"] == "wrong"
    r = client.post(f"{B}/{_id(1)}/verdict", json={"verdict": None})
    assert r.status_code == 200 and client.get(B).json()["events"][0]["verdict"] is None
    for bad in ({"verdict": "maybe"}, {}, {"verdict": "wrong", "x": 1}, [1], {"verdict": 1}):
        assert client.post(f"{B}/{_id(1)}/verdict", json=bad).status_code == 422
    assert client.post(f"{B}/{_id(1)}/verdict", content=b"nope").status_code == 422
    assert client.post(f"{B}/{_id(2)}/verdict", json={"verdict": "wrong"}).status_code == 404
    assert client.post(f"{B}/..%2Fx/verdict", json={"verdict": "wrong"}).status_code == 404


def test_verdict_needs_csrf_with_cookie_session(raw):
    _seed([(_id(1), NOW)], verdicts=False)
    assert raw.post("/api/admin/login", json={"token": TOKEN}).status_code == 200
    url = f"{B}/{_id(1)}/verdict"
    assert raw.post(url, json={"verdict": "wrong"}).status_code == 403
    csrf = raw.get("/api/admin/csrf").json()
    tok = csrf.get("token") or csrf.get("csrf")
    assert raw.post(url, json={"verdict": "wrong"},
                    headers={"X-CSRF-Token": tok}).status_code == 200
