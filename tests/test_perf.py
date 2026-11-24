# © 2026 Andy217Ace
"""app.perf: percentile, bounded rolling windows, route templates (never raw paths) in the
middleware, and the „Sistem” payload fields (admin-only ones absent for the public)."""
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import perf, system_status
from app.api import create_app
from tests.test_api import settings


@pytest.fixture(autouse=True)
def clean():
    perf.reset()
    yield
    perf.reset()


def test_percentile_nearest_rank():
    v = list(range(1, 101))
    assert perf.percentile(v, .5) == 50
    assert perf.percentile(v, .95) == 95
    assert perf.percentile([7], .95) == 7
    assert perf.percentile([], .5) is None


def test_route_window_is_bounded_and_24h():
    for i in range(perf.MAX_SAMPLES + 500):
        perf.record_route("/api/board", float(i))
    assert len(perf._routes["/api/board"]) == perf.MAX_SAMPLES
    now = time.time()
    perf.record_route("/api/x", 999.0, now=now - perf.WINDOW_S - 1)  # too old: not counted
    perf.record_route("/api/x", 5.0, now=now)
    [x] = [r for r in perf.routes_summary(now=now) if r["route"] == "/api/x"]
    assert x == {"route": "/api/x", "n": 1, "p50_ms": 5.0, "p95_ms": 5.0}


def test_ocr_window_is_bounded_and_has_last():
    for i in range(perf.OCR_SAMPLES + 10):
        perf.record_ocr_cycle(float(i))
    s = perf.ocr_summary()
    assert s["n"] == perf.OCR_SAMPLES and s["last_ms"] == perf.OCR_SAMPLES + 9
    perf.reset()
    assert perf.ocr_summary() == {"n": 0, "p50_ms": None, "p95_ms": None, "last_ms": None}


def test_admin_routes_only_with_include_admin():
    perf.record_route("/api/admin/system", 1.0)
    perf.record_route("/api/board", 1.0)
    assert [r["route"] for r in perf.routes_summary()] == ["/api/board"]
    assert {r["route"] for r in perf.routes_summary(include_admin=True)} == {"/api/board", "/api/admin/system"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "t" * 40)
    monkeypatch.setattr(system_status, "_quality_cache", None)
    app = create_app(settings(db_path=str(tmp_path / "t.db")), start_poller=False)
    with TestClient(app) as c:
        yield c


def test_middleware_keys_by_route_template_not_raw_path(client):
    client.get("/api/trains/1636?secret=abc")
    client.get("/api/trains/531")
    client.get("/api/nope/123")  # the /api catch-all (404): kept under its template too
    assert set(perf._routes) == {"/api/trains/{no}", "/api/{rest:path}"}
    assert len(perf._routes["/api/trains/{no}"]) == 2


def test_public_system_has_perf_and_quality_but_no_versions(client):
    client.get("/api/board")
    client.get("/api/admin/system", headers={"Authorization": "Bearer " + "t" * 40})
    body = client.get("/api/system").json()
    assert "tesseract" not in body and "security_updates" not in body
    assert {"h24", "d7"} <= set(body["ocr_quality"])
    assert body["ocr_quality"]["h24"] == {"frames": 0, "frames_ok_pct": None, "rows": 0, "rows_ok_pct": None}
    routes = [r["route"] for r in body["perf"]["routes"]]
    assert "/api/board" in routes and not any(r.startswith("/api/admin") for r in routes)
    admin = client.get("/api/admin/system", headers={"Authorization": "Bearer " + "t" * 40}).json()
    assert "tesseract" in admin and "security_updates" in admin
    assert any(r["route"] == "/api/admin/system" for r in admin["perf"]["routes"])


def test_ocr_quality_counts_last_24h_and_7d(tmp_path):
    from app.store import Store
    store = Store(str(tmp_path / "q.db"))
    store.migrate()
    now = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
    iso = lambda d: (now - d).isoformat(timespec="seconds")  # noqa: E731
    for i, (age, ok) in enumerate(((timedelta(hours=1), 1), (timedelta(hours=2), 0),
                                   (timedelta(days=3), 1), (timedelta(days=9), 1))):
        store._conn.execute("INSERT INTO captures(captured_at, image_hash, ok) VALUES (?,?,?)",
                            (iso(age), f"h{i}", ok))
    system_status._quality_cache = None
    q = system_status.ocr_quality(store, now)
    system_status._quality_cache = None
    assert q["h24"]["frames"] == 2 and q["h24"]["frames_ok_pct"] == 50.0
    assert q["d7"]["frames"] == 3 and q["d7"]["frames_ok_pct"] == 66.7
    assert json.dumps(q)  # aggregates only, serialisable
    store.close()


def test_middleware_overhead_is_negligible():
    """record_route is the only per-request work the middleware adds: well under 50 µs."""
    n = 20000
    t0 = time.perf_counter()
    for i in range(n):
        perf.record_route("/api/board", 1.0)
    per_call_us = (time.perf_counter() - t0) / n * 1e6
    assert per_call_us < 50, per_call_us


def test_push_follow_routes_only_with_include_admin():
    for r in ("/api/push/subscribe", "/api/follow", "/api/follows", "/api/board"):
        perf.record_route(r, 1.0)
    assert [r["route"] for r in perf.routes_summary()] == ["/api/board"]
    assert len(perf.routes_summary(include_admin=True)) == 4
