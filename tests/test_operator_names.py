# © 2026 Andy217Ace
"""Schema v10: official operator names (migration, matching rule, diacritic-insensitive search)."""
import json

import pytest

from app import canonical, observations, operator_names
from app.store import Store


def _rows(conn, sql):
    return [tuple(r) for r in conn.execute(sql)]


@pytest.fixture
def v9(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "bk"))
    path = str(tmp_path / "t.db")
    s = Store(path)
    s.migrate()
    c = s._conn
    c.execute("PRAGMA foreign_keys = OFF")
    ops = [("CFR Calatori", "CFR Calatori"), ("Softrans Calat", "Softrans Calat"),
           ("Transferoviar", "Transferoviar"), ("GFR Galzitori", "GFR Galzitori"),
           ("| SUD Trans", "| SUD Trans"), ("Calatori 16:25", "Calatori 16:25"),
           ("asr", "asr"), ("", ""), ("Ferotrafic", "Ferotrafic")]
    for i, (op, raw) in enumerate(ops, 1):
        c.execute("INSERT INTO services(id, board, service_date, train_type, train_no, station,"
                  " operator, sched_time, first_seen, last_seen, operator_raw)"
                  " VALUES (?, 'departure', '2026-11-01', 'R', ?, 'BRASOV', ?, '08:10', 'a', 'b', ?)",
                  (i, 1000 + i, op, raw))
        c.execute("INSERT INTO observations(capture_id, service_id, board, row_index, observed_at,"
                  " operator, operator_raw, validation_state, processing_version)"
                  " VALUES (1, ?, 'departure', 0, 'x', ?, ?, 'ok', 'v')", (i, op, raw))
    # operator unaccepted but its raw text is a clean board form
    c.execute("INSERT INTO observations(capture_id, board, row_index, observed_at, operator,"
              " operator_raw, validation_state, processing_version)"
              " VALUES (1, 'departure', 1, 'x', 'asr', 'Regio Calatori', 'ok', 'v')")
    c.execute("INSERT INTO service_quality(service_id, operator_canonical, updated_at)"
              " VALUES (1, 'CFR Calatori', 'x')")
    c.execute("INSERT INTO trains(train_no, operators_json, routes_json, journeys, observations)"
              " VALUES (1, ?, '[]', 3, 3)",
              (json.dumps([{"operator": "CFR Calatori", "journeys": 2},
                           {"operator": "CFR Calatori ", "journeys": 1},
                           {"operator": "xq", "journeys": 1}]),))
    c.execute("INSERT INTO corrections(board, field, wrong_value, correct_value, created_at)"
              " VALUES ('departure', 'operator', 'CFR CALATORI', 'REGIO CALATORI', 'x')")
    c.execute("INSERT INTO corrections(board, field, wrong_value, correct_value, created_at)"
              " VALUES ('departure', 'station', 'CFR CALATORI', 'X', 'x')")
    c.execute("PRAGMA user_version = 9")
    return s


def test_migration_maps_names_and_keeps_raw(v9):
    c = v9._conn
    raw_before = _rows(c, "SELECT operator_raw FROM services ORDER BY id")
    obs_raw_before = _rows(c, "SELECT operator_raw FROM observations ORDER BY id")
    operator_names.migrate_to_10(c)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 10
    got = [r[0] for r in c.execute("SELECT operator FROM services ORDER BY id")]
    assert got[:3] == ["CFR Călători", "Softrans", "Transferoviar Călători"]
    assert got[8] == "Ferotrafic TFI"
    assert _rows(c, "SELECT operator_raw FROM services ORDER BY id") == raw_before
    assert _rows(c, "SELECT operator_raw FROM observations ORDER BY id") == obs_raw_before
    assert got[4:8] == ["| SUD Trans", "Calatori 16:25", "asr", ""]  # not accepted: unchanged
    # unaccepted operator + accepted raw: the raw's official name
    assert c.execute("SELECT operator FROM observations WHERE operator_raw='Regio Calatori'"
                     ).fetchone()[0] == "Regio Călători"
    assert c.execute("SELECT operator_canonical FROM service_quality").fetchone()[0] \
        == "CFR Călători"


def test_migration_merges_trains_and_maps_corrections(v9):
    c = v9._conn
    operator_names.migrate_to_10(c)
    js = c.execute("SELECT operators_json FROM trains").fetchone()[0]
    assert json.loads(js) == [{"operator": "CFR Călători", "journeys": 3},
                              {"operator": "xq", "journeys": 1}]
    assert "Călători" in js  # not \u-escaped
    assert _rows(c, "SELECT field, wrong_value, correct_value FROM corrections ORDER BY id") == [
        ("operator", "CFR Călători", "Regio Călători"),
        ("station", "CFR CALATORI", "X")]


def test_migration_skips_malformed_trains_json(v9):
    c = v9._conn
    c.execute("INSERT INTO trains(train_no, operators_json, routes_json, journeys, observations)"
              " VALUES (2, 'not json', '[]', 1, 1), (3, '[1, {\"journeys\": 2}]', '[]', 1, 1)")
    operator_names.migrate_to_10(c)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 10
    assert c.execute("SELECT operators_json FROM trains WHERE train_no=2").fetchone()[0] == "not json"
    assert json.loads(c.execute("SELECT operators_json FROM trains WHERE train_no=3").fetchone()[0]) \
        == [{"operator": "", "journeys": 2}]


def test_migration_rerun_is_noop(v9):
    c = v9._conn
    operator_names.migrate_to_10(c)
    snap = _rows(c, "SELECT operator FROM observations ORDER BY id")
    c.execute("PRAGMA user_version = 9")  # ladder re-run on already-official data
    operator_names.migrate_to_10(c)
    assert _rows(c, "SELECT operator FROM observations ORDER BY id") == snap
    c.execute("UPDATE services SET operator='zzz'")
    operator_names.migrate_to_10(c)  # >= 10: nothing runs
    assert c.execute("SELECT DISTINCT operator FROM services").fetchone()[0] == "zzz"


def test_migration_failure_rolls_back(v9, monkeypatch):
    def boom(conn):
        raise RuntimeError("boom")
    monkeypatch.setattr(operator_names, "_remap_trains", boom)
    with pytest.raises(RuntimeError):
        operator_names.migrate_to_10(v9._conn)
    c = v9._conn
    assert c.execute("PRAGMA user_version").fetchone()[0] == 9
    assert c.execute("SELECT operator FROM services WHERE id=1").fetchone()[0] == "CFR Calatori"
    assert c.execute("SELECT COUNT(*) FROM observations WHERE operator='CFR Calatori'"
                     ).fetchone()[0] == 1


def test_store_ladder_runs_v10_with_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "bk"))
    path = str(tmp_path / "t.db")
    s = Store(path)
    s.migrate()
    s._conn.execute("PRAGMA foreign_keys = OFF")
    s._conn.execute("INSERT INTO services(board, service_date, train_type, train_no, station,"
                    " operator, sched_time, first_seen, last_seen, operator_raw)"
                    " VALUES ('departure', '2026-11-01', 'R', 1, 'X', 'Ferotrafic', '08:10',"
                    " 'a', 'b', 'Ferotrafic')")
    s._conn.execute("PRAGMA user_version = 9")
    s.close()
    s = Store(path)
    s.migrate()
    assert s._conn.execute("SELECT operator FROM services").fetchone()[0] == "Ferotrafic TFI"
    assert list((tmp_path / "bk").glob("tabela-*-v9.db"))


# -- matching rule -------------------------------------------------------------------------

@pytest.mark.parametrize("text, name", [
    ("CFR Calatori", "CFR Călători"), ("CFR Călători", "CFR Călători"),
    ("Transferoviar", "Transferoviar Călători"),
    ("InterRegional", "InterRegional Călători"),
    ("Astra Trans Ca", "Astra Trans Carpatic"), ("Softrans Calat", "Softrans"),
    ("Softrans", "Softrans"), ("Ferotrafic", "Ferotrafic TFI"),
])
def test_official_names(text, name):
    assert canonical.canonical_operator(text) == (name, 1.0)
    assert name in canonical.known_operators()


def test_acceptance_rule():
    assert canonical.operator_match("Regio Calatorl")[2]  # >= 0.82
    assert canonical.operator_match("asr")[2] is False
    assert canonical.operator_match("") == ("", 0.0, False)
    n, s, ok = canonical.operator_match("Calatori")  # CFR / Regio tie: no margin
    assert not ok and n == "Calatori" and s < canonical.DEFAULT_THRESHOLD


def test_known_list_keeps_hard_threshold_only():
    assert canonical.operator_match("Softrans", known=["Softrans SRL"])[2] is False


# -- diacritic-insensitive search ----------------------------------------------------------

def test_fold_function_and_train_search(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.migrate()
    assert s._conn.execute("SELECT fold('Călători ȘI')").fetchone()[0] == "calatori si"
    s._conn.execute("INSERT INTO trains(train_no, first_seen, last_seen, operators_json,"
                    " routes_json, journeys, observations) VALUES (7, 'a', 'b', ?, '[]', 1, 1)",
                    (json.dumps([{"operator": "CFR Călători", "journeys": 1}],
                                ensure_ascii=False),))
    for q in ("calatori", "CĂLĂTORI", "Călători"):
        assert [t["train_no"] for t in observations.list_trains(s, q)] == [7]
    assert observations.list_trains(s, "regio") == []
