# © 2026 Andy217Ace
"""`fara_aeroport`: the Statistici routes leave the Airport trips out by default; train and
station pages keep them."""
import pytest
from fastapi.testclient import TestClient

from app import stats_compare, stats_overview
from app.api import create_app
from app.config import Settings
from app.store import Store
from tests.test_stats import add

AIR = "AEROPORT H COANDA"


@pytest.fixture
def client(tmp_path):
    stats_overview.clear_cache()
    stats_compare.clear_cache()
    db = tmp_path / "t.db"
    s = Store(str(db))
    s.migrate()
    s._conn.close()
    st = Settings(db_path=str(db), source_url="http://x", vapid_private_key="",
                  vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract",
                  poller_enabled=False, last_image_path=None, weather=None)
    app = create_app(st, start_poller=False)
    with TestClient(app, base_url="https://testserver") as c:
        st_ = app.state.store
        for i, d in enumerate([0, 2, 4, 10, 35, 1]):       # 4 / 6 on time (<= 5 min)
            add(st_, "arrival", 1621, 14 + i, "12:10", d)
        for i in range(6):                                  # 6 / 6 on time
            add(st_, "arrival", 7901, 14 + i, "09:00", 0, station=AIR)
        yield c


def arr(c, q=""):
    r = c.get("/api/stats?prag=5&min=1" + q)
    assert r.status_code == 200
    return r.json()["boards"]["arrival"]


def test_default_leaves_airport_out(client):
    a = arr(client)
    assert a["n"] == 6 and a["on_time_pct"] == pytest.approx(66.7)
    assert arr(client, "&fara_aeroport=1") == a
    ov = client.get("/api/stats/overview").json()
    assert ov["params"]["no_airport"] is True and ov["coverage"]["journeys"] == 6


def test_zero_includes_airport(client):
    a = arr(client, "&fara_aeroport=0")
    assert a["n"] == 12 and a["on_time_pct"] == pytest.approx(83.3)
    ov = client.get("/api/stats/overview?fara_aeroport=0").json()
    assert ov["params"]["no_airport"] is False and ov["coverage"]["journeys"] == 12


def test_other_statistici_routes(client):
    for path, key in (("/api/stats/dwell", "n"), ("/api/stats/platform-changes", None)):
        d0, d1 = client.get(path).json(), client.get(path + "?fara_aeroport=0").json()
        assert d0["params"]["no_airport"] is True and d1["params"]["no_airport"] is False
        if key:
            assert d0[key] == 6 and d1[key] == 12
    rk = client.get("/api/stats/rankings?min=1").json()
    assert AIR not in [s["station"] for s in rk["stations"]["most_delayed"]]
    for path in ("/api/stats/heatmap", "/api/stats/reliable", "/api/stats/changes", "/api/stats/seasons"):
        assert client.get(path).status_code == 200, path
        assert client.get(path + "?fara_aeroport=0").status_code == 200, path


def test_invalid_value(client):
    for path in ("/api/stats", "/api/stats/overview", "/api/stats/dwell", "/api/stats/heatmap",
                 "/api/trains/7901/journeys"):
        assert client.get(path + "?fara_aeroport=2").status_code == 422, path


def test_train_and_station_pages_keep_airport(client):
    t = client.get("/api/trains/7901/journeys")
    assert t.status_code == 200 and len(t.json()["journeys"]) == 6
    s = client.get("/api/stations/" + AIR)
    assert s.status_code == 200
    assert client.get("/api/journeys?station=" + AIR).json()["total"] == 6
