# © 2026 Andy217Ace
"""Statistics (Etapa D): N always shown, missing != 0, small samples withhold percentages."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import stats
from app.api import create_app
from app.config import Settings
from app.store import Store

BUC = ZoneInfo("Europe/Bucharest")


# ---- pure functions -----------------------------------------------------------------

def test_percentile_linear():
    assert stats.percentile([], 0.5) is None
    assert stats.percentile([7], 0.9) == 7
    assert stats.percentile([0, 10], 0.5) == 5
    assert stats.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == pytest.approx(9.1)


def test_summarize_full_sample():
    s = stats.summarize([0, 0, 3, 6, 40], on_time_max=5, min_sample=5)
    assert s["n"] == 5 and s["sufficient"]
    assert s["mean"] == 9.8 and s["median"] == 3 and s["max"] == 40
    assert s["on_time"] == 3 and s["on_time_pct"] == 60.0
    assert s["over_30"] == 1 and s["over_30_pct"] == 20.0
    assert s["p90"] == pytest.approx(26.4)


def test_summarize_small_sample_withholds_percentages():
    s = stats.summarize([0, 12], on_time_max=5, min_sample=5)
    assert s["n"] == 2 and not s["sufficient"]
    assert s["on_time"] == 1 and s["on_time_pct"] is None
    assert s["p90"] is None and s["over_30_pct"] is None
    assert s["mean"] == 6.0 and s["max"] == 12  # raw figures stay


def test_summarize_empty_is_not_zero():
    s = stats.summarize([None, None], 5, 1)
    assert s["n"] == 0 and s["mean"] is None and s["max"] is None and s["on_time_pct"] is None


def test_threshold_changes_on_time():
    assert stats.summarize([0, 5, 6], 5, 1)["on_time"] == 2
    assert stats.summarize([0, 5, 6], 0, 1)["on_time"] == 1


def test_distribution_buckets():
    d = {b["label"]: b["n"] for b in stats.distribution([0, 1, 5, 6, 30, 31, 61, None])}
    assert d == {"0": 1, "1–5": 2, "6–15": 1, "16–30": 1, "31–60": 1, "> 60": 1}


def test_env_defaults(monkeypatch):
    monkeypatch.setenv("ON_TIME_MAX_MIN", "3")
    monkeypatch.setenv("STATS_MIN_SAMPLE", "abc")
    assert stats.default_on_time() == 3 and stats.default_min_sample() == 5


# ---- data sets ----------------------------------------------------------------------

def iso(d, h, m):
    return datetime(2026, 10, d, h, m, tzinfo=BUC).isoformat()


def add(store, board, no, day, t, delay, *, state="confirmed", station="BRASOV", uncertain=0):
    """Insert a journey whose computed result will be `state`."""
    hh, mm = (int(x) for x in t.split(":"))
    sched = datetime(2026, 10, day, hh, mm, tzinfo=BUC)
    read = None if state == "unknown" else (sched + timedelta(minutes=delay - 2)).isoformat()
    status = "listed" if state == "in_progress" else "gone"
    c = store._conn
    sid = c.execute(
        "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
        " sched_time, first_seen, last_seen, last_delay, status, uncertain, delay_read_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (board, f"2026-10-{day:02d}", "IR", no, station, "CFR Calatori", t,
         (sched - timedelta(hours=1)).isoformat(), (sched + timedelta(minutes=delay)).isoformat(),
         delay if state != "unknown" else 0, status, uncertain, read)).lastrowid
    c.execute("INSERT INTO events(service_id, ts, kind) VALUES (?,?,'appeared')",
              (sid, (sched - timedelta(hours=1)).isoformat()))
    if status == "gone" and state != "unconfirmed":
        c.execute("INSERT INTO events(service_id, ts, kind) VALUES (?,?,'gone')",
                  (sid, (sched + timedelta(minutes=delay + 3)).isoformat()))
    return sid


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    # 1621 arrival: 6 journeys (sufficient); 1622 arrival: 2; 1731 departure: 5
    for i, d in enumerate([0, 2, 4, 10, 35, 1]):
        add(s, "arrival", 1621, 14 + i, "12:10", d)
    add(s, "arrival", 1622, 20, "13:00", 50)
    add(s, "arrival", 1622, 19, "13:00", 0, state="unconfirmed")
    for i, d in enumerate([0, 0, 0, 1, 2]):
        add(s, "departure", 1731, 14 + i, "08:15", d, station="CONSTANTA")
    add(s, "departure", 1731, 19, "08:15", 0, state="unknown", station="CONSTANTA")
    add(s, "departure", 1731, 20, "08:15", 0, state="in_progress", station="CONSTANTA")
    yield s
    s.close()


def test_catalog_entries_per_train_and_board(store):
    d = stats.catalog(store, stats.Params(on_time=5, min_sample=5))
    e = {(x["train_no"], x["board"]): x for x in d["trains"]}
    a = e[(1621, "arrival")]
    assert a["journeys"] == 6 and a["stats"]["n"] == 6 and a["stats"]["sufficient"]
    assert a["stats"]["on_time"] == 4  # 0,2,4,1
    dep = e[(1731, "departure")]
    assert dep["journeys"] == 7 and dep["stats"]["n"] == 5  # unknown + in progress excluded
    assert dep["quality"]["states"]["unknown"] == 1 and dep["quality"]["states"]["in_progress"] == 1
    small = e[(1622, "arrival")]
    assert small["stats"]["n"] == 2 and small["stats"]["on_time_pct"] is None


def test_confirmed_only(store):
    d = stats.catalog(store, stats.Params(on_time=5, min_sample=1, confirmed_only=True))
    small = {(x["train_no"], x["board"]): x for x in d["trains"]}[(1622, "arrival")]
    assert small["stats"]["n"] == 1


def test_catalog_query(store):
    assert {x["train_no"] for x in stats.catalog(store, stats.Params(), "162")["trains"]} == {1621, 1622}
    assert {x["train_no"] for x in stats.catalog(store, stats.Params(), "const")["trains"]} == {1731}


def test_rankings_respect_min_sample(store):
    r = stats.rankings(store, stats.Params(on_time=5, min_sample=5))
    assert r["eligible"] == 2 and r["below_min"] == 1
    assert [e["train_no"] for e in r["most_delayed"]] == [1621, 1731]
    assert [e["train_no"] for e in r["most_punctual"]] == [1731, 1621]


def test_overview(store):
    o = stats.overview(store, stats.Params(on_time=5, min_sample=5))
    assert o["quality"]["journeys"] == 15
    assert o["boards"]["arrival"]["n"] == 8 and o["boards"]["departure"]["n"] == 5
    hours = {h["key"]: h for h in o["by_time"]["arrival"]["hour"]}
    assert hours[12]["n"] == 6 and hours[13]["n"] == 2 and hours[0]["n"] == 0
    assert len(o["by_time"]["departure"]["weekday"]) == 7
    assert o["by_time"]["arrival"]["month"][0]["key"] == "2026-10"
    assert o["period"] == {"first": "2026-10-14", "last": "2026-10-20", "days": 7}


def test_board_filter(store):
    o = stats.overview(store, stats.Params(board="departure"))
    assert set(o["boards"]) == {"departure"} and o["quality"]["journeys"] == 7


# ---- API ----------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    s = Store(str(db))
    s.migrate()
    s._conn.close()
    st = Settings(db_path=str(db), source_url="http://x", vapid_private_key="",
                  vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract",
                  poller_enabled=False, last_image_path=None, weather=None)
    app = create_app(st, start_poller=False)
    with TestClient(app, base_url="https://testserver") as c:
        store_ = app.state.store
        for i, d in enumerate([0, 2, 4, 10, 35, 1]):
            add(store_, "arrival", 1621, 14 + i, "12:10", d)
        add(store_, "departure", 1731, 14, "08:15", 0, state="unknown", station="CONSTANTA")
        yield c


def test_api_stats_and_params(client):
    r = client.get("/api/stats?prag=0&min=3")
    assert r.status_code == 200
    j = r.json()
    assert j["params"]["on_time_max_min"] == 0 and j["params"]["min_sample"] == 3
    assert j["boards"]["arrival"]["on_time"] == 1
    for bad in ("prag=61", "min=0", "board=x", "from=2026-1-1", "from=2026-10-20&to=2026-10-01",
                "doar_confirmate=2", "prag=-1"):
        assert client.get("/api/stats?" + bad).status_code == 422, bad


def test_api_trains_stats_csv(client):
    r = client.get("/api/trains/stats?format=csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.lstrip("﻿").splitlines()
    assert lines[0].startswith("train_no,board,")
    assert len(lines) == 3
    assert client.get("/api/trains/stats?format=xml").status_code == 422


def test_api_trains_stats_does_not_shadow_detail(client):
    assert client.get("/api/trains/stats").json()["n"] == 2
    assert client.get("/api/trains/abc").status_code == 422


def test_api_train_journeys(client):
    j = client.get("/api/trains/1621/journeys").json()
    assert j["train_no"] == 1621 and len(j["journeys"]) == 6
    assert j["journeys"][0]["service_date"] == "2026-10-19"  # newest first
    assert j["journeys"][0]["result"]["state"] == "confirmed"
    assert client.get("/api/trains/9999/journeys").status_code == 404
    assert client.get("/api/trains/0/journeys").status_code == 422
    assert client.get("/api/trains/1621/journeys?format=csv").text.count("\r\n") == 7


def test_api_journeys_list_and_detail(client):
    j = client.get("/api/journeys?state=unknown").json()
    assert j["n"] == 1 and j["journeys"][0]["result"]["observed_delay"] is None
    jid = j["journeys"][0]["id"]
    d = client.get(f"/api/journeys/{jid}").json()
    assert d["result"]["state"] == "unknown" and d["delay_series"] == []
    assert client.get("/api/journeys/99999").status_code == 404
    assert client.get("/api/journeys/x").status_code == 422
    assert client.get("/api/journeys?state=nope").status_code == 422
    assert client.get("/api/journeys?limit=2").json()["truncated"] is True
    csv_ = client.get("/api/journeys?format=csv&train=1621").text
    assert csv_.lstrip("﻿").startswith("id,service_date,board")


def test_api_rankings(client):
    j = client.get("/api/stats/rankings?min=6").json()
    assert j["eligible"] == 1 and j["most_delayed"][0]["train_no"] == 1621
    assert client.get("/api/stats/rankings?min=7").json()["eligible"] == 0
    assert client.get("/api/stats/rankings?format=csv").status_code == 200
    assert client.get("/api/stats/rankings?limit=51").status_code == 422


def test_api_history_has_id_and_delay_known(client):
    j = client.get("/api/history?date=2026-10-14").json()
    by_no = {s["train_no"]: s for s in j["services"]}
    assert by_no[1731]["delay_known"] is False and by_no[1621]["delay_known"] is True
    assert isinstance(by_no[1621]["id"], int)


def test_cache_invalidated_by_new_data(store):
    p = stats.Params(on_time=5, min_sample=1)
    n0 = stats.overview(store, p)["quality"]["journeys"]
    assert stats.overview(store, p)["quality"]["journeys"] == n0  # cached path
    add(store, "arrival", 1999, 20, "20:00", 3)
    assert stats.overview(store, p)["quality"]["journeys"] == n0 + 1
    store._conn.execute("UPDATE services SET status='gone' WHERE status='listed'")
    store._conn.execute("INSERT INTO runs(ts, ok, n_rows) VALUES ('x', 1, 0)")
    assert stats.overview(store, p)["quality"]["states"]["in_progress"] == 0
