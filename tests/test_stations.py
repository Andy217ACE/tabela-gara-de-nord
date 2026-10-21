# © 2026 Andy217Ace
"""Station pages (Etapa D2)."""
import pytest
from fastapi.testclient import TestClient

from app import stations, stats
from app.api import create_app
from app.config import Settings
from app.store import Store
from tests.test_stats import add


def seed(s):
    for i, d in enumerate([0, 3, 10, 40, 2]):
        add(s, "arrival", 1621, 14 + i, "12:10", d, station="GALATI")
    add(s, "departure", 1622, 14, "15:00", 7, station="GALATI")
    add(s, "arrival", 1623, 14, "16:00", 0, station="GALATI", state="unknown")
    for i, d in enumerate([0, 0, 1, 0, 0]):
        add(s, "arrival", 1700 + i, 14, "09:%02d" % i, d, station="BRASOV")
    add(s, "arrival", 1800, 14, "10:00", 0, station="BRASOV TRIAJ")
    add(s, "arrival", 1801, 14, "10:05", 3, station="GALATZ", uncertain=1)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    seed(s)
    yield s
    s.close()


def test_canonical():
    assert stations.canonical(" Galați ") == "GALATI"
    assert stations.canonical("brasov triaj") == "BRASOV TRIAJ"
    assert stations.canonical("--") == ""


def test_list(store):
    items = {i["name"]: i for i in stations.list_stations(store)}
    assert items["GALATI"]["journeys"] == 7 and items["GALATI"]["arrivals"] == 6
    assert items["GALATI"]["departures"] == 1 and items["GALATI"]["delay_known"] == 6
    assert items["GALATZ"]["uncertain_only"] and not items["GALATI"]["uncertain_only"]
    assert [i["name"] for i in stations.list_stations(store, "brasov")] == ["BRASOV", "BRASOV TRIAJ"]


def test_detail_separates_boards_and_keeps_exact_name(store):
    d = stations.detail(store, "Galați", stats.Params(on_time=5, min_sample=5))
    assert d["name"] == "GALATI" and d["journeys"] == 7
    assert "București Nord" in d["note"] and "GALATI" in d["note"]
    a, dep = d["boards"]["arrival"], d["boards"]["departure"]
    assert a["stats"]["n"] == 5 and a["stats"]["sufficient"] and a["stats"]["on_time"] == 3
    assert dep["stats"]["n"] == 1 and dep["stats"]["on_time_pct"] is None
    assert a["quality"]["states"]["unknown"] == 1
    assert [t["train_no"] for t in a["trains"]] == [1621, 1623]
    # ranking among stations with >= 5 journeys with a known delay: GALATI then BRASOV
    assert a["rank"] == {"position": 1, "of": 2}
    assert dep["rank"]["position"] is None
    assert stations.detail(store, "BRASOV", stats.Params())["journeys"] == 5  # not TRIAJ
    assert stations.detail(store, "NOWHERE", stats.Params()) is None


def test_rank_stations(store):
    r = stations.rank_stations(stats.load(store, stats.Params(min_sample=5)),
                               stats.Params(min_sample=5))
    assert r["eligible"] == 2
    assert [e["station"] for e in r["most_delayed"]] == ["GALATI", "BRASOV"]
    assert [e["station"] for e in r["most_punctual"]] == ["BRASOV", "GALATI"]


def test_journeys_page(store):
    d = stations.journeys_page(store, "galati", stats.Params(), limit=3)
    assert d["n"] == 3 and d["next_before"] is not None
    d2 = stations.journeys_page(store, "galati", stats.Params(), limit=3, before=d["next_before"])
    assert d2["n"] == 3
    ids = [j["id"] for j in d["journeys"] + d2["journeys"]]
    assert ids == sorted(ids, reverse=True) and len(set(ids)) == 6


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "t.db"
    st = Settings(db_path=str(db), source_url="http://x", vapid_private_key="",
                  vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract",
                  poller_enabled=False, last_image_path=None, weather=None)
    app = create_app(st, start_poller=False)
    with TestClient(app, base_url="https://testserver") as c:
        seed(app.state.store)
        yield c


def test_api_stations(client):
    j = client.get("/api/stations?query=gal").json()
    assert {s["name"] for s in j["stations"]} == {"GALATI", "GALATZ"}
    assert client.get("/api/stations?limit=0").status_code == 422
    assert client.get("/api/stations?format=csv").text.lstrip("﻿").startswith("name,")


def test_api_station_detail(client):
    j = client.get("/api/stations/Gala%C8%9Bi?min=1").json()
    assert j["name"] == "GALATI" and j["boards"]["departure"]["stats"]["sufficient"]
    assert client.get("/api/stations/NIMIC").status_code == 404
    assert client.get("/api/stations/" + "A" * 41).status_code == 422
    assert client.get("/api/stations/%2D%2D").status_code == 422
    r = client.get("/api/stations/GALATI?format=csv")
    assert r.status_code == 200 and 'filename="statie-galati.csv"' in r.headers["content-disposition"]


def test_api_station_journeys(client):
    j = client.get("/api/stations/GALATI/journeys?limit=2&board=arrival").json()
    assert j["n"] == 2 and all(x["board"] == "arrival" for x in j["journeys"])
    assert client.get("/api/stations/GALATI/journeys?before=x").status_code == 422
    assert client.get("/api/stations/NIMIC/journeys").status_code == 404
    assert client.get("/api/stations/GALATI/journeys?format=csv").status_code == 200


def test_api_rankings_include_stations(client):
    j = client.get("/api/stats/rankings?min=5").json()
    assert j["stations"]["eligible"] == 2 and "_ranked" not in j["stations"]
    assert "stations_most_delayed" in client.get("/api/stats/rankings?format=csv&min=5").text
