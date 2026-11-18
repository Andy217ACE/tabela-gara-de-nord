# © 2026 Andy217Ace
"""Statistici v3 sp3 (5/5): `/api/stats/heatmap` — mean delay by weekday (0-6) and hour (0-23), one
common scale for both boards. Under 7 days of data: „date insuficiente”, no cells."""
from app import stats, stats_compare as cmp, stats_heatmap as hm
from tests.test_stats_overview import add, store  # noqa: F401
from tests.test_stats_v3_sp3_changes import P, TODAY


def run(store, p=P, filters=None):
    cmp.clear_cache()
    return hm.heatmap(store, p, filters or {}, TODAY)


def seed(c):
    # 2026-10-14 is a Wednesday (2); 14 days of data: weekdays repeat twice
    for d in range(7, 21):
        add(c, "arrival", 1, d, "08:10", 4)          # every day 08h: mean 4
    for d in (14,):                                   # Wednesday 14h arrival: one journey, 30 min
        add(c, "arrival", 2, d, "14:00", 30)
    for d in (7, 14):                                 # two Wednesdays at 18h: mean 20
        add(c, "arrival", 3, d, "18:00", 10)
        add(c, "arrival", 3, d, "18:30", 30)
    for d in range(7, 21):
        add(c, "departure", 9, d, "08:15", 10)        # departures mean 10 at 08h


def test_shape_all_cells_two_boards(store):
    store._conn.execute("DELETE FROM services")
    seed(store._conn)
    r = run(store)
    assert r["status"] == "ok" and set(r["boards"]) == {"arrival", "departure"}
    for b in ("arrival", "departure"):
        cells = r["boards"][b]
        assert len(cells) == 7 * 24
        assert {(c["d"], c["h"]) for c in cells} == {(d, h) for d in range(7) for h in range(24)}
        assert set(cells[0]) >= {"d", "h", "journeys", "n", "mean", "median", "sufficient"}
    assert r["days"] == list(range(7)) and r["hours"] == list(range(24))


def test_cell_figures_and_missing_is_none_not_zero(store):
    store._conn.execute("DELETE FROM services")
    seed(store._conn)
    r = run(store)
    arr = {(c["d"], c["h"]): c for c in r["boards"]["arrival"]}
    c = arr[(2, 8)]                      # two Wednesdays at 08h, delay 4
    assert c["n"] == 2 and c["mean"] == 4.0 and c["journeys"] == 2
    assert arr[(2, 14)]["n"] == 1 and arr[(2, 14)]["mean"] == 30.0 and not arr[(2, 14)]["sufficient"]
    empty = arr[(0, 3)]
    assert empty["journeys"] == 0 and empty["n"] == 0 and empty["mean"] is None


def test_common_scale_spans_both_boards_and_ignores_small_cells(store):
    store._conn.execute("DELETE FROM services")
    c = store._conn
    for d in range(7, 21):
        add(c, "arrival", 1, d, "08:10", 4)
        add(c, "departure", 9, d, "08:15", 10)
        add(c, "departure", 9, d, "09:15", 25)
    add(c, "arrival", 2, 14, "14:00", 90)    # a single huge delay: below min_sample, not in the scale
    r = run(store, p=stats.Params(on_time=5, min_sample=2))   # each weekday-hour cell has 2 journeys
    assert r["scale"]["min"] == 0 and r["scale"]["max"] == 25.0
    assert r["scale"]["unit"] == "min"


def test_scale_is_none_without_a_sufficient_cell(store):
    store._conn.execute("DELETE FROM services")
    c = store._conn
    for d in range(7, 21):
        add(c, "arrival", 1, d, f"{d % 20:02d}:00", 4)      # a different hour each day: n=1 per cell
    r = run(store, p=stats.Params(on_time=5, min_sample=5))
    assert r["status"] == "ok" and r["scale"]["max"] is None


def test_under_seven_days_is_insufficient(store):
    store._conn.execute("DELETE FROM services")
    for d in (19, 20):
        add(store._conn, "arrival", 1, d, "10:00", 3)
    r = run(store)
    assert r["status"] == "insufficient" and r["message_key"] == "stats.sp3.insufficient"
    assert r["boards"] == {} and r["scale"] is None
    assert r["history"]["days"] == 2


def test_empty_database(store):
    store._conn.execute("DELETE FROM services")
    r = run(store)
    assert r["status"] == "insufficient" and r["boards"] == {}


def test_period_board_and_filters(store):
    store._conn.execute("DELETE FROM services")
    seed(store._conn)
    only = run(store, p=stats.Params(on_time=5, min_sample=3, board="departure"))
    assert set(only["boards"]) == {"departure"}
    r = run(store, filters={"operator": "Nobody"})
    assert all(c["journeys"] == 0 for c in r["boards"]["arrival"])
    week = run(store, p=stats.Params(on_time=5, min_sample=3, date_from=cmp.window(TODAY)["now"][0],
                                     date_to=TODAY))
    arr = {(c["d"], c["h"]): c for c in week["boards"]["arrival"]}
    assert arr[(2, 8)]["n"] == 1     # one Wednesday in the last 7 days
