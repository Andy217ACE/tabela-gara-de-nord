# © 2026 Andy217Ace
"""Statistici — „Probleme” (app.stats_problems): deterministic findings on synthetic data.
Rules under test: median (not mean) ranks groups; >= 2 trains per group; recurrent = >= 3
days late on every day; below the minimum sample no percentages / no items; a trend needs
>= 7 days; partial days and reading gaps are reported; links point to train/station/day."""
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import stats, stats_overview as so, stats_problems as sp
from app.store import Store

BUC = ZoneInfo("Europe/Bucharest")
P = stats.Params(on_time=5, min_sample=5)
TODAY = date(2026, 10, 24)
_ids = iter(range(1, 100000))


def J(board, no, day, t, delay, *, station="BRASOV", ttype="IR", operator="CFR Calatori",
      state="confirmed", sid=None):
    """One public journey as stats_overview.fetch() returns it (with `result`)."""
    known = state != "unknown"
    return {"id": sid or next(_ids), "board": board, "service_date": f"2026-10-{day:02d}",
            "train_type": ttype, "train_no": no, "station": station, "operator": operator,
            "sched_time": t, "status": "listed" if state == "in_progress" else "gone",
            "uncertain": 0, "last_platform": None,
            "result": {"state": state, "delay_known": known,
                       "observed_delay": delay if known else None}}


def extra(days=4, **kw):
    e = so.empty_extra()
    e["history"] = {"first": "2026-10-21", "last": "2026-10-24", "days": days}
    e.update(kw)
    return e


def build(js, boards=("arrival", "departure"), p=P, **kw):
    return sp.build(js, list(boards), p, extra(**kw), TODAY)


def town(board, station, delays, *, no0=100, days=(21, 22, 23), t="10:00", ttype="IR"):
    """`len(delays)` trains to/from `station`, each seen on `days` with the given delay."""
    return [J(board, no0 + k, d, t, v, station=station, ttype=ttype)
            for k, v in enumerate(delays) for d in days]


# ---- small pieces ---------------------------------------------------------------------------

def test_severity_and_score():
    assert sp.severity_of(None) == "mică" and sp.severity_of(10) == "mică"
    assert sp.severity_of(15) == "medie" and sp.severity_of(30) == "mare"
    assert sp.score("mare", "ridicată", 25) == 15.0
    assert sp.score("mare", "ridicată", 25) > sp.score("mare", "medie", 25) > \
        sp.score("medie", "medie", 25) > sp.score("medie", "medie", 4)
    assert sp.score("mică", "scăzută", 0) == 0


def test_below_minimum_sample_no_items_no_percent():
    js = [J("arrival", 1, 21, "08:00", 40), J("arrival", 2, 22, "08:00", 50),
          J("departure", 3, 21, "09:00", 0)]
    d = build(js)
    assert d["status"] == "insufficient" and d["items"] == [] and d["good"] == []
    assert "Date insuficiente" in d["message"]
    a = d["boards"]["arrival"]
    assert a["n"] == 2 and a["on_time_pct"] is None and a["sufficient"] is False
    assert d["routes"]["arrival"]["worst"] == [] and d["routes"]["arrival"]["below_min"] == 1
    assert all(w["over_15_pct"] is None for w in d["windows"]["arrival"])
    json.dumps(d)  # serialisable


def test_missing_delay_is_not_zero():
    js = town("arrival", "PITESTI", [30, 40]) + [
        J("arrival", 900, 21, "10:00", None, station="PITESTI", state="unknown"),
        J("arrival", 901, 21, "10:00", None, station="PITESTI", state="in_progress")]
    d = build(js, boards=["arrival"])
    assert d["boards"]["arrival"]["n"] == 6 and d["boards"]["arrival"]["on_time"] == 0
    assert d["coverage"]["unknown"] == 1 and d["coverage"]["in_progress"] == 1


# ---- ranking -------------------------------------------------------------------------------

def test_routes_ranked_by_median_not_mean():
    # CLUJ: one 390-min case among punctual trains (mean 66, median 5);
    # PITESTI: consistently late (mean = median = 35)
    js = town("arrival", "CLUJ NAPOCA", [0, 5], no0=100) + \
        [J("arrival", 199, 21, "23:56", 390, station="CLUJ NAPOCA")] + \
        town("arrival", "PITESTI", [35, 35], no0=200)
    d = build(js, boards=["arrival"])
    worst = d["routes"]["arrival"]["worst"]
    assert [r["key"] for r in worst] == ["PITESTI", "CLUJ NAPOCA"]
    route_items = [i for i in d["items"] if i["kind"] == "route"]
    assert [i["links"][0]["href"] for i in route_items] == ["#statie?nume=PITESTI&board=arrival"]
    assert d["big"]["arrival"]["top"][0]["delay"] == 390


def test_group_needs_two_trains():
    js = [J("arrival", 7, d, "10:00", 45, station="ADJUD") for d in range(17, 24)] + \
        town("arrival", "BRASOV", [0, 10])
    d = build(js, boards=["arrival"])
    r = d["routes"]["arrival"]
    assert r["single_train"] == 1 and [x["key"] for x in r["worst"]] == ["BRASOV"]


def test_recurrent_trains_raw_counts():
    js = ([J("arrival", 9256, d, "17:02", v, station="PITESTI", ttype="RE")
           for d, v in ((21, 90), (22, 65), (23, 45))]
          + [J("arrival", 1, d, "08:00", v) for d, v in ((21, 20), (22, 0), (23, 30))]  # 2 of 3
          + [J("arrival", 2, d, "09:00", 60) for d in (22, 23)]                          # 2 days
          + [J("departure", 9257, d, "17:37", 10, station="PITESTI") for d in (21, 22, 23)])
    d = build(js)
    rec = d["recurrent"]
    assert rec["seen"] == 3 and rec["count"] == 2  # train 2: too few days; train 1: one on time
    t = rec["trains"][0]
    assert (t["board"], t["train_no"], t["days"], t["late_days"], t["over_15_days"]) == \
        ("arrival", 9256, 3, 3, 3)
    assert [x["delay"] for x in t["delays"]] == [90, 65, 45] and t["median"] == 65
    assert t["confidence"] == "medie"  # 3 days < min sample
    it = next(i for i in d["items"] if i["kind"] == "recurrent")
    assert "%" not in it["figures"] and "3 din 3 zile" in it["figures"]
    assert it["links"][0]["href"] == "#tren?nr=9256"


def test_recurrent_allows_one_on_time_day_from_five_days():
    js = [J("arrival", 5, 17 + k, "07:00", v) for k, v in enumerate([20, 25, 0, 30, 20])]
    rec = sp.recurrent(js, P)
    assert rec["count"] == 1 and rec["trains"][0]["confidence"] == "ridicată"
    js2 = [J("arrival", 5, 17 + k, "07:00", v) for k, v in enumerate([20, 0, 0, 30, 20])]
    assert sp.recurrent(js2, P)["count"] == 0


def test_boards_item_and_mix_note():
    js = (town("arrival", "AEROPORT H COANDA", [0, 0, 0, 0], no0=300, ttype="RM")
          + town("arrival", "PITESTI", [20, 30, 25, 40], no0=400)
          + town("departure", "BRASOV", [0, 0, 0, 0, 5], no0=500))
    d = build(js)
    mix = d["boards"]["arrival"]["mix"]
    assert mix["station"] in ("AEROPORT H COANDA", "PITESTI")
    it = d["items"][0]
    assert it["kind"] == "boards" and it["board"] == "arrival" and it["rank"] == 1
    assert "Sosiri: 12 din 24 la timp (50 %)" in it["figures"]
    assert "fără " in it["figures"]
    assert it["severity"] == "medie" and it["confidence"] == "ridicată"


def test_items_sorted_by_score_and_capped():
    js = (town("arrival", "PITESTI", [35, 40, 45], no0=100)
          + town("arrival", "TARGOVISTE", [25, 30], no0=200, t="17:00")
          + town("arrival", "BRASOV", [0, 0, 5, 0, 0, 0], no0=300, t="12:00")
          + town("departure", "BRASOV", [0, 0, 0, 0, 0], no0=400))
    items = build(js)["items"]
    assert len(items) <= sp.MAX_ITEMS
    assert [i["score"] for i in items] == sorted((i["score"] for i in items), reverse=True)
    assert [i["rank"] for i in items] == list(range(1, len(items) + 1))
    for i in items:
        assert i["severity"] in sp.SEV_W and i["confidence"] in sp.CONF_W and i["n"] > 0
        assert i["title"] and i["figures"] and i["why"]


# ---- windows, episodes, growth, trend, coverage -----------------------------------------------

def test_critical_window_needs_several_days():
    base = town("arrival", "BRASOV", [0, 0, 0, 0, 0, 0], no0=100, t="12:00")
    one_day = [J("arrival", 200 + k, 22, "07:30", 40, station="PITESTI") for k in range(6)]
    d = build(base + one_day, boards=["arrival"])
    w = {x["from_h"]: x for x in d["windows"]["arrival"]}
    assert w[6]["n"] == 6 and w[6]["late_days"] == 1 and w[6]["critical"] is False
    # ...the same day is an episode
    assert d["episodes"] and d["episodes"][0]["date"] == "2026-10-22"
    assert d["episodes"][0]["over_30"] == 6
    ep = next(i for i in d["items"] if i["kind"] == "episode")
    assert ep["links"][0]["href"] == "#istoric?date=2026-10-22&board=arrival"
    spread = [J("arrival", 300 + k, 21 + k % 3, "07:30", 40, station="PITESTI") for k in range(6)]
    d = build(base + spread, boards=["arrival"])
    w = {x["from_h"]: x for x in d["windows"]["arrival"]}
    assert w[6]["critical"] is True and w[6]["over_15_pct"] == 100.0


def test_growth_after_first_announcement_ignores_misread():
    js = [J("arrival", 1, 21, "08:00", 30, sid=1), J("arrival", 2, 21, "08:10", 10, sid=2),
          J("arrival", 3, 21, "08:20", 10, sid=3), J("arrival", 4, 21, "08:30", 0, sid=4)]
    ev = {1: [{"old": "0", "new": "10"}, {"old": "10", "new": "30"}],            # grew +20
          2: [{"old": "0", "new": "10"}],                                       # same
          3: [{"old": "0", "new": "410"}, {"old": "410", "new": "10"}],         # "+10" misread
          4: [{"old": "0", "new": "0"}]}                                        # never > 0
    g = sp.growth(js, P, ev)
    assert (g["n"], g["grew"], g["same"], g["recovered"]) == (3, 1, 2, 0)
    assert g["grew_median"] == 20 and g["grew_pct"] is None and g["sufficient"] is False


def test_trend_insufficient_below_seven_days_and_direction_after():
    js = town("arrival", "BRASOV", [0, 20], days=(21, 22, 23, 24))
    t = build(js, boards=["arrival"], days=4)["trend"]
    assert t["status"] == "insufficient" and t["direction"]["arrival"] is None
    assert [r["partial"] for r in t["boards"]["arrival"]] == [False, False, False, True]
    early = [J("arrival", 10 + k, d, "10:00", 0) for d in range(10, 14) for k in range(6)]
    late = [J("arrival", 10 + k, d, "10:00", 30) for d in range(14, 18) for k in range(6)]
    t = build(early + late, boards=["arrival"], days=8)["trend"]
    assert t["status"] == "ok" and t["direction"]["arrival"]["label"] == "mai rău"
    assert t["direction"]["arrival"]["diff_pp"] == -100.0


def test_coverage_partial_days_and_gaps():
    js = town("arrival", "BRASOV", [0, 5], days=(21, 22, 23, 24))
    gaps = [{"start": "2026-10-22T11:16+03:00", "end": "2026-10-22T12:30+03:00", "minutes": 74}]
    c = build(js, boards=["arrival"], gaps=gaps, low_quality_dates={"2026-10-21": 12})["coverage"]
    assert c["level"] == "parțială" and c["days"] == 4 and c["gaps_count"] == 1
    why = {x["date"]: x["why"] for x in c["partial"]}
    assert why == {"2026-10-21": "12 călătorii excluse, calitate redusă",
                   "2026-10-22": "74 min fără citire", "2026-10-24": "ziua în curs"}
    assert build(js, boards=["arrival"], days=2)["coverage"]["level"] == "insuficientă"
    assert build(js, boards=["arrival"], days=9)["coverage"]["level"] == "bună"


# ---- through /api/stats/overview (database, read-only connection) ----------------------------

@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.migrate()
    c = s._conn
    for k, (no, delay) in enumerate([(9256, 90), (9256, 65), (9256, 45)]):
        sched = datetime(2026, 10, 21 + k, 17, 2, tzinfo=BUC)
        sid = c.execute(
            "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
            " sched_time, first_seen, last_seen, last_delay, status, delay_read_at)"
            " VALUES ('arrival',?,'RE',?,'PITESTI','CFR Calatori','17:02',?,?,?,'gone',?)",
            (sched.date().isoformat(), no, (sched - timedelta(hours=1)).isoformat(),
             (sched + timedelta(minutes=delay)).isoformat(), delay,
             (sched + timedelta(minutes=delay - 2)).isoformat())).lastrowid
        c.execute("INSERT INTO events(service_id, ts, kind) VALUES (?,?,'appeared')",
                  (sid, (sched - timedelta(hours=1)).isoformat()))
        c.execute("INSERT INTO events(service_id, ts, kind, old, new) VALUES (?,?,'delay','0','20')",
                  (sid, (sched - timedelta(minutes=30)).isoformat()))
        c.execute("INSERT INTO events(service_id, ts, kind, old, new) VALUES (?,?,'delay','20',?)",
                  (sid, sched.isoformat(), str(delay)))
        c.execute("INSERT INTO events(service_id, ts, kind) VALUES (?,?,'gone')",
                  (sid, (sched + timedelta(minutes=delay + 3)).isoformat()))
    t0 = datetime(2026, 10, 22, 10, 0, tzinfo=BUC)
    for m in (0, 1, 2, 40, 41):  # one pause of 38 min between two successful readings
        c.execute("INSERT INTO runs(ts, image_hash, ok, n_rows) VALUES (?, '', 1, 10)",
                  ((t0 + timedelta(minutes=m)).isoformat(),))
    c.execute("INSERT INTO runs(ts, image_hash, ok, n_rows) VALUES (?, '', 0, 0)",
              ((t0 + timedelta(minutes=20)).isoformat(),))  # a failed reading is no reading
    c.commit()
    so.clear_cache()
    yield s
    s.close()


def test_overview_has_problems_from_database(store):
    d = so.overview(store, P, {}, today=TODAY)
    pr = d["problems"]
    assert pr["recurrent"]["count"] == 1 and pr["recurrent"]["trains"][0]["train_no"] == 9256
    assert pr["coverage"]["gaps"] == [{"start": "2026-10-22T10:02+03:00",
                                       "end": "2026-10-22T10:40+03:00", "minutes": 38}]
    g = pr["growth"]["arrival"]
    assert (g["n"], g["grew"]) == (3, 3) and g["grew_median"] == 45
    # below the minimum sample at the board level: no items, no percentages
    assert pr["status"] == "insufficient" and pr["items"] == []
    json.dumps(d)


def test_overview_problems_follow_filters(store):
    day = date(2026, 10, 23)
    p = stats.Params(on_time=5, min_sample=5, date_from=day, date_to=day)
    d = so.overview(store, p, {"perioada": "1"}, today=day)
    assert d["problems"]["recurrent"]["count"] == 0  # one day cannot show recurrence
    assert d["problems"]["coverage"]["gaps"] == []    # the pause was on 22.10
