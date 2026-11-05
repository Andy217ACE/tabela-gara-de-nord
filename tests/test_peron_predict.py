# © 2026 Andy217Ace
"""Predicția peronului (Val 5b, peron): ierarhie, praguri, zgomot OCR, linie de bază,
backtest temporal, poartă, fără scriere în DB."""
import sqlite3
from datetime import date, timedelta

import pytest

from app import peron_predict as PP
from app import quality as dq


def C(i, train=100, station="Iași", board="departure", day="2026-10-05", sched="08:00",
      platform=5):
    return PP.Case(i, day, train, station, board, sched, platform)


def mondays(n, last="2026-10-05"):
    """n lunele consecutive, cea mai recentă la `last` (ambele sunt lunei)."""
    d0 = date.fromisoformat(last)
    return [(d0 - timedelta(days=7 * k)).isoformat() for k in range(n)][::-1]


def days_from(start, n):
    """n zile consecutive, de la `start` (nivelul (a) nu depinde de ziua săptămânii)."""
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=k)).isoformat() for k in range(n)]


def pool_of(cases):
    p = PP.Pool()
    for c in cases:
        p.add(c)
    return p


# --- ierarhie și praguri ----------------------------------------------------------

def test_level_a_needs_five_readings_at_sixty_percent():
    days = mondays(5, last="2026-10-05")  # 5 luni, aceeași stație, același tren
    p = pool_of([C(i, day=d, platform=5 if i < 3 else 6) for i, d in enumerate(days)])
    pred = p.predict(C(99, day="2026-10-12"))  # 3/5 = 60%
    assert pred is not None and pred.basis == "a"
    assert pred.platform == 5 and pred.n == 5 and pred.share == pytest.approx(0.6)


def test_level_a_no_prediction_below_five_readings():
    days = mondays(4)
    p = pool_of([C(i, day=d) for i, d in enumerate(days)])  # 4 citiri, toate 5
    assert p.predict(C(99, day="2026-10-12")) is None


def test_level_a_no_prediction_below_sixty_percent():
    days = days_from("2026-09-01", 17)  # 10 de 5 și 7 de 6: 10/17 = 58,8%
    cases = [C(i, day=d, platform=5 if i < 10 else 6) for i, d in enumerate(days)]
    assert pool_of(cases).predict(C(99, day="2026-10-12")) is None


def test_share_exactly_sixty_percent_predicts():
    days = days_from("2026-09-01", 10)  # 6 de 5 și 4 de 6: 6/10 = 60%
    cases = [C(i, day=d, platform=5 if i < 6 else 6) for i, d in enumerate(days)]
    pred = pool_of(cases).predict(C(99, day="2026-10-12"))
    assert pred is not None and pred.platform == 5


def test_tie_gives_no_prediction():
    days = days_from("2026-09-01", 10)  # 5 de 5 și 5 de 6: nu există peron dominant
    cases = [C(i, day=d, platform=5 if i < 5 else 6) for i, d in enumerate(days)]
    assert pool_of(cases).predict(C(99, day="2026-10-12")) is None


def test_level_a_window_is_sixty_days():
    old = [f"2026-07-0{k}" for k in range(1, 9)]  # ieșite din fereastra de 60 de zile
    recent = mondays(5, last="2026-10-05")
    cases = ([C(i, day=d, platform=5) for i, d in enumerate(old)]
             + [C(100 + i, day=d, platform=6) for i, d in enumerate(recent)])
    pred = pool_of(cases).predict(C(999, day="2026-10-12"))
    assert pred is not None and pred.basis == "a" and pred.platform == 6 and pred.n == 5


def test_level_b_station_hour_weekday_with_twenty_readings():
    days = mondays(20, last="2026-10-05")  # 20 de luni, trenuri diferite (fără nivelul a)
    cases = [C(i, train=200 + i, day=d, sched=f"08:{i:02d}", platform=5)
             for i, d in enumerate(days)]
    pred = pool_of(cases).predict(C(999, train=999, day="2026-11-02", sched="08:30"))
    assert pred is not None and pred.basis == "b" and pred.n == 20 and pred.platform == 5


def test_level_b_below_twenty_gives_no_prediction():
    days = mondays(19, last="2026-10-05")
    cases = [C(i, train=200 + i, day=d, sched=f"08:{i:02d}") for i, d in enumerate(days)]
    assert pool_of(cases).predict(C(999, train=999, day="2026-11-02", sched="08:30")) is None


def test_level_b_hour_bucket_separates_hours():
    days = mondays(20, last="2026-10-05")
    cases = [C(i, train=200 + i, day=d, sched="09:00") for i, d in enumerate(days)]
    assert pool_of(cases).predict(C(999, train=999, day="2026-11-02", sched="08:30")) is None


# --- zgomot OCR -------------------------------------------------------------------

def test_ocr_noise_does_not_flip_a_clear_majority():
    days = days_from("2026-09-01", 13)  # 10 citiri de 5 și 3 confuzii 5→6
    cases = [C(i, day=d, platform=5 if i < 10 else 6) for i, d in enumerate(days)]
    pred = pool_of(cases).predict(C(99, day="2026-09-15"))
    assert pred is not None and pred.platform == 5 and pred.n == 13


def test_ocr_noise_below_threshold_gives_no_prediction_not_a_wrong_one():
    days = days_from("2026-09-01", 9)  # 5 de 5 și 4 confuzii 5→6: 5/9 = 55%
    cases = [C(i, day=d, platform=5 if i < 5 else 6) for i, d in enumerate(days)]
    assert pool_of(cases).predict(C(99, day="2026-09-15")) is None


# --- linia de bază ----------------------------------------------------------------

def test_baseline_is_last_platform_from_an_earlier_day():
    p = pool_of([C(1, day="2026-10-03", platform=4), C(2, day="2026-10-04", platform=7),
                 C(3, day="2026-10-05", platform=9)])
    assert p.baseline(C(99, day="2026-10-05")) == 7  # ziua curentă nu contează


def test_baseline_is_none_without_history_for_same_train_station_board():
    p = pool_of([C(1, train=100, day="2026-10-04", platform=7)])
    assert p.baseline(C(99, train=101, day="2026-10-05")) is None
    assert p.baseline(C(99, train=100, board="arrival", day="2026-10-05")) is None


# --- backtest temporal ------------------------------------------------------------

def test_walk_forward_predicts_only_from_earlier_days():
    day1 = [C(i, train=100 + i, day="2026-10-05") for i in range(10)]
    day2 = [C(50 + i, train=100 + i, day="2026-10-06") for i in range(10)]
    evals = {e.service_id: e for e in PP.walk_forward(day1 + day2)}
    assert all(evals[i].prediction is None for i in range(10))  # nimic înainte de ziua 1


def test_walk_forward_ignores_future_days():
    days = mondays(12)
    base = [C(i, day=d, platform=5) for i, d in enumerate(days)]
    future = [C(500 + i, day="2027-01-04", platform=9) for i in range(20)]
    before = {e.service_id: e.prediction for e in PP.walk_forward(base)}
    after = {e.service_id: e.prediction for e in PP.walk_forward(base + future)
             if e.service_id in before}
    assert before == after


# --- raport și poartă -------------------------------------------------------------

def _ev(i, truth, pred_platform, baseline, day="2026-10-05"):
    pred = None if pred_platform is None else PP.Prediction(pred_platform, 10, 1.0, "a")
    return PP.Evaluation(i, day, truth, pred, baseline)


def test_report_counts_accuracy_baseline_and_confusions():
    evs = [_ev(1, truth=5, pred_platform=5, baseline=6),
           _ev(2, truth=6, pred_platform=5, baseline=6),  # confuzie 5↔6
           _ev(3, truth=5, pred_platform=None, baseline=5)]
    rep = PP.report(evs)
    assert rep["n_cases"] == 3 and rep["n_pred"] == 2 and rep["n_nopred"] == 1
    assert rep["acc_pred"] == 50.0
    assert rep["n_common"] == 2
    assert rep["acc_pred_common"] == 50.0 and rep["acc_base_common"] == 50.0
    assert rep["wrong_pairs_56_38"] == 1
    assert rep["wrong_pairs_share"] == 100.0
    assert rep["by_level"] == {"a": 2, "b": 0}
    assert rep["good_days"] == 1


def test_report_empty_has_no_numbers():
    rep = PP.report([])
    assert rep["n_pred"] == 0 and rep["acc_pred"] is None


def _rep(**kw):
    base = dict(n_pred=100, acc_pred=80.0, n_common=100, acc_pred_common=85.0,
                acc_base_common=80.0)
    base.update(kw)
    return base


def test_gate_refuses_small_backtest():
    assert PP.gate(_rep(n_pred=99)).published is False


def test_gate_refuses_below_eighty_percent():
    assert PP.gate(_rep(acc_pred=79.9)).published is False


def test_gate_refuses_without_five_points_over_baseline():
    assert PP.gate(_rep(acc_pred_common=84.9)).published is False


def test_gate_refuses_without_common_cases():
    assert PP.gate(_rep(n_common=0)).published is False


def test_gate_publishes_only_when_all_hold():
    g = PP.gate(_rep())
    assert g.published is True and "publicat" in g.reason


# --- citire fără scriere ---------------------------------------------------------

def _db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE services (id INTEGER PRIMARY KEY, board TEXT, service_date TEXT,"
        " train_type TEXT, train_no INTEGER, station TEXT, operator TEXT, sched_time TEXT,"
        " first_seen TEXT, last_seen TEXT, last_delay INTEGER NOT NULL DEFAULT 0,"
        " last_platform INTEGER, status TEXT NOT NULL DEFAULT 'listed');"
        "CREATE TABLE events (id INTEGER PRIMARY KEY, service_id INTEGER, ts TEXT,"
        " kind TEXT, old TEXT, new TEXT);"
        "CREATE TABLE observations (id INTEGER PRIMARY KEY, service_id INTEGER,"
        " board TEXT, observed_at TEXT, train_no INTEGER, sched_time TEXT, platform INTEGER,"
        " station TEXT, validation_state TEXT);")
    dq.ensure_schema(conn)
    return conn


def _svc(conn, sid, train=100, day="2026-10-05", sched="08:00", station="Iași"):
    conn.execute("INSERT INTO services (id, board, service_date, train_type, train_no, station,"
                 " operator, sched_time, first_seen, last_seen) VALUES"
                 " (?, 'departure', ?, 'R', ?, ?, 'CFR', ?, '', '')",
                 (sid, day, train, station, sched))


def _obs(conn, sid, platform, state="ok", train=100):
    conn.execute("INSERT INTO observations (service_id, board, observed_at, train_no, sched_time,"
                 " platform, station, validation_state) VALUES (?, 'departure', '', ?, '08:00',"
                 " ?, 'Iași', ?)", (sid, train, platform, state))


def test_load_cases_uses_only_ok_read_platforms_and_skips_ties(tmp_path):
    p = str(tmp_path / "t.db")
    conn = _db(p)
    _svc(conn, 1)  # 5, 5, 6 (ok) -> truth 5
    _obs(conn, 1, 5); _obs(conn, 1, 5); _obs(conn, 1, 6)
    _svc(conn, 2)  # ties 5 / 6 -> exclus
    _obs(conn, 2, 5); _obs(conn, 2, 6)
    _svc(conn, 3)  # doar citiri neconfirmate -> nu intră
    _obs(conn, 3, 7, state="uncertain")
    _svc(conn, 4)  # fără peron citit (NULL) -> nu intră
    _obs(conn, 4, None)
    conn.commit()
    cases = PP.load_cases(conn)
    assert [(c.service_id, c.platform) for c in cases] == [(1, 5)]


def test_predict_path_does_not_write(tmp_path):
    p = str(tmp_path / "t.db")
    conn = _db(p)
    _svc(conn, 1)
    _obs(conn, 1, 5)
    conn.commit()
    ro = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    before = ro.execute("SELECT COUNT(*) FROM observations").fetchone()
    cases = PP.load_cases(ro)
    pool = PP.Pool()
    for c in cases:
        pool.predict(c)
        pool.baseline(c)
    after = ro.execute("SELECT COUNT(*) FROM observations").fetchone()
    assert before == after and ro.total_changes == 0


# --- scriptul de backtest refuză baza de producție --------------------------------

def test_backtest_script_refuses_production_path(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "backtest_peron", Path(__file__).resolve().parent.parent / "scripts" / "backtest_peron.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with pytest.raises(ValueError, match="producție"):
        mod.check_db_path(mod.PRODUCTION_DB)
    copy = tmp_path / "copie.db"
    copy.write_bytes(b"")
    assert mod.check_db_path(str(copy)) == str(copy)
