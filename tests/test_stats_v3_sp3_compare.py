# © 2026 Andy217Ace
"""Statistici v3 sp3 (3/5): `/api/stats/overview?compare=prev7` — the last 7 days next to the 7 before,
for the summary's figures. Under 7 days of data: „date insuficiente” (dictionary key), no figures."""
from datetime import date

import pytest

from app import stats, stats_compare as cmp
from tests.test_stats_overview import add, store  # noqa: F401
from tests.test_stats_v3_sp3_changes import P, TODAY


def run(store, p=P, filters=None):
    cmp.clear_cache()
    return cmp.compare(store, p, filters or {}, TODAY)


def two_weeks(c):
    for i, d in enumerate(range(7, 14)):     # before: 10 min late each, train 11
        add(c, "arrival", 11, d, "10:00", 10)
    for d in range(14, 21):                   # now: on time, trains 11 and 12
        add(c, "arrival", 11, d, "10:00", 0)
        add(c, "arrival", 12, d, "11:00", 2)


def test_shape_and_figures(store):
    store._conn.execute("DELETE FROM services")
    two_weeks(store._conn)
    r = run(store)
    assert r["status"] == "ok" and r["compare"] == "prev7"
    assert set(r) >= {"params", "window", "history", "now", "before", "delta", "cache_ttl_s", "generated_at"}
    assert r["window"] == {"now": ["2026-10-14", "2026-10-20"], "before": ["2026-10-07", "2026-10-13"]}
    keys = {"n", "on_time_pct", "mean", "median", "journeys", "trains"}
    assert set(r["now"]) >= keys and set(r["before"]) >= keys
    assert r["now"]["journeys"] == 14 and r["now"]["trains"] == 2 and r["now"]["on_time_pct"] == 100.0
    assert r["now"]["mean"] == 1.0
    assert r["before"]["journeys"] == 7 and r["before"]["trains"] == 1 and r["before"]["on_time_pct"] == 0.0
    assert r["before"]["mean"] == 10.0
    assert r["delta"]["on_time_pct"] == 100.0 and r["delta"]["mean"] == -9.0
    assert r["delta"]["journeys"] == 7 and r["delta"]["trains"] == 1


def test_under_seven_days_is_insufficient_with_no_figures(store):
    store._conn.execute("DELETE FROM services")
    for d in (19, 20):
        add(store._conn, "arrival", 1, d, "10:00", 3)
    r = run(store)
    assert r["status"] == "insufficient" and r["message_key"] == "stats.sp3.insufficient"
    assert r["now"] is None and r["before"] is None and r["delta"] is None
    assert r["history"] == {"days": 2, "needed_days": 7, "sufficient": False}


def test_empty_database_is_insufficient_not_zero(store):
    store._conn.execute("DELETE FROM services")
    r = run(store)
    assert r["status"] == "insufficient" and r["now"] is None


def test_week_without_data_has_missing_figures_not_zeros(store):
    store._conn.execute("DELETE FROM services")
    for d in range(14, 21):   # seven days of history, but nothing in the week before
        add(store._conn, "arrival", 11, d, "10:00", 0)
    r = run(store)
    assert r["status"] == "ok"
    assert r["before"]["journeys"] == 0 and r["before"]["n"] == 0
    assert r["before"]["on_time_pct"] is None and r["before"]["mean"] is None
    assert r["delta"]["on_time_pct"] is None and r["delta"]["mean"] is None


def test_small_sample_withholds_the_percentage_but_not_the_counts(store):
    store._conn.execute("DELETE FROM services")
    for d in range(7, 14):
        add(store._conn, "arrival", 11, d, "10:00", 0)
    add(store._conn, "arrival", 12, 20, "10:00", 0)
    add(store._conn, "arrival", 12, 19, "10:00", 0)
    r = run(store, p=stats.Params(on_time=5, min_sample=5))
    assert r["now"]["n"] == 2 and r["now"]["on_time_pct"] is None and r["now"]["journeys"] == 2
    assert r["delta"]["on_time_pct"] is None


def test_unknown_delay_journeys_count_as_journeys_not_as_zero_delay(store):
    store._conn.execute("DELETE FROM services")
    for d in range(7, 14):
        add(store._conn, "arrival", 11, d, "10:00", 0)
    for d in range(14, 18):
        add(store._conn, "arrival", 11, d, "10:00", 6)
    add(store._conn, "arrival", 11, 18, "10:00", 0, state="unknown")
    r = run(store)
    assert r["now"]["journeys"] == 5 and r["now"]["n"] == 4 and r["now"]["mean"] == 6.0


def test_filters_and_board_apply_to_both_columns(store):
    store._conn.execute("DELETE FROM services")
    two_weeks(store._conn)
    assert run(store, filters={"operator": "Nobody"})["now"]["journeys"] == 0
    r = run(store, p=stats.Params(on_time=5, min_sample=3, board="departure"))
    assert r["now"]["journeys"] == 0 and r["before"]["journeys"] == 0
