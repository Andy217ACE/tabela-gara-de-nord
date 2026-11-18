# © 2026 Andy217Ace
"""Statistici v3 sp3 (4/5): „Cele mai fiabile trenuri” — the mirror of „Probleme”: trains most often on
time, at least 10 journeys with a read delay (a train with one journey never shows up)."""
from app import stats, stats_changes as sc, stats_compare as cmp
from tests.test_stats_overview import add, store  # noqa: F401
from tests.test_stats_v3_sp3_changes import P, TODAY


def run(store, p=P, filters=None):
    cmp.clear_cache()
    return sc.reliable(store, p, filters or {}, TODAY)


def seed(c):
    days = list(range(7, 21))   # 14 days
    for d in days:                                     # 14 journeys, always on time
        add(c, "arrival", 101, d, "10:00", 0, station="A", operator="Op1")
    for d in days[:12]:                                # 12 journeys, 9 on time
        add(c, "arrival", 102, d, "11:00", 0 if d % 4 else 20, station="B", operator="Op2")
    for d in days[:10]:                                # exactly 10 journeys, all on time: qualifies
        add(c, "departure", 103, d, "12:00", 1, station="C", operator="Op1")
    for d in days[:9]:                                 # 9 journeys: below the threshold
        add(c, "arrival", 104, d, "13:00", 0, station="D", operator="Op1")
    add(c, "arrival", 105, 20, "14:00", 0, station="E", operator="Op1")     # one journey, perfect


def test_minimum_is_ten_journeys(store):
    store._conn.execute("DELETE FROM services")
    seed(store._conn)
    r = run(store)
    assert sc.RELIABLE_MIN_JOURNEYS == 10
    nos = [x["train_no"] for x in r["items"]]
    assert 104 not in nos and 105 not in nos
    assert set(nos) == {101, 102, 103}
    assert r["min_journeys"] == 10 and r["status"] == "ok"


def test_order_and_fields(store):
    store._conn.execute("DELETE FROM services")
    seed(store._conn)
    items = run(store)["items"]
    assert [x["train_no"] for x in items][-1] == 102      # least on time of the qualifying ones, last
    assert items[0]["on_time_pct"] == 100.0
    top = items[0]
    assert set(top) >= {"train_no", "train", "board", "operator", "route", "n", "journeys",
                        "on_time_pct", "mean", "median"}
    assert top["n"] >= 10
    # 100% trains with more journeys first
    assert [x["train_no"] for x in items][:2] == [101, 103]


def test_unknown_delay_journeys_do_not_count_toward_the_minimum(store):
    store._conn.execute("DELETE FROM services")
    for d in range(7, 14):
        add(store._conn, "arrival", 106, d, "10:00", 0)
    for d in range(14, 21):
        add(store._conn, "arrival", 106, d, "10:00", 0, state="unknown")   # 14 journeys, 7 with a read
    r = run(store)
    assert r["items"] == [] and r["status"] == "empty"


def test_empty_database_and_below_minimum_are_the_empty_state_not_zeros(store):
    store._conn.execute("DELETE FROM services")
    r = run(store)
    assert r["status"] == "empty" and r["items"] == [] and r["message_key"] == "stats.sp3.reliable.empty"


def test_board_period_and_filters(store):
    store._conn.execute("DELETE FROM services")
    seed(store._conn)
    only_dep = run(store, p=stats.Params(on_time=5, min_sample=3, board="departure"))
    assert [x["train_no"] for x in only_dep["items"]] == [103]
    assert run(store, filters={"operator": "Op2"})["items"][0]["train_no"] == 102
    week = run(store, p=stats.Params(on_time=5, min_sample=3, date_from=cmp.window(TODAY)["now"][0],
                                     date_to=TODAY))
    assert week["items"] == []   # at most 7 journeys each in the last 7 days
