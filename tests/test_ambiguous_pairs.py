# © 2026 Andy217Ace
"""scripts/ambiguous_pairs.py on a synthetic database: read-only report of ambiguous pairs."""
import hashlib
import importlib.util
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from app.store import Store

SPEC = importlib.util.spec_from_file_location(
    "ambiguous_pairs",
    Path(__file__).resolve().parent.parent / "scripts" / "ambiguous_pairs.py")
ap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ap)

DAY = (date.today() - timedelta(days=2)).isoformat()


def _t(hh, mm=0, day=DAY):
    return f"{day}T{hh:02d}:{mm:02d}:00+03:00"


def _svc(c, no, station, sched, fs, ls, *, board="departure", day=DAY):
    return c.execute(
        "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
        " sched_time, first_seen, last_seen, status, station_raw, operator_raw)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (board, day, "R", no, station, "CFR", sched, fs, ls, "gone", station, "")).lastrowid


def _cap(c, at):
    return c.execute("INSERT INTO captures(captured_at, image_hash, ok) VALUES (?,?,1)",
                     (at, hashlib.md5(at.encode() + str(c.total_changes).encode())
                      .hexdigest())).lastrowid


def _obs(c, cap, sid, no, at, *, board="departure", station="BUZAU"):
    c.execute(
        "INSERT INTO observations(capture_id, service_id, board, row_index, observed_at,"
        " train_no, station, validation_state, processing_version)"
        " VALUES (?,?,?,0,?,?,?, 'ok', 't')", (cap, sid, board, at, no, station))


def _db(tmp_path):
    db = tmp_path / "a.db"
    s = Store(str(db))
    s.migrate()
    c = s._conn
    # (a) 8093 / 93: same hour and station, never in one capture
    a = _svc(c, 8093, "BUZAU", "17:08", _t(13), _t(13, 30))
    b = _svc(c, 93, "BUZAU", "17:08", _t(13, 35), _t(14))
    for k in range(3):
        _obs(c, _cap(c, _t(13, k)), a, 8093, _t(13, k))
    _obs(c, _cap(c, _t(13, 40)), b, 93, _t(13, 40))
    # (b) 5011 / 5014 always together in the same frame
    x = _svc(c, 5011, "PITESTI", "09:10", _t(8), _t(9))
    y = _svc(c, 5014, "PITESTI", "09:10", _t(8), _t(9))
    for k in range(2):
        cap = _cap(c, _t(8, k))
        _obs(c, cap, x, 5011, _t(8, k), station="PITESTI")
        _obs(c, cap, y, 5014, _t(8, k), station="PITESTI")
    # (c) 1584 / 1581: one differing digit, never together
    p = _svc(c, 1584, "CONSTANTA", "11:00", _t(10), _t(10, 30))
    q = _svc(c, 1581, "CONSTANTA", "11:00", _t(10, 40), _t(11))
    _obs(c, _cap(c, _t(10, 5)), p, 1584, _t(10, 5), station="CONSTANTA")
    _obs(c, _cap(c, _t(10, 45)), q, 1581, _t(10, 45), station="CONSTANTA")
    c.commit()
    s.close()
    return db


def _find(pairs, a, b):
    return [p for p in pairs if {p.no_a, p.no_b} == {a, b}]


def test_prefix_dup(tmp_path):
    conn = sqlite3.connect(_db(tmp_path))
    ps = _find(ap.find_pairs(conn, days=30), 8093, 93)
    assert len(ps) == 1
    p = ps[0]
    assert p.kind == "prefix_dup" and p.station == "BUZAU"
    assert p.same_day_overlap is False
    assert (p.reads_a, p.reads_b) == (1, 3)  # no_a=93, no_b=8093


def test_coexist_beats_one_digit(tmp_path):
    conn = sqlite3.connect(_db(tmp_path))
    ps = _find(ap.find_pairs(conn, days=30), 5011, 5014)
    assert len(ps) == 1 and ps[0].kind == "coexist"
    assert ps[0].same_day_overlap is True and ps[0].station == "PITESTI"


def test_one_digit(tmp_path):
    conn = sqlite3.connect(_db(tmp_path))
    ps = _find(ap.find_pairs(conn, days=30), 1584, 1581)
    assert len(ps) == 1 and ps[0].kind == "one_digit" and ps[0].station == "CONSTANTA"


def test_window_excludes_old(tmp_path):
    conn = sqlite3.connect(_db(tmp_path))
    assert ap.find_pairs(conn, days=1) == []


def test_main_writes_nothing(tmp_path, capsys):
    db = _db(tmp_path)
    before = db.read_bytes()
    assert ap.main(["--db", str(db), "--days", "30"]) == 0
    out = capsys.readouterr().out
    assert "prefix_dup" in out and "coexist" in out and "one_digit" in out
    assert db.read_bytes() == before
