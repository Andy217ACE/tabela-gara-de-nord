# © 2026 Andy217Ace
"""Statistici — „Întârzieri în trepte” și „Număr de modificări” (app.stats_steps).
Rules under test: values per journey come from delay events (cronological); a bounce
A -> B -> A is OCR noise and is removed (counted apart); decreases are shown apart from
the steps up; the first value is a step from 0; below the minimum sample no percentages."""
from datetime import date

from app import stats, stats_steps as ss, stats_overview as so

P = stats.Params(on_time=5, min_sample=3)
_ids = iter(range(1, 100000))


def J(board="arrival", no=1000, final=0, day=21, station="BRASOV", sid=None):
    return {"id": sid or next(_ids), "board": board, "service_date": f"2026-10-{day:02d}",
            "train_type": "IR", "train_no": no, "station": station, "sched_time": "10:00",
            "result": {"state": "confirmed", "delay_known": True, "observed_delay": final}}


def ev(*vals, t0=0, gap=10):
    """Delay events with the given `new` values, `gap` minutes apart (old is always None)."""
    return [{"old": None, "new": v, "ts": f"2026-10-21T{(t0 + i * gap) // 60 + 8:02d}:{(t0 + i * gap) % 60:02d}:00+03:00"}
            for i, v in enumerate(vals)]


def run(pairs, board="arrival"):
    js = [j for j, _ in pairs]
    events = {j["id"]: e for j, e in pairs if e}
    return ss.build(js, [board], P, events)[board]


# ---- clean series ----------------------------------------------------------------------------

def test_series_drops_bounce_and_duplicates():
    vals, bounces = ss.clean_series(ev(5, 10, 5, 15))
    assert vals == [5, 15] and bounces == 1
    vals, bounces = ss.clean_series(ev(5, 5, 10))
    assert vals == [5, 10] and bounces == 0
    vals, _ = ss.clean_series([{"old": None, "new": "x", "ts": "2026-10-21T08:00:00+03:00"}])
    assert vals == []


def test_series_returns_timestamps():
    pts, _ = ss.clean_points(ev(5, 10, gap=7))
    assert [v for v, _t in pts] == [5, 10]
    assert (pts[1][1] - pts[0][1]).total_seconds() == 7 * 60


# ---- steps ----------------------------------------------------------------------------------

def test_step_matrix_and_sizes():
    j1, j2, j3 = J(final=10), J(final=15), J(final=5)
    d = run([(j1, ev(5, 10)), (j2, ev(5, 10, 15)), (j3, ev(5))])
    pairs = {(x["from"], x["to"]): x["n"] for x in d["steps"]["matrix"]}
    assert pairs == {(0, 5): 3, (5, 10): 2, (10, 15): 1}
    assert d["steps"]["n_steps"] == 6 and d["steps"]["median_size"] == 5
    assert d["steps"]["sizes"][0] == {"size": 5, "n": 6}
    assert d["steps"]["median_gap_min"] == 10 and d["steps"]["gap_n"] == 3


def test_decreases_are_separate():
    d = run([(J(final=5), ev(15, 5)), (J(final=5), ev(10)), (J(final=5), ev(10))])
    assert d["steps"]["downs"] == 1 and d["steps"]["ups"] == 3
    assert all(x["to"] > x["from"] for x in d["steps"]["matrix"])
    assert d["steps"]["down_median"] == 10


def test_first_share_announced_vs_added():
    # final 20: announced 5 first (added 15); final 10: announced 10 (complete); final 10: 5 then 10
    d = run([(J(final=20), ev(5, 20)), (J(final=10), ev(10)), (J(final=10), ev(5, 10))])
    fs = d["steps"]["first_share"]
    assert fs["n"] == 3 and fs["complete"] == 1 and fs["later"] == 2
    assert fs["announced_min"] == 20 and fs["final_min"] == 40  # 5+10+5 of 20+10+10
    assert fs["announced_pct"] == 50.0 and fs["added_median"] == 10


def test_small_sample_has_no_percentages():
    d = run([(J(final=5), ev(5))])
    assert d["steps"]["sufficient"] is False
    assert d["steps"]["first_share"]["announced_pct"] is None


def test_suspect_misread_values_ignored():
    # "410 -> 10": 410 was a misread "+"; it must not become a step
    evs = [{"old": None, "new": 410, "ts": "2026-10-21T08:00:00+03:00"},
           {"old": 410, "new": 10, "ts": "2026-10-21T08:10:00+03:00"}]
    d = run([(J(final=10), evs)] * 3)
    assert {(x["from"], x["to"]) for x in d["steps"]["matrix"]} == {(0, 10)}


# ---- changes per journey --------------------------------------------------------------------

def test_histogram_buckets_and_mean_max():
    pairs = [(J(), []), (J(final=5), ev(5)), (J(final=10), ev(5, 10)),
             (J(final=15), ev(5, 10, 15)), (J(final=20), ev(5, 10, 15, 20)),
             (J(final=25), ev(5, 10, 15, 20, 25, 30))]
    d = run(pairs)["changes"]
    assert [(b["key"], b["n"]) for b in d["hist"]] == [("0", 1), ("1", 1), ("2", 1), ("3", 1), ("4+", 2)]
    assert d["n"] == 6 and d["max"] == 6 and d["mean"] == round(16 / 6, 2)


def test_top_trains_sorted_with_route():
    pairs = [(J(no=1, station="CLUJ", final=10), ev(5, 10, 15, 20)),
             (J(no=2, station="IASI", final=5), ev(5)),
             (J(no=3, station="ARAD", final=10), ev(5, 10, 15))]
    top = run(pairs)["changes"]["top"]
    assert [t["train_no"] for t in top] == [1, 3]   # a single change is not a top case
    assert top[0]["changes"] == 4 and top[0]["station"] == "CLUJ"
    assert top[0]["href"] == "#tren?nr=1"


def test_bounces_counted_not_as_changes():
    d = run([(J(final=5), ev(5, 10, 5))])["changes"]
    assert d["hist"][1]["n"] == 1 and d["bounces"] == 1


def test_arrivals_and_departures_never_mixed():
    a, b = J("arrival", final=5), J("departure", final=5)
    out = ss.build([a, b], ["arrival", "departure"], P, {a["id"]: ev(5), b["id"]: ev(5, 10, 15)})
    assert out["arrival"]["changes"]["max"] == 1 and out["departure"]["changes"]["max"] == 3


def test_empty():
    d = run([])
    assert d["changes"]["n"] == 0 and d["changes"]["mean"] is None and d["steps"]["matrix"] == []


def test_overview_payload_has_steps():
    e = so.empty_extra()
    e["history"] = {"first": "2026-10-21", "last": "2026-10-24", "days": 4}
    j = J(final=5)
    e["delay_events"] = {j["id"]: ev(5)}
    out = so.build([dict(j, operator="CFR", last_platform=None, uncertain=0, status="gone")],
                   [], e, P, date(2026, 10, 24), {})
    assert out["steps"]["arrival"]["changes"]["n"] == 1
