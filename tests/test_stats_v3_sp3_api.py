# © 2026 Andy217Ace
"""Statistici v3 sp3: the real routes (/api/stats/changes, /api/stats/heatmap, /api/stats/reliable and
/api/stats/overview?compare=prev7). Skipped until the controller wires them
(docs/superpowers/plans/2026-11-17-sp3-integrare.md); then they become the endpoint tests of the
shape, the 10-journey threshold and the missing-data answer on the live app."""
import pytest
from fastapi.testclient import TestClient

from app import stats_compare, stats_overview as so
from app.api import create_app
from app.config import Settings
from app.store import Store
from tests.test_stats_overview import add


def _client(tmp_path, seed):
    s = Store(str(tmp_path / "t.db"))
    s.migrate()
    seed(s._conn)
    s._conn.commit()
    cfg = Settings(db_path=s.path, source_url="https://example.com/x", vapid_private_key="",
                   vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract",
                   poller_enabled=False, last_image_path=None)
    so.clear_cache()
    stats_compare.clear_cache()
    return s, TestClient(create_app(cfg, start_poller=False))


def _wired(c):
    return c.get("/api/stats/changes").status_code != 404


def _young(c):
    for d in (19, 20):
        add(c, "arrival", 1, d, "10:00", 3)


def test_young_base_answers_insufficient_on_every_new_route(tmp_path):
    s, client = _client(tmp_path, _young)
    with client as c:
        if not _wired(c):
            pytest.skip("rutele sp3 nu sunt încă legate în stats_api.py")
        for url in ("/api/stats/changes", "/api/stats/heatmap", "/api/stats/overview?compare=prev7"):
            r = c.get(url)
            assert r.status_code == 200, url
            d = r.json()
            assert d["status"] == "insufficient" and d["message_key"] == "stats.sp3.insufficient", url
    s.close()


def test_routes_shape_with_two_weeks_of_data(tmp_path):
    def seed(c):   # `add` writes October 2026 days: the routes use the real today, so only the shape is checked
        for d in range(7, 21):
            add(c, "arrival", 11, d, "10:00", 4)

    s, client = _client(tmp_path, seed)
    with client as c:
        if not _wired(c):
            pytest.skip("rutele sp3 nu sunt încă legate în stats_api.py")
        assert c.get("/api/stats/changes").json()["window"]["now"]
        h = c.get("/api/stats/heatmap?perioada=all").json()
        assert h["days"] == list(range(7)) and h["hours"] == list(range(24))
        assert c.get("/api/stats/reliable").json()["min_journeys"] == 10
        assert c.get("/api/stats/overview?compare=nimic").status_code == 422
    s.close()
