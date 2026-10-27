# © 2026 Andy217Ace
"""Beta 1.28: every train / station ranking entry carries `trend` — the mean READ delay per day over
the last 14 service days (ending at the latest day of the set), so the tables can draw a sparkline.
Additive field: a day without a read delay is null (never 0), `n` says how many journeys back it."""
from datetime import date

from fastapi.testclient import TestClient

from app import stats, stations
from tests.test_stats import add, client, store  # noqa: F401  (shared fixtures)

P = stats.Params(on_time=5, min_sample=5)


def test_trend_shape_and_values(store):  # noqa: F811
    d = stats.catalog(store, P)
    e = {(x["train_no"], x["board"]): x for x in d["trains"]}
    t = e[(1621, "arrival")]["trend"]
    assert t["days"] == 14 and t["last"] == "2026-10-20"
    assert len(t["values"]) == 14 and len(t["n"]) == 14
    # 1621: 14.10 .. 19.10 delays 0, 2, 4, 10, 35, 1 ; day 20 has no journey of this train
    assert t["values"][-7:] == [0.0, 2.0, 4.0, 10.0, 35.0, 1.0, None]
    assert t["n"][-7:] == [1, 1, 1, 1, 1, 1, 0]
    assert t["values"][:7] == [None] * 7 and sum(t["n"][:7]) == 0


def test_trend_missing_is_null_never_zero(store):  # noqa: F811
    # 1731: day 19 delay unread (unknown), day 20 still in progress -> both null, n = 0
    t = {(x["train_no"], x["board"]): x for x in stats.catalog(store, P)["trains"]}[(1731, "departure")]["trend"]
    assert t["values"][-2:] == [None, None] and t["n"][-2:] == [0, 0]
    assert t["values"][-7:-2] == [0.0, 0.0, 0.0, 1.0, 2.0]


def test_trend_averages_a_day_with_several_journeys(store):  # noqa: F811
    add(store, "arrival", 1621, 14, "18:30", 8)       # a second journey on 14.10 (0 and 8 -> 4)
    t = {(x["train_no"], x["board"]): x for x in stats.catalog(store, P)["trains"]}[(1621, "arrival")]["trend"]
    assert t["values"][-7] == 4.0 and t["n"][-7] == 2


def test_trend_is_in_rankings_and_station_entries(store):  # noqa: F811
    r = stats.rankings(store, P)
    assert all(len(e["trend"]["values"]) == 14 for e in r["most_delayed"] + r["most_punctual"])
    js = stats.load(store, P)
    for e in stations.station_entries(js, P):
        assert e["trend"]["days"] == 14 and e["trend"]["last"] == "2026-10-20"
    st = {e["station"]: e for e in stations.station_entries(js, P)}["BRASOV"]["trend"]
    assert st["n"][-7:] == [1, 1, 1, 1, 1, 2, 1]   # 1621 + the unconfirmed 1622 on 19.10; 1622 on 20.10


def test_trend_window_is_14_calendar_days_and_ignores_older(store):  # noqa: F811
    add(store, "arrival", 1621, 1, "12:10", 55)   # 1 Oct: outside the window ending at 20 Oct
    t = {(x["train_no"], x["board"]): x for x in stats.catalog(store, P)["trains"]}[(1621, "arrival")]["trend"]
    assert 55.0 not in t["values"]
    assert date.fromisoformat(t["last"]).toordinal() - 13 == date(2026, 10, 7).toordinal()


def test_trend_over_http_and_csv_unchanged(client):  # noqa: F811
    r = client.get("/api/trains/stats")
    assert r.status_code == 200
    e = r.json()["trains"][0]
    assert set(e["trend"]) == {"last", "days", "values", "n"}
    csv = client.get("/api/trains/stats?format=csv").text
    assert "trend" not in csv
    rk = client.get("/api/stats/rankings").json()
    assert rk["most_delayed"] and "trend" in rk["most_delayed"][0]
