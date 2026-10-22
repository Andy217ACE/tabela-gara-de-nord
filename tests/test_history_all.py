# © 2026 Andy217Ace
"""Istoric — all days of one train (`/api/history?train=N&all=1`): every journey of the
train, newest first, paginated by a keyset cursor, with a summary per board computed only
from READ delays (missing is never 0) and percentages withheld below the minimum sample."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import history_all, stats
from app.api import create_app
from app.config import Settings
from app.store import Store
from tests.test_stats import add


def delay_event(store, sid, ts, old, new):
    store._conn.execute("INSERT INTO events(service_id, ts, kind, old, new) VALUES (?,?,'delay',?,?)",
                        (sid, ts, old, new))


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    # 1621: arrival on 14..19 (6 journeys), departure on 20 (in progress), other train 1731
    ids = {}
    for i, d in enumerate([0, 2, 4, 10, 35, 1]):
        ids[14 + i] = add(s, "arrival", 1621, 14 + i, "12:10", d)
    add(s, "arrival", 1621, 13, "12:10", 0, state="unknown", station="PLOIESTI")
    add(s, "arrival", 1621, 12, "12:10", 7, state="unconfirmed")
    add(s, "departure", 1621, 20, "18:40", 3, state="in_progress", station="CONSTANTA")
    add(s, "departure", 1731, 15, "08:15", 0, station="CONSTANTA")
    delay_event(s, ids[18], "2026-10-18T12:20:00+03:00", "0", "50")  # a higher reading earlier
    s._ids = ids
    yield s
    s.close()


def P(**kw):
    return stats.Params(on_time=5, min_sample=kw.pop("min_sample", 5), **kw)


def test_all_days_newest_first(store):
    d = history_all.page(store, 1621, P())
    js = d["journeys"]
    assert [j["service_date"] for j in js] == ["2026-10-20", "2026-10-19", "2026-10-18", "2026-10-17",
                                               "2026-10-16", "2026-10-15", "2026-10-14",
                                               "2026-10-13", "2026-10-12"]
    assert all(j["train_no"] == 1621 for j in js)
    assert d["total"] == 9 and d["n"] == 9 and d["next"] is None
    assert d["period"] == {"first": "2026-10-12", "last": "2026-10-20", "days": 9}


def test_unknown_delay_is_not_zero(store):
    js = {j["service_date"]: j for j in history_all.page(store, 1621, P())["journeys"]}
    unk = js["2026-10-13"]
    assert unk["result"]["state"] == "unknown"
    assert unk["result"]["observed_delay"] is None and unk["max_read_delay"] is None
    assert js["2026-10-18"]["max_read_delay"] == 50  # max over readings, final stays 35
    assert js["2026-10-18"]["result"]["final_delay"] == 35
    assert js["2026-10-14"]["max_read_delay"] == 0  # a read 0 is a real 0


def test_summary_only_known_values_per_board(store):
    d = history_all.page(store, 1621, P())
    a = d["summary"]["arrival"]
    # 6 confirmed (0,2,4,10,35,1) + 1 unconfirmed (7); unknown never counted
    assert a["n"] == 7 and a["max"] == 35 and a["median"] == 4
    assert a["sufficient"] and a["on_time_pct"] is not None
    assert d["summary"]["departure"]["n"] == 0  # in progress only: no value, not 0
    assert d["summary"]["departure"]["mean"] is None
    assert d["quality"]["states"]["unknown"] == 1


def test_summary_below_min_sample_has_no_percentages(store):
    d = history_all.page(store, 1621, P(min_sample=50))
    a = d["summary"]["arrival"]
    assert a["n"] == 7 and not a["sufficient"]
    assert a["on_time_pct"] is None and a["p90"] is None and a["mean"] is not None


def test_pagination_cursor_covers_everything_once(store):
    seen, cur = [], None
    for _ in range(10):
        d = history_all.page(store, 1621, P(), limit=4, cursor=cur)
        seen += [j["id"] for j in d["journeys"]]
        assert d["total"] == 9  # summary/total describe the whole result, not the page
        cur = d["next"]
        if cur is None:
            break
    assert len(seen) == 9 and len(set(seen)) == 9


def test_filters_combine(store):
    d = history_all.page(store, 1621, P(board="arrival"), station="ploi")
    assert [j["service_date"] for j in d["journeys"]] == ["2026-10-13"]
    d = history_all.page(store, 1621, P(), time_from="18:00", time_to="23:59")
    assert [j["board"] for j in d["journeys"]] == ["departure"]
    day = date(2026, 10, 16)
    d = history_all.page(store, 1621, P(date_from=day, date_to=day))
    assert [j["service_date"] for j in d["journeys"]] == ["2026-10-16"]


def test_station_wildcards_are_literal(store):
    assert history_all.page(store, 1621, P(), station="%")["total"] == 0


def test_cursor_parse():
    assert history_all.parse_cursor("2026-10-18_12:10_42") == ("2026-10-18", "12:10", 42)
    for bad in ("x", "2026-10-18_25:10_1", "2026-10-18_12:10_", "2026-13-01_12:10_1",
                "2026-10-18_12:10_1;DROP", "2026-10-18_12:10_" + "9" * 13):
        with pytest.raises(ValueError):
            history_all.parse_cursor(bad)


# ---- data quality (schema v7): same exclusions as the rest --------------------------------

def sq(store, sid, **kw):
    cols = ["service_id", "updated_at"] + list(kw)
    store._conn.execute(f"INSERT INTO service_quality({', '.join(cols)}) VALUES"
                        f" ({', '.join('?' * len(cols))})", [sid, "2026-10-22T00:00:00Z", *kw.values()])


def test_ghost_never_listed_nor_counted(store):
    ghost = add(store, "arrival", 1621, 21, "12:10", 90)
    sq(store, ghost, ghost=1, ghost_reason="misread")
    d = history_all.page(store, 1621, P())
    assert ghost not in [j["id"] for j in d["journeys"]] and d["total"] == 9
    assert d["summary"]["arrival"]["max"] == 35


def test_low_quality_listed_but_not_in_summary(store, monkeypatch):
    beta = add(store, "arrival", 1621, 21, "12:10", 90)
    sq(store, beta, low_quality=1)
    d = history_all.page(store, 1621, P())
    first = d["journeys"][0]
    assert first["id"] == beta and first["low_quality"] is True
    assert d["total"] == 10 and d["low_quality_excluded"] == 1
    assert d["summary"]["arrival"]["n"] == 7 and d["summary"]["arrival"]["max"] == 35
    monkeypatch.setenv("STATS_INCLUDE_LOW_QUALITY", "1")
    assert history_all.page(store, 1621, P())["summary"]["arrival"]["max"] == 90


def test_suspect_event_is_not_a_reading(store):
    sid = store._ids[17]
    ev = store._conn.execute("INSERT INTO events(service_id, ts, kind, old, new)"
                             " VALUES (?,?,'delay','0','425')", (sid, "2026-10-17T12:05:00+03:00")).lastrowid
    store._conn.execute("INSERT INTO event_quality(event_id, suspect, reason) VALUES (?,1,'plus_misread')",
                        (ev,))
    js = {j["id"]: j for j in history_all.page(store, 1621, P())["journeys"]}
    assert js[sid]["max_read_delay"] == 10


def test_checked_without_confirmed_value_is_unknown(store):
    sid = store._ids[16]
    sq(store, sid, delay_checked=1)
    js = {j["id"]: j for j in history_all.page(store, 1621, P())["journeys"]}
    assert js[sid]["max_read_delay"] is None and js[sid]["result"]["delay_known"] is False
    sid2 = store._ids[15]
    sq(store, sid2, delay_checked=1, max_delay_clean=6, last_delay_clean=2)
    js = {j["id"]: j for j in history_all.page(store, 1621, P())["journeys"]}
    assert js[sid2]["max_read_delay"] == 6 and js[sid2]["result"]["observed_delay"] == 2


# ---- API --------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
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
        for i, d in enumerate([0, 2, 4, 10, 35, 1]):
            add(st_, "arrival", 1621, 14 + i, "12:10", d)
        add(st_, "departure", 1731, 14, "08:15", 0, station="CONSTANTA")
        yield c


def test_api_all_days(client):
    r = client.get("/api/history", params={"train": "1621", "all": "1"})
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "all" and d["train"] == 1621 and d["date"] is None
    assert d["total"] == 6 and len(d["journeys"]) == 6
    assert d["journeys"][0]["service_date"] == "2026-10-19"
    assert d["summary"]["arrival"]["n"] == 6
    assert d["params"]["min_sample"] >= 1


def test_api_all_days_with_day_and_page(client):
    d = client.get("/api/history", params={"train": "1621", "all": "1", "date": "2026-10-16"}).json()
    assert d["date"] == "2026-10-16" and [j["service_date"] for j in d["journeys"]] == ["2026-10-16"]
    d = client.get("/api/history", params={"train": "1621", "all": "1", "limit": "2"}).json()
    assert len(d["journeys"]) == 2 and d["next"]
    d2 = client.get("/api/history", params={"train": "1621", "all": "1", "limit": "2",
                                            "cursor": d["next"]}).json()
    assert d2["journeys"][0]["service_date"] == "2026-10-17"


def test_api_day_mode_unchanged(client):
    d = client.get("/api/history", params={"date": "2026-10-16"}).json()
    assert d["date"] == "2026-10-16" and "services" in d and "mode" not in d


@pytest.mark.parametrize("params", [
    {"all": "1"},                                  # all days needs a train number
    {"train": "1621", "all": "2"},
    {"train": "1621", "all": "1", "limit": "0"},
    {"train": "1621", "all": "1", "limit": "201"},
    {"train": "1621", "all": "1", "limit": "abc"},
    {"train": "1621", "all": "1", "cursor": "nope"},
    {"train": "1621", "all": "1", "date": "2026-02-30"},
    {"train": "1621", "all": "1", "min": "0"},
    {"train": "1621", "all": "1", "board": "x"},
    {"train": "1621", "all": "1", "from": "25:00"},
    {"train": "1621", "all": "1", "from": "13:00", "to": "12:00"},
    {"train": "1621", "all": "1", "station": "x" * 65},
    {"train": "abc", "all": "1"},
])
def test_api_all_days_validation(client, params):
    r = client.get("/api/history", params=params)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)


def test_api_all_days_unknown_train_is_empty(client):
    d = client.get("/api/history", params={"train": "9999", "all": "1"}).json()
    assert d["total"] == 0 and d["journeys"] == [] and d["period"]["first"] is None


# ---- static (CSP-safe UI) -------------------------------------------------------------

def _web(name):
    from pathlib import Path
    return (Path(__file__).resolve().parent.parent / "web" / name).read_text(encoding="utf-8")


def test_index_has_all_days_selector_and_load_more():
    html = _web("index.html")
    assert 'id="h-scope"' in html and "Toate zilele" in html and "O zi anume" in html
    assert 'id="h-more"' in html and "Încarcă mai multe" in html and 'id="h-summary"' in html
    assert "style=" not in html


def test_history_js_all_days_mode():
    js = _web("history.js")
    assert 'p.set("all", "1")' in js and 'p.set("cursor", cursor)' in js and "var PAGE = 200" in js
    assert "#tren?nr=" in js and "openJourney(j.id" in js
    assert "necunoscut, nu 0" in js and "fără procente sub N" in js
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", ".style.", "setAttribute(\"style\""):
        assert bad not in js
