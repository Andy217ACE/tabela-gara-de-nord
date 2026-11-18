# © 2026 Andy217Ace
"""Statistici v3 sp3 (2/5): threshold alerts — a route or operator with a MEDIAN delay above 15 min in
the last 7 days (the constant is in code), only with the minimum sample, last 7 days only."""
from datetime import date

from app import stats, stats_changes as sc, stats_compare as cmp
from tests.test_stats_overview import add, store  # noqa: F401
from tests.test_stats_v3_sp3_changes import P, TODAY


def run(store, p=P, filters=None):
    cmp.clear_cache()
    return sc.changes(store, p, filters or {}, TODAY)["alerts"]


def seed(c):
    for d in range(7, 14):   # an old week, so the base has 14 days
        add(c, "arrival", 1, d, "10:00", 0, station="OK", operator="Op OK")
    for i, d in enumerate(range(14, 21)):
        add(c, "arrival", 2, d, "10:00", 20 + i, station="SLOW", operator="Op SLOW")   # median 23
        add(c, "arrival", 1, d, "10:00", 1, station="OK", operator="Op OK")
    for d in (18, 19):   # only two journeys: below the minimum sample
        add(c, "arrival", 3, d, "10:00", 90, station="TINY", operator="Op TINY")


def test_threshold_constant_is_fifteen():
    assert sc.ALERT_MEDIAN_MIN == 15


def test_route_and_operator_above_threshold_alert(store):
    store._conn.execute("DELETE FROM services")
    seed(store._conn)
    a = run(store)
    assert {(x["kind"], x["key"]) for x in a} == {("route", "SLOW"), ("operator", "Op SLOW")}
    x = a[0]
    assert set(x) >= {"kind", "board", "key", "median", "n", "threshold"}
    assert x["median"] == 23.0 and x["n"] == 7 and x["threshold"] == 15
    # the small group never alerts, however late
    assert all(y["key"] not in ("TINY", "Op TINY") for y in a)


def test_exactly_at_the_threshold_is_not_an_alert(store):
    store._conn.execute("DELETE FROM services")
    for d in range(7, 21):
        add(store._conn, "arrival", 5, d, "10:00", 15, station="EDGE", operator="Op EDGE")
    assert run(store) == []


def test_only_the_last_seven_days_count(store):
    store._conn.execute("DELETE FROM services")
    for d in range(7, 14):
        add(store._conn, "arrival", 6, d, "10:00", 40, station="OLD", operator="Op OLD")
    for d in range(14, 21):
        add(store._conn, "arrival", 6, d, "10:00", 2, station="OLD", operator="Op OLD")
    assert run(store) == []


def test_alerts_are_listed_even_without_a_full_comparison_history(store):
    # 3 days of data: changes are „insuficient”, but an alert is a figure of the last 7 days with its N
    store._conn.execute("DELETE FROM services")
    for d in (18, 19, 20):
        for i in range(2):
            add(store._conn, "arrival", 7, d, f"1{i}:00", 40, station="NEW", operator="Op NEW")
    cmp.clear_cache()
    r = sc.changes(store, P, {}, TODAY)
    assert r["status"] == "insufficient"
    assert {x["key"] for x in r["alerts"]} == {"NEW", "Op NEW"}


def test_operator_filter_narrows_alerts(store):
    store._conn.execute("DELETE FROM services")
    seed(store._conn)
    assert {x["key"] for x in run(store, filters={"operator": "Op OK"})} == set()
