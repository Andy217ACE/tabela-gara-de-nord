# © 2026 Andy217Ace
"""Istoric without a day: EVERY day, every train (`/api/history?all=1`, no `train`, no
`date`) — newest first, keyset cursor (200 per page max), filters combinable, total and
period of the whole filtered result, summary only from READ delays, ghosts never listed,
the reduced-quality (beta) period listed + marked but kept out of the summary."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import history_all, stats
from app.api import create_app
from app.config import Settings
from app.store import Store
from tests.test_stats import add


def sq(store, sid, **kw):
    cols = ["service_id", "updated_at"] + list(kw)
    store._conn.execute(f"INSERT INTO service_quality({', '.join(cols)}) VALUES"
                        f" ({', '.join('?' * len(cols))})", [sid, "2026-10-22T00:00:00Z", *kw.values()])


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    ids = {}
    for i, d in enumerate([0, 2, 4, 10, 35, 1]):          # 1621 arrivals 14..19
        ids[("1621", 14 + i)] = add(s, "arrival", 1621, 14 + i, "12:10", d)
    ids["1731"] = add(s, "departure", 1731, 15, "08:15", 0, station="CONSTANTA")
    ids["1732"] = add(s, "departure", 1732, 15, "08:15", 6, station="CONSTANTA")  # same slot
    ids["unk"] = add(s, "arrival", 1580, 17, "21:05", 0, state="unknown", station="PLOIESTI SUD")
    ids["late"] = add(s, "arrival", 1580, 19, "23:50", 12, station="PLOIESTI SUD")
    s._ids = ids
    yield s
    s.close()


def P(**kw):
    return stats.Params(on_time=5, min_sample=kw.pop("min_sample", 3), **kw)


def _order(js):
    return [(j["service_date"], j["sched_time"], j["id"]) for j in js]


def test_no_day_no_train_lists_every_day_newest_first(store):
    d = history_all.page(store, None, P())
    js = d["journeys"]
    assert d["mode"] == "all" and d["train"] is None
    assert d["total"] == 10 and d["n"] == 10 and d["next"] is None
    assert d["period"] == {"first": "2026-10-14", "last": "2026-10-19", "days": 6}
    assert _order(js) == sorted(_order(js), reverse=True)
    assert js[0]["id"] == store._ids["late"]                  # 19th, 23:50 before 12:10
    assert {j["train_no"] for j in js} == {1621, 1731, 1732, 1580}


def test_cursor_pages_cover_everything_once_in_order(store):
    full = _order(history_all.page(store, None, P())["journeys"])
    seen, cur = [], None
    for _ in range(20):
        d = history_all.page(store, None, P(), limit=3, cursor=cur)
        assert d["total"] == 10 and d["n"] <= 3
        seen += _order(d["journeys"])
        cur = d["next"]
        if cur is None:
            break
    assert seen == full                     # ties (same day + time) split by id, no gaps


def test_limit_is_capped(store):
    assert history_all.page(store, None, P(), limit=10_000)["n"] == 10
    assert history_all.page(store, None, P(), limit=0)["n"] == 1


def test_filters_combine_without_day(store):
    d = history_all.page(store, None, P(board="departure"))
    assert {j["train_no"] for j in d["journeys"]} == {1731, 1732} and d["total"] == 2
    d = history_all.page(store, None, P(board="arrival"), station="ploiesti")
    assert [j["id"] for j in d["journeys"]] == [store._ids["late"], store._ids["unk"]]
    d = history_all.page(store, None, P(), time_from="20:00", time_to="23:59")
    assert {j["train_no"] for j in d["journeys"]} == {1580}
    d = history_all.page(store, None, P(), station="%")          # LIKE wildcards are literal
    assert d["total"] == 0 and d["period"] == {"first": None, "last": None, "days": 0}


def test_one_day_filters_that_day_only(store):
    day = date(2026, 10, 15)
    d = history_all.page(store, None, P(date_from=day, date_to=day))
    assert {j["service_date"] for j in d["journeys"]} == {"2026-10-15"} and d["total"] == 3
    assert d["period"]["days"] == 1


def test_summary_only_read_delays_unknown_never_zero(store):
    d = history_all.page(store, None, P())
    a = d["summary"]["arrival"]
    assert a["n"] == 7 and a["max"] == 35          # 6 × 1621 + 12; the unknown one not counted
    assert d["summary"]["departure"]["n"] == 2
    assert d["quality"]["states"]["unknown"] == 1
    js = {j["id"]: j for j in d["journeys"]}
    assert js[store._ids["unk"]]["max_read_delay"] is None


def test_ghost_excluded_low_quality_listed_not_summarised(store, monkeypatch):
    ghost = add(store, "arrival", 1999, 19, "10:00", 80)
    sq(store, ghost, ghost=1, ghost_reason="misread")
    beta = add(store, "arrival", 1998, 19, "11:00", 90)
    sq(store, beta, low_quality=1)
    d = history_all.page(store, None, P())
    ids = [j["id"] for j in d["journeys"]]
    assert ghost not in ids and beta in ids and d["total"] == 11
    assert d["low_quality_excluded"] == 1
    assert next(j for j in d["journeys"] if j["id"] == beta)["low_quality"] is True
    assert d["summary"]["arrival"]["max"] == 35
    monkeypatch.setenv("STATS_INCLUDE_LOW_QUALITY", "1")
    assert history_all.page(store, None, P())["summary"]["arrival"]["max"] == 90


def test_summary_cache_follows_new_data(store, monkeypatch):
    monkeypatch.setattr(history_all, "AGG_TTL_S", 0)
    assert history_all.page(store, None, P())["summary"]["arrival"]["max"] == 35
    add(store, "arrival", 1700, 19, "09:00", 55)
    d = history_all.page(store, None, P())
    assert d["total"] == 11 and d["summary"]["arrival"]["max"] == 55


def test_total_is_fresh_even_while_summary_is_cached(store):
    history_all.page(store, None, P())
    add(store, "arrival", 1700, 19, "09:00", 55)
    d = history_all.page(store, None, P())        # within the TTL: summary may lag, list/total not
    assert d["total"] == 11 and 1700 in {j["train_no"] for j in d["journeys"]}


def test_train_mode_unchanged(store):
    d = history_all.page(store, 1621, P())
    assert d["train"] == 1621 and d["total"] == 6
    assert _order(d["journeys"]) == _order([j for j in history_all.page(store, None, P())["journeys"]
                                            if j["train_no"] == 1621])


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
        add(st_, "departure", 1580, 19, "22:00", 4, station="IASI")
        yield c


def test_api_all_days_without_train(client):
    r = client.get("/api/history", params={"all": "1"})
    assert r.status_code == 200
    d = r.json()
    assert d["train"] is None and d["date"] is None and d["total"] == 8
    assert d["period"] == {"first": "2026-10-14", "last": "2026-10-19", "days": 6}
    assert d["journeys"][0]["train_no"] == 1580
    assert len({j["service_date"] for j in d["journeys"]}) == 6


def test_api_without_train_paginates(client):
    d = client.get("/api/history", params={"all": "1", "limit": "3"}).json()
    assert d["n"] == 3 and d["next"]
    seen = [j["id"] for j in d["journeys"]]
    while d["next"]:
        d = client.get("/api/history", params={"all": "1", "limit": "3", "cursor": d["next"]}).json()
        seen += [j["id"] for j in d["journeys"]]
    assert len(seen) == 8 and len(set(seen)) == 8


@pytest.mark.parametrize("params,total", [
    ({"board": "departure"}, 2),
    ({"station": "iasi"}, 1),
    ({"from": "08:00", "to": "09:00"}, 1),
    ({"date": "2026-10-14"}, 2),
    ({"date": "2026-10-14", "board": "arrival"}, 1),
    ({"train": "1621", "from": "12:00"}, 6),
])
def test_api_without_day_filters_combine(client, params, total):
    d = client.get("/api/history", params={"all": "1", **params}).json()
    assert d["total"] == total and len(d["journeys"]) == total


@pytest.mark.parametrize("params", [{"all": "1", "limit": "201"}, {"all": "1", "cursor": "x"},
                                    {"all": "1", "date": "2026-13-01"}])
def test_api_without_train_validation(client, params):
    r = client.get("/api/history", params=params)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)


def test_api_legacy_day_mode_still_works(client):
    d = client.get("/api/history", params={"date": "2026-10-16"}).json()
    assert d["date"] == "2026-10-16" and "services" in d
