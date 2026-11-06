# © 2026 Andy217Ace
"""Comparație pe zilele săptămânii: prag de încredere (N apariții distincte), ziua curentă
parțială nu se numără, sosiri/plecări separate, fără valori înșelătoare sub prag."""
from datetime import date, timedelta
from pathlib import Path

from app import stats, stats_weekdays as wd
from app import stats_overview as so

P = stats.Params(on_time=5, min_sample=5)
TODAY = date(2026, 12, 2)            # miercuri
WEB = Path(__file__).resolve().parent.parent / "web"


def jr(board, day, delay, *, t="12:00", state="confirmed", known=True):
    return {"board": board, "service_date": day.isoformat(), "sched_time": t,
            "result": {"state": state, "delay_known": known, "observed_delay": delay}}


def mondays(n, end=date(2026, 11, 30)):
    return [end - timedelta(days=7 * i) for i in range(n)]


def day(d, board="arrival", delays=(0, 2, 10, 40, 3, 1)):
    return [jr(board, d, x) for x in delays]


def get(res, board, d):
    return res["boards"][board][d]


def test_constant_documented():
    assert wd.MIN_APPEARANCES == 4
    assert "N=4" in (wd.__doc__ or "")


def test_below_threshold_collecting_message_and_weeks():
    js = [j for m in mondays(3) for j in day(m)]
    r = wd.build(js, ["arrival", "departure"], P, TODAY)
    assert r["status"] == "collecting" and r["weeks"] == 3
    assert r["min_appearances"] == 4
    assert "după ~4 săptămâni" in r["message"]
    mon = get(r, "arrival", 0)
    assert mon["appearances"] == 3 and mon["reliable"] is False
    assert mon["on_time_pct"] is None and mon["median"] is None and mon["over_30_pct"] is None
    assert mon["journeys"] == 18          # numărul brut rămâne vizibil


def test_empty_is_collecting_zero_weeks():
    r = wd.build([], ["arrival", "departure"], P, TODAY)
    assert r["status"] == "collecting" and r["weeks"] == 0
    assert all(len(r["boards"][b]) == 7 for b in ("arrival", "departure"))


def test_above_threshold_values_and_other_days_insufficient():
    js = [j for m in mondays(4) for j in day(m)] + day(date(2026, 11, 25))   # 4 luni, 1 miercuri
    r = wd.build(js, ["arrival", "departure"], P, TODAY)
    assert r["status"] == "ok" and r["weeks"] == 4 and r["message"] is None
    mon = get(r, "arrival", 0)
    assert mon["reliable"] and mon["appearances"] == 4 and mon["journeys"] == 24
    # delays per day: 0,2,10,40,3,1 -> on-time (<=5): 4/6
    assert mon["on_time_pct"] == round(100 * 4 / 6, 1)
    assert mon["over_30_pct"] == round(100 / 6, 1)
    assert mon["median"] == 2.5
    assert mon["per_day"] == 6
    wed = get(r, "arrival", 2)
    assert wed["appearances"] == 1 and wed["reliable"] is False and wed["on_time_pct"] is None
    # plecările nu se amestecă cu sosirile
    assert get(r, "departure", 0)["journeys"] == 0 and get(r, "departure", 0)["reliable"] is False


def test_boards_never_mixed():
    js = [j for m in mondays(4) for j in day(m, "arrival")] + \
         [j for m in mondays(4) for j in day(m, "departure", (30, 40, 50, 60, 70, 80))]
    r = wd.build(js, ["arrival", "departure"], P, TODAY)
    assert get(r, "arrival", 0)["on_time_pct"] > 50
    assert get(r, "departure", 0)["on_time_pct"] == 0
    assert get(r, "departure", 0)["over_30_pct"] == round(100 * 5 / 6, 1)   # 30 nu e „peste 30”


def test_current_day_is_partial_not_an_appearance():
    wednesdays = [TODAY - timedelta(days=7 * i) for i in range(1, 4)]   # 3 miercuri complete
    js = [j for w in wednesdays for j in day(w)] + day(TODAY)           # + azi (a 4-a, parțială)
    r = wd.build(js, ["arrival"], P, TODAY)
    wed = get(r, "arrival", 2)
    assert wed["appearances"] == 3 and wed["reliable"] is False
    assert wed["journeys"] == 18                  # datele de azi nu intră în cifre
    assert wed["partial_today"] is True and r["today_weekday"] == 2
    assert r["status"] == "collecting" and r["weeks"] == 3
    # a doua zi (joi) miercurea de ieri e completă -> 4 apariții
    r2 = wd.build(js, ["arrival"], P, TODAY + timedelta(days=1))
    assert get(r2, "arrival", 2)["appearances"] == 4 and get(r2, "arrival", 2)["reliable"]
    assert r2["status"] == "ok"


def test_unknown_delay_not_zero_and_min_sample_withholds_pct():
    js = []
    for m in mondays(4):                  # 1 călătorie citită + 1 cu întârziere necunoscută pe zi
        js += [jr("arrival", m, 7), jr("arrival", m, 0, state="unknown", known=False)]
    mon = get(wd.build(js, ["arrival"], P, TODAY), "arrival", 0)
    assert mon["reliable"] and mon["journeys"] == 8 and mon["n"] == 4
    assert mon["median"] == 7
    assert mon["on_time_pct"] is None     # n=4 < min_sample=5: procentele rămân ascunse


def test_integrated_in_overview_payload(tmp_path):
    """Prin /api/stats/overview (store real): cheia `weekdays` există, ziua de azi nu intră."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from app.store import Store
    tz = ZoneInfo("Europe/Bucharest")
    s = Store(str(tmp_path / "w.db"))
    s.migrate()
    c = s._conn
    for k, d in enumerate(mondays(4) + [TODAY]):
        sched = datetime(d.year, d.month, d.day, 12, 0, tzinfo=tz)
        sid = c.execute(
            "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
            " sched_time, first_seen, last_seen, last_delay, status, uncertain, delay_read_at)"
            " VALUES ('arrival',?,'IR',?,'BRASOV','CFR Calatori','12:00',?,?,3,'gone',0,?)",
            (d.isoformat(), 100 + k, (sched - timedelta(hours=1)).isoformat(),
             (sched + timedelta(minutes=3)).isoformat(), (sched + timedelta(minutes=1)).isoformat())).lastrowid
        c.execute("INSERT INTO events(service_id, ts, kind) VALUES (?,?,'appeared')",
                  (sid, (sched - timedelta(hours=1)).isoformat()))
        c.execute("INSERT INTO events(service_id, ts, kind) VALUES (?,?,'gone')",
                  (sid, (sched + timedelta(minutes=6)).isoformat()))
    c.commit()
    so.clear_cache()
    d = so.overview(s, P, {}, today=TODAY)
    s.close()
    w = d["weekdays"]
    assert w["status"] == "ok" and w["weeks"] == 4
    assert w["boards"]["arrival"][0]["appearances"] == 4
    assert w["boards"]["arrival"][2]["appearances"] == 0      # azi (miercuri) nu e apariție
    assert w["boards"]["arrival"][2]["partial_today"] is True
    empty = so.build([], [], so.empty_extra(), P, TODAY, {})
    assert empty["weekdays"]["status"] == "collecting"


def test_frontend_static_csp_safe_and_wired():
    js = (WEB / "stat_weekdays.js").read_text(encoding="utf-8")
    for bad in ("eval(", "new Function", "innerHTML", "setAttribute(\"style\"", "unsafe"):
        assert bad not in js
    assert "Comparația va deveni valabilă după ~4 săptămâni de date" in js
    assert "date insuficiente" in js
    assert "stat_weekdays.js" in (WEB / "index.html").read_text(encoding="utf-8")
    assert "statWeekdays" in (WEB / "statistici.js").read_text(encoding="utf-8")
    assert "/stat_weekdays.js" in (WEB / "sw.js").read_text(encoding="utf-8")
