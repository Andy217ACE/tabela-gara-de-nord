# © 2026 Andy217Ace
"""Statistici v2: /api/stats/overview — one aggregated, cached, read-only payload.
Rules: N everywhere, missing != 0, small samples withhold percentages, ghosts and the
reduced-quality period excluded, weather only with enough days (correlation != cause)."""
import threading
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import stats, stats_overview as so
from app.api import create_app
from app.config import Settings
from app.store import Store

BUC = ZoneInfo("Europe/Bucharest")
TODAY = date(2026, 10, 20)
P = stats.Params(on_time=5, min_sample=5)


def add(c, board, no, day, t, delay, *, state="confirmed", station="BRASOV",
        operator="CFR Calatori", ttype="IR", platform=None):
    hh, mm = (int(x) for x in t.split(":"))
    sched = datetime(2026, 10, day, hh, mm, tzinfo=BUC)
    read = None if state == "unknown" else (sched + timedelta(minutes=delay - 2)).isoformat()
    status = "listed" if state == "in_progress" else "gone"
    sid = c.execute(
        "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
        " sched_time, first_seen, last_seen, last_delay, status, uncertain, delay_read_at,"
        " last_platform) VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
        (board, f"2026-10-{day:02d}", ttype, no, station, operator, t,
         (sched - timedelta(hours=1)).isoformat(), (sched + timedelta(minutes=delay)).isoformat(),
         delay if state != "unknown" else 0, status, read, platform)).lastrowid
    c.execute("INSERT INTO events(service_id, ts, kind) VALUES (?,?,'appeared')",
              (sid, (sched - timedelta(hours=1)).isoformat()))
    if status == "gone" and state != "unconfirmed":
        c.execute("INSERT INTO events(service_id, ts, kind) VALUES (?,?,'gone')",
                  (sid, (sched + timedelta(minutes=delay + 3)).isoformat()))
    return sid


def mark(c, sid, **kw):
    cols = ", ".join(kw)
    c.execute(f"INSERT INTO service_quality(service_id, {cols}, updated_at) VALUES (?, "
              + ", ".join("?" * len(kw)) + ", '2026-10-20T00:00:00Z')", (sid, *kw.values()))


def weather(c, day, hour, temp, precip):
    t = datetime(2026, 10, day, hour, 0, tzinfo=BUC).astimezone(timezone.utc)
    c.execute("INSERT INTO weather_observations(observed_at, fetched_at, temperature_c,"
              " precipitation_mm, wind_speed_kmh) VALUES (?,?,?,?,?)",
              (t.strftime("%Y-%m-%dT%H:%M:%SZ"), t.isoformat(), temp, precip, 5.0))


def seed(c):
    # 1621 arrival 12:10 from Brașov, 6 days (sufficient), lines 3
    for i, d in enumerate([0, 2, 4, 10, 35, 1]):
        add(c, "arrival", 1621, 14 + i, "12:10", d, platform=3)
    # 1622 arrival 13:00 from Galați, 2 journeys (small sample), Transferoviar, line unknown
    add(c, "arrival", 1622, 20, "13:00", 50, station="GALATI", operator="Transferoviar", ttype="R")
    add(c, "arrival", 1622, 19, "13:00", 0, state="unconfirmed", station="GALATI",
        operator="Transferoviar", ttype="R")
    # 1731 departure 08:15 to Constanța: 5 read + 1 unknown + 1 in progress
    for i, d in enumerate([0, 0, 0, 1, 2]):
        add(c, "departure", 1731, 14 + i, "08:15", d, station="CONSTANTA", platform=7)
    add(c, "departure", 1731, 19, "08:15", 0, state="unknown", station="CONSTANTA", platform=7)
    add(c, "departure", 1731, 20, "08:15", 0, state="in_progress", station="CONSTANTA",
        platform=7)
    # excluded: a ghost and a reduced-quality journey (never in any figure)
    mark(c, add(c, "arrival", 9999, 20, "12:30", 90, station="BRASOV"), ghost=1)
    mark(c, add(c, "arrival", 8888, 14, "12:40", 70, station="BRASOV"), low_quality=1)


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.migrate()
    seed(s._conn)
    so.clear_cache()
    yield s
    s.close()


def ov(store, filters=None, p=P, today=TODAY):
    so.clear_cache()
    return so.overview(store, p, filters or {}, today=today)


# ---- pure parts ------------------------------------------------------------------------

def test_period_range():
    assert so.period_range("all", TODAY) == (None, None)
    assert so.period_range("1", TODAY) == (TODAY, TODAY)
    assert so.period_range("7", TODAY) == (date(2026, 10, 14), TODAY)
    assert so.period_range("30", TODAY) == (date(2026, 9, 21), TODAY)
    with pytest.raises(ValueError):
        so.period_range("3", TODAY)


def test_build_empty():
    d = so.build([], [], so.empty_extra(), P, TODAY, {})
    assert d["coverage"]["journeys"] == 0 and d["coverage"]["trains"] == 0
    assert d["history"]["days"] == 0 and d["history"]["sufficient"] is False
    for b in ("arrival", "departure"):
        assert d["boards"][b]["n"] == 0 and d["boards"][b]["on_time_pct"] is None
        assert all(h["n"] == 0 and h["median"] is None for h in d["hourly"][b])
        assert len(d["hourly"][b]) == 24
        assert d["heatmap"][b] == [] and d["daily"][b] == []
        assert d["platforms"][b]["missing"] == 0 and d["platforms"][b]["lines"] == []
    assert "Încă nu există" in d["insights"][0]
    assert d["weather"]["status"] == "collecting" and d["weather"]["matched"] == 0


# ---- whole payload ---------------------------------------------------------------------

def test_board_summary_and_distribution(store):
    d = ov(store)
    a = d["boards"]["arrival"]
    assert a["n"] == 8 and a["journeys"] == 8 and a["sufficient"]
    dist = {x["label"]: x for x in d["distribution"]["arrival"]}
    assert dist["0"]["n"] == 2 and dist["1–5"]["n"] == 3 and dist["31–60"]["n"] == 2
    assert dist["1–5"]["pct"] == 37.5
    dep = d["boards"]["departure"]
    assert dep["n"] == 5 and dep["journeys"] == 7  # unknown + in progress: not in the stats


def test_ghost_and_low_quality_excluded(store):
    d = ov(store)
    assert d["coverage"]["excluded"] == {"ghost": 1, "low_quality": 1}
    assert 9999 not in [r["key"] for r in d["routes"]["arrival"]["most_delayed"]]
    assert d["boards"]["arrival"]["max"] == 50  # 90 (ghost) and 70 (beta) never count
    assert d["coverage"]["journeys"] == 15


def test_hourly_and_heatmap_mark_small_samples(store):
    d = ov(store)
    h = d["hourly"]["arrival"]
    assert h[12]["n"] == 6 and h[12]["median"] == 3.0 and h[12]["sufficient"]
    assert h[13]["n"] == 2 and not h[13]["sufficient"] and h[13]["on_time_pct"] is None
    assert h[13]["median"] == 25.0  # raw figures stay
    assert h[5]["n"] == 0 and h[5]["median"] is None  # missing is not 0
    cells = {(c["d"], c["h"]): c for c in d["heatmap"]["arrival"]}
    # 2026-10-14 is a Wednesday (weekday 2)
    assert cells[(2, 12)]["n"] == 1 and not cells[(2, 12)]["sufficient"]
    assert all(c["n"] > 0 for c in d["heatmap"]["arrival"])


def test_daily_series(store):
    d = ov(store)
    days = [x["key"] for x in d["daily"]["arrival"]]
    assert days == sorted(days) and days[0] == "2026-10-14" and days[-1] == "2026-10-20"
    last = d["daily"]["arrival"][-1]
    assert last["n"] == 1 and last["journeys"] == 1 and last["on_time_pct"] is None


def test_operators_types_routes_min_sample(store):
    d = ov(store)
    ops = {x["key"]: x for x in d["operators"]["arrival"]}
    assert ops["CFR Calatori"]["n"] == 6 and ops["CFR Calatori"]["sufficient"]
    assert ops["Transferoviar"]["n"] == 2 and ops["Transferoviar"]["on_time_pct"] is None
    assert [x["key"] for x in d["operators"]["arrival"]][0] == "CFR Calatori"  # eligible first
    types = {x["key"]: x for x in d["types"]["arrival"]}
    assert types["IR"]["n"] == 6 and types["R"]["n"] == 2
    r = d["routes"]["arrival"]
    assert r["eligible"] == 1 and r["below_min"] == 1
    assert r["most_delayed"][0]["key"] == "BRASOV" and r["most_delayed"][0]["n"] == 6


def test_traffic_and_platforms_count_all_public_journeys(store):
    d = ov(store)
    t = d["traffic"]
    assert t["days"] == 7
    assert t["arrival"][12] == 6 and t["arrival"][13] == 2 and t["departure"][8] == 7
    assert t["arrival"][0] == 0
    pl = d["platforms"]
    assert pl["arrival"]["lines"] == [{"line": 3, "n": 6}]
    assert pl["departure"]["lines"] == [{"line": 7, "n": 7}]


def test_missing_platform_is_not_zero(store):
    pl = ov(store)["platforms"]["arrival"]
    assert pl["missing"] == 2
    assert all(x["line"] != 0 for x in pl["lines"])


def test_filters_operator_and_type(store):
    d = ov(store, {"operator": "Transferoviar"})
    assert d["boards"]["arrival"]["n"] == 2 and d["boards"]["departure"]["n"] == 0
    assert {o["name"] for o in d["options"]["operators"]} == {"CFR Calatori", "Transferoviar"}
    d = ov(store, {"tip": "R"})
    assert d["coverage"]["journeys"] == 2
    assert {t["name"] for t in d["options"]["types"]} == {"IR", "R"}
    assert ov(store, {"operator": "Nimeni"})["coverage"]["journeys"] == 0


def test_period_filter(store):
    p = stats.Params(on_time=5, min_sample=5, date_from=TODAY, date_to=TODAY)
    d = ov(store, {"perioada": "1"}, p=p)
    assert d["coverage"]["first"] == "2026-10-20" and d["coverage"]["journeys"] == 2
    assert d["history"]["days"] == 7  # the whole history stays known


def test_insights_text(store):
    text = " ".join(ov(store)["insights"])
    assert "Sosiri: din 8 călătorii încheiate cu întârziere citită" in text
    assert "(N = 8)" in text or "N = 8" in text
    assert "Plecări:" in text
    assert "12:00–12:59" in text  # the only sufficient arrival hour
    assert "linia 7" in text.lower()


def test_insights_small_sample_no_percent(store):
    d = ov(store, {"operator": "Transferoviar"})
    t = " ".join(d["insights"])
    assert "doar 2" in t and "%" not in t.split("Plecări")[0]


def test_weather_collecting(store):
    w = ov(store)["weather"]
    assert w["status"] == "collecting" and w["matched"] == 0 and w["needed_days"] == 7
    assert w["groups"] == {}


def test_weather_ok_groups(tmp_path):
    s = Store(str(tmp_path / "w.db"))
    s.migrate()
    c = s._conn
    for day in range(10, 20):
        wet = day % 2 == 0
        weather(c, day, 12, 8.0 if day < 15 else 18.0, 1.2 if wet else 0.0)
        add(c, "arrival", 100 + day, day, "12:00", 20 if wet else 1)
    c.commit()
    so.clear_cache()
    w = so.overview(s, P, {}, today=TODAY)["weather"]
    s.close()
    assert w["status"] == "ok" and w["matched"] == 10 and w["days"] == 10
    pr = {g["key"]: g for g in w["groups"]["precip"]}
    assert pr["wet"]["n"] == 5 and pr["wet"]["mean"] == 20 and pr["dry"]["n"] == 5
    assert "cauz" in w["note"]


def test_cache_ttl(store, monkeypatch):
    so.clear_cache()
    a = so.overview(store, P, {}, today=TODAY)
    add(store._conn, "arrival", 4242, 20, "15:00", 3)
    assert so.overview(store, P, {}, today=TODAY) is a  # served from cache within the TTL
    monkeypatch.setenv("STATS_CACHE_TTL_S", "0")
    b = so.overview(store, P, {}, today=TODAY)
    assert b is not a and b["coverage"]["journeys"] == a["coverage"]["journeys"] + 1


def test_does_not_wait_for_the_store_lock(store):
    """The OCR ingest holds store._lock; the statistics read on their own connection."""
    store._conn.commit()
    held, release = threading.Event(), threading.Event()

    def hold():
        with store._lock:
            held.set()
            release.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(5)
    out = {}
    w = threading.Thread(target=lambda: out.setdefault("d", ov(store)))
    w.start()
    w.join(5)
    release.set()
    t.join(5)
    assert "d" in out and out["d"]["coverage"]["journeys"] == 15


def test_ro_fallback_memory():
    s = Store(":memory:")
    s.migrate()
    seed(s._conn)
    so.clear_cache()
    d = so.overview(s, P, {}, today=TODAY)
    s.close()
    assert d["coverage"]["journeys"] == 15


def test_csv_sets(store):
    d = ov(store)
    for name in so.SETS:
        body = so.to_csv(d, name)
        assert body.startswith("﻿") and "\r\n" in body, name
    hourly = so.to_csv(d, "hourly")
    assert hourly.splitlines()[0].lstrip("﻿").startswith("board,hour,")
    with pytest.raises(KeyError):
        so.to_csv(d, "nimic")


# ---- API -------------------------------------------------------------------------------

@pytest.fixture
def client(store):
    store._conn.commit()
    s = Settings(db_path=store.path, source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract",
                 poller_enabled=False, last_image_path=None)
    so.clear_cache()
    with TestClient(create_app(s, start_poller=False)) as c:
        yield c


def test_api_overview_json(client):
    r = client.get("/api/stats/overview")
    assert r.status_code == 200
    d = r.json()
    assert d["coverage"]["journeys"] == 15 and d["params"]["perioada"] == "all"
    assert d["params"]["on_time_max_min"] == 5 and d["params"]["min_sample"] == 5
    assert set(d) >= {"insights", "distribution", "hourly", "heatmap", "daily", "operators",
                      "types", "routes", "traffic", "platforms", "weather", "quality"}


def test_api_filters_echo(client):
    d = client.get("/api/stats/overview?board=arrival&operator=Transferoviar&tip=R").json()
    assert d["params"]["board"] == "arrival" and d["params"]["operator"] == "Transferoviar"
    assert d["params"]["tip"] == "R" and list(d["boards"]) == ["arrival"]
    assert d["boards"]["arrival"]["n"] == 2


def test_api_bad_period(client):
    assert client.get("/api/stats/overview?perioada=5").status_code == 422
    assert client.get("/api/stats/overview?board=x").status_code == 422
    assert client.get("/api/stats/overview?operator=" + "x" * 41).status_code == 422


def test_api_unknown_operator(client):
    r = client.get("/api/stats/overview?operator=Nimeni")
    assert r.status_code == 200 and r.json()["coverage"]["journeys"] == 0


def test_api_csv_set(client):
    r = client.get("/api/stats/overview?format=csv&set=platforms")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="statistici-platforms.csv"' in r.headers["content-disposition"]
    assert "arrival" in r.text


def test_api_csv_bad_set(client):
    assert client.get("/api/stats/overview?format=csv").status_code == 422
    assert client.get("/api/stats/overview?format=csv&set=x").status_code == 422
