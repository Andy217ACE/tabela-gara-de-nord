# © 2026 Andy217Ace
"""Statistici v3 sp3 (1/5): „Ce s-a schimbat săptămâna asta” — top 3 better / worse routes and
operators, last 7 days vs the 7 before, by % on time. Fewer than 7 days of data: „date insuficiente”
(dictionary key), never invented figures."""
from datetime import date

import pytest

from app import stats, stats_changes as sc, stats_compare as cmp
from tests.test_stats_overview import add, store  # noqa: F401

TODAY = date(2026, 10, 20)
P = stats.Params(on_time=5, min_sample=3)


def seed_weeks(c, routes):
    """routes: station -> (delays last 7 days (14-20), delays previous 7 days (7-13)), 1 per day."""
    no = 4000
    for station, (cur, prev) in routes.items():
        no += 1
        for i, d in enumerate(cur):
            add(c, "arrival", no, 14 + i, "10:00", d, station=station, operator="Op " + station)
        for i, d in enumerate(prev):
            add(c, "arrival", no, 7 + i, "10:00", d, station=station, operator="Op " + station)


def run(store, filters=None, p=P):
    cmp.clear_cache()
    return sc.changes(store, p, filters or {}, TODAY)


def test_insufficient_history_is_a_dictionary_key_not_zeros(store):
    # a young base: 3 days of data
    store._conn.execute("DELETE FROM services")
    for d in (18, 19, 20):
        add(store._conn, "arrival", 1, d, "10:00", 3)
    r = run(store)
    assert r["status"] == "insufficient" and r["message_key"] == "stats.sp3.insufficient"
    assert r["improved"] == [] and r["worsened"] == []
    assert r["history"]["days"] == 3 and r["history"]["needed_days"] == 7


def test_empty_database_is_insufficient(store):
    store._conn.execute("DELETE FROM services")
    assert run(store)["status"] == "insufficient"


def test_improved_and_worsened_top_three(store):
    store._conn.execute("DELETE FROM services")
    seed_weeks(store._conn, {
        "A": ([0] * 7, [20] * 7),        # 0% -> 100%: +100
        "B": ([0] * 7, [0, 0, 0, 20, 20, 20, 20]),   # 43% -> 100%: +57
        "C": ([0, 0, 0, 20, 20, 20, 20], [0] * 7),   # worse -43
        "D": ([20] * 7, [0] * 7),                    # worse -100
        "E": ([0] * 7, [0] * 7),                     # unchanged: in neither list
        "F": ([0] * 7, [20, 20, 0, 0, 0, 0, 0]),     # +28.6
        "G": ([0, 0, 0, 0, 20, 20, 20], [0] * 7),    # worse -42.9? 4/7 on time = 57.1 -> -42.9
    })
    r = run(store)
    assert r["status"] == "ok"
    rt = [x for x in r["improved"] if x["kind"] == "route"]
    assert [x["key"] for x in rt][:2] == ["A", "B"]
    assert len([x for x in r["improved"] if x["kind"] == "route"]) == 3
    assert [x["key"] for x in r["worsened"] if x["kind"] == "route"][:2] == ["D", "C"] \
        or [x["key"] for x in r["worsened"] if x["kind"] == "route"][:2] == ["D", "G"]
    top = r["improved"][0]
    assert set(top) >= {"kind", "board", "key", "now_pct", "before_pct", "delta", "n_now", "n_before"}
    assert top["delta"] == round(top["now_pct"] - top["before_pct"], 1)
    assert all(x["delta"] > 0 for x in r["improved"]) and all(x["delta"] < 0 for x in r["worsened"])
    assert all(x["key"] != "E" for x in r["improved"] + r["worsened"])
    assert len(r["improved"]) <= 6 and len(r["worsened"]) <= 6   # 3 routes + 3 operators


def test_group_below_min_sample_in_either_week_is_left_out(store):
    store._conn.execute("DELETE FROM services")
    seed_weeks(store._conn, {"A": ([0] * 7, [20] * 7), "B": ([0] * 7, [])})
    # B has no journeys in the previous week: no comparison, no invented 0%
    r = run(store)
    assert all(x["key"] != "B" for x in r["improved"] + r["worsened"])
    assert any(x["key"] == "A" for x in r["improved"])


def test_operator_filter_and_board_are_applied(store):
    store._conn.execute("DELETE FROM services")
    seed_weeks(store._conn, {"A": ([0] * 7, [20] * 7), "B": ([20] * 7, [0] * 7)})
    r = run(store, {"operator": "Op A"})
    assert all(x["key"] in ("A", "Op A") for x in r["improved"] + r["worsened"])
    r = run(store, p=stats.Params(on_time=5, min_sample=3, board="departure"))
    assert r["improved"] == [] and r["worsened"] == []


def test_response_shape_and_cache(store):
    store._conn.execute("DELETE FROM services")
    seed_weeks(store._conn, {"A": ([0] * 7, [20] * 7)})
    r = run(store)
    assert set(r) >= {"params", "status", "history", "improved", "worsened", "alerts",
                      "alert_threshold_min", "window", "cache_ttl_s", "generated_at"}
    assert r["window"] == {"now": ["2026-10-14", "2026-10-20"], "before": ["2026-10-07", "2026-10-13"]}
    assert r["cache_ttl_s"] == 60
    # read-only + cached: a new journey is not seen within the TTL
    add(store._conn, "arrival", 77, 20, "11:00", 99, station="A", operator="Op A")
    again = sc.changes(store, P, {}, TODAY)
    assert again is r or again["generated_at"] == r["generated_at"]
