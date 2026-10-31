# © 2026 Andy217Ace
"""Predicția întârzierii finale (Val 5b): prag, ierarhie, backtest temporal, poartă."""
import sqlite3
from datetime import date, timedelta

import pytest

from app import predict as P
from app import quality as dq


def J(i, train=100, station="Iași", board="departure", day="2026-10-05", sched="08:00",
      final=0, baseline=0):
    return P.Journey(i, train, board, station, day, sched, final, baseline)


def days_from(start, n):
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=k)).isoformat() for k in range(n)]


# --- prag și ierarhie ---------------------------------------------------------------

def test_no_prediction_below_train_threshold():
    # 9 călătorii ale trenului, stația sub 30: nimic afișabil
    train = [J(i, final=5, day=days_from("2026-10-05", 9)[i]) for i in range(9)]
    pool = P.build_pool(train)
    assert P.predict_final(pool, J(99, day="2026-10-20")) is None


def test_level_a_same_train_same_weekday():
    # 2026-10-05 e luni; 10 zile de luni (7 zile la rând = 1 luni la 7 zile): 10 la același tren
    mondays = [(date(2026, 10, 5) + timedelta(days=7 * k)).isoformat() for k in range(10)]
    pool = P.build_pool([J(i, final=10, day=d) for i, d in enumerate(mondays)])
    p = P.predict_final(pool, J(99, day="2026-11-02"))  # luni
    assert p is not None and p.basis == "a" and p.n == 10 and p.delay_min == 10


def test_level_b_same_train_other_weekday():
    days = days_from("2026-10-05", 10)  # zile consecutive: toate zilele săptămânii
    pool = P.build_pool([J(i, final=f, day=d) for i, (d, f) in enumerate(zip(days, range(10)))])
    # ziua din afara celor 10 apare de 1 dată pe grupă de zi a săptămânii: cade la nivelul (b)
    p = P.predict_final(pool, J(99, day="2026-10-15"))
    assert p is not None and p.basis == "b" and p.n == 10
    assert p.delay_min == pytest.approx(4.5)


def test_level_c_station_when_train_has_few():
    # trenul are 3 călătorii; stația, oră și zi a săptămânii au 30 (4 săptămâni de luni)
    mondays = [(date(2026, 10, 5) + timedelta(days=7 * k)).isoformat() for k in range(30)]
    train = [J(i, train=500 + i, final=20, day=d) for i, d in enumerate(mondays)]
    few = [J(100 + i, train=777, final=0, day=mondays[i]) for i in range(3)]
    pool = P.build_pool(train + few)
    p = P.predict_final(pool, J(999, train=777, day="2026-11-02"))
    # grupa stației: 30 de călătorii cu 20 min și 3 cu 0 min (trenul 777) -> n=33, mediana 20
    assert p is not None and p.basis == "c" and p.n == 33 and p.delay_min == 20


def test_interval_is_quartiles():
    days = days_from("2026-10-05", 12)
    finals = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    pool = P.build_pool([J(i, final=f, day=d) for i, (d, f) in enumerate(zip(days, finals))])
    p = P.predict_final(pool, J(99, day="2026-10-20"))
    assert p.low < p.delay_min < p.high
    assert p.low == pytest.approx(2.75) and p.high == pytest.approx(8.25)


# --- backtest temporal ----------------------------------------------------------------

def test_walk_forward_ignores_future_days():
    days = days_from("2026-10-05", 40)
    rows = [J(i, final=(i % 7), day=d) for i, d in enumerate(days)]
    before = P.walk_forward(rows)
    # o zi „viitoare” cu valori absurde nu trebuie să schimbe predicțiile zilelor anterioare
    future = rows + [J(9000 + k, final=900, day="2026-12-01") for k in range(50)]
    after = P.walk_forward(future)
    old_ids = {e.service_id: e.prediction for e in before}
    for e in after:
        if e.service_id in old_ids:
            assert e.prediction == old_ids[e.service_id]


def test_walk_forward_predicts_only_from_earlier_days():
    rows = [J(1, final=5, day="2026-10-05"), J(2, final=5, day="2026-10-05")]
    ev = P.walk_forward(rows)
    assert all(e.prediction is None for e in ev)  # aceeași zi nu se folosește singură


def test_report_mae_and_interval():
    days = days_from("2026-10-05", 60)
    rows = [J(i, final=10, baseline=0, day=d) for i, d in enumerate(days)]
    rep = P.report(P.walk_forward(rows), rows)
    assert rep["n_eval"] > 0 and rep["n_skipped"] + rep["n_eval"] == len(rows)
    assert rep["mae_pred"] == 0  # tot 10 min în fiecare zi: mediana e exactă
    assert rep["mae_base"] == 10
    assert rep["in_interval_pct"] == 100.0
    assert rep["good_days"] == 60


# --- poarta ---------------------------------------------------------------------------

def _rep(**kw):
    base = {"n_eval": 500, "mae_pred": 2.0, "mae_base": 3.0, "good_days": 40,
            "in_interval_pct": 60.0, "by_level": {"a": 1, "b": 1, "c": 1}}
    base.update(kw)
    return base


def test_gate_refuses_before_30_good_days():
    g = P.gate(_rep(good_days=29))
    assert g.published is False and "29 zile" in g.reason


def test_gate_refuses_small_backtest():
    g = P.gate(_rep(n_eval=99))
    assert g.published is False and "99" in g.reason


def test_gate_refuses_when_not_better_than_baseline():
    g = P.gate(_rep(mae_pred=3.0, mae_base=3.0))
    assert g.published is False and "nu bate" in g.reason
    assert P.gate(_rep(mae_pred=3.5, mae_base=3.0)).published is False


def test_gate_publishes_only_when_all_hold():
    g = P.gate(_rep())
    assert g.published is True and g.reason.startswith("publicat")


def test_gate_refuses_without_mae():
    assert P.gate(_rep(mae_pred=None, mae_base=None)).published is False


# --- citire fără scriere, din baza de date --------------------------------------------

def _db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE services (id INTEGER PRIMARY KEY, board TEXT, service_date TEXT,"
        " train_type TEXT, train_no INTEGER, station TEXT, operator TEXT, sched_time TEXT,"
        " first_seen TEXT, last_seen TEXT, last_delay INTEGER NOT NULL DEFAULT 0,"
        " last_platform INTEGER, status TEXT NOT NULL DEFAULT 'listed');"
        "CREATE TABLE events (id INTEGER PRIMARY KEY, service_id INTEGER, ts TEXT,"
        " kind TEXT, old TEXT, new TEXT);")
    dq.ensure_schema(conn)
    return conn


def test_load_journeys_and_first_read(tmp_path):
    conn = _db(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO services (id, board, service_date, train_type, train_no, station,"
                 " operator, sched_time, first_seen, last_seen) VALUES"
                 " (1,'departure','2026-10-05','R',100,'Iași','CFR','08:00','','')")
    conn.execute("INSERT INTO services (id, board, service_date, train_type, train_no, station,"
                 " operator, sched_time, first_seen, last_seen) VALUES"
                 " (2,'departure','2026-10-05','R',101,'Iași','CFR','09:00','','')")
    conn.execute("INSERT INTO service_quality (service_id, delay_checked, last_delay_clean,"
                 " updated_at) VALUES (1, 1, 12, ''), (2, 1, NULL, '')")
    conn.execute("INSERT INTO events (service_id, ts, kind, old, new) VALUES"
                 " (1, '2026-10-05T08:05', 'delay', '0', '7'),"
                 " (1, '2026-10-05T08:20', 'delay', '7', '12')")
    conn.commit()
    js = P.load_journeys(conn)
    assert [(j.service_id, j.final, j.baseline) for j in js] == [(1, 12, 7)]  # 2: unknown


def test_predict_path_does_not_write(tmp_path):
    p = str(tmp_path / "t.db")
    conn = _db(p)
    conn.execute("INSERT INTO services (id, board, service_date, train_type, train_no, station,"
                 " operator, sched_time, first_seen, last_seen) VALUES"
                 " (1,'departure','2026-10-05','R',100,'Iași','CFR','08:00','','')")
    conn.execute("INSERT INTO service_quality (service_id, delay_checked, last_delay_clean,"
                 " updated_at) VALUES (1, 1, 3, '')")
    conn.commit()
    ro = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    before = ro.execute("SELECT COUNT(*) FROM services").fetchone(), \
        ro.execute("SELECT COUNT(*) FROM service_quality").fetchone()
    js = P.load_journeys(ro)
    P.predict_final(P.build_pool(js), js[0])
    after = ro.execute("SELECT COUNT(*) FROM services").fetchone(), \
        ro.execute("SELECT COUNT(*) FROM service_quality").fetchone()
    assert before == after and ro.total_changes == 0


# --- scriptul de backtest refuză baza de producție -----------------------------------

def test_backtest_script_refuses_production_path(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "backtest_delay", Path(__file__).resolve().parent.parent / "scripts" / "backtest_delay.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with pytest.raises(ValueError, match="producție"):
        mod.check_db_path(mod.PRODUCTION_DB)
    copy = tmp_path / "copie.db"
    copy.write_bytes(b"")
    assert mod.check_db_path(str(copy)) == str(copy)
