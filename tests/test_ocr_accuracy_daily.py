# © 2026 Andy217Ace
"""Monitorizarea zilnica (scripts/ocr_accuracy_daily.py): consensul vecinilor, doar citire."""
import importlib.util
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ocr_accuracy_daily",
                                               ROOT / "scripts" / "ocr_accuracy_daily.py")
mon = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mon)


def _r(no, platform, state="ok"):
    return state, json.dumps({"no": {"norm": no}, "platform": {"norm": platform}})


def _db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE services (id INTEGER PRIMARY KEY, service_date TEXT)")
    con.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY, service_id INTEGER, "
                "observed_at TEXT, validation_state TEXT, fields_json TEXT)")
    con.execute("INSERT INTO services VALUES (1, '2026-11-27'), (2, '2026-11-26')")
    reads = [_r(1581, 4), _r(1581, 4), _r(1584, None), _r(1581, 4), _r(1581, 4),
             _r(9999, 9, "rejected_low_conf")]  # nepublicata: nu se noteaza, nu voteaza
    for i, (state, fj) in enumerate(reads):
        con.execute("INSERT INTO observations VALUES (?, 1, ?, ?, ?)",
                    (i + 1, f"2026-11-27T10:{i:02d}:00", state, fj))
    con.execute("INSERT INTO observations VALUES (99, 2, '2026-11-26T10:00:00', 'ok', ?)",
                (_r(1, 1)[1],))
    con.commit()
    con.close()


def test_day_summary_counts_against_neighbour_consensus(tmp_path):
    db = tmp_path / "t.db"
    _db(db)
    con = sqlite3.connect(db)
    s = mon.day_summary(con, "2026-11-27")
    con.close()
    assert s["services"] == 1 and s["readings"] == 5
    assert s["fields"]["no"] == {"n": 5, "ok": 4, "unread": 0, "wrong": 1, "accuracy": 0.8}
    assert s["fields"]["platform"]["unread"] == 1 and s["fields"]["platform"]["ok"] == 4
    assert s["fields"]["delay"]["n"] == 0  # fara voturi, fara nota


def test_too_few_neighbours_are_not_scored():
    counts = {f: mon.collections.Counter() for f in mon.FIELDS}
    mon.score_service([{"no": {"norm": 1}}, {"no": {"norm": 1}}, {"no": {"norm": 2}}], counts)
    assert sum(counts["no"].values()) == 0  # 2 vecini < MIN_VOTES


def test_main_writes_daily_file_and_never_writes_the_db(tmp_path, capsys):
    db = tmp_path / "t.db"
    _db(db)
    before = db.read_bytes()
    assert mon.main(["--db", str(db), "--date", "2026-11-27", "--days", "2",
                     "--out", str(tmp_path / "out")]) == 0
    days = [json.loads(line)["date"] for line in capsys.readouterr().out.splitlines()]
    assert days == ["2026-11-26", "2026-11-27"]
    assert (tmp_path / "out" / "ocr-accuracy-2026-11-27.json").is_file()
    assert db.read_bytes() == before
