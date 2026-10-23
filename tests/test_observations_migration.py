# © 2026 Andy217Ace
"""Schema v5: captures, observations, trains catalog (+ backfill from services)."""
import json
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.models import Row
from app.store import SCHEMA_VERSION, Store

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=BUC)
V5_TABLES = {"captures", "observations", "trains"}


def R(board, no, t, station="Brasov", operator="CFR Calatori"):
    return Row(board=board, train_type="IR", train_no=no, station=station,
               operator=operator, sched_time=t)


def rows():
    return [R("arrival", 1621, "12:10"), R("arrival", 1622, "12:20"),
            R("departure", 1621, "12:45", station="Constanta"),
            R("departure", 1732, "12:30", operator="Transferoviar")]


def version(s):
    return s._conn.execute("PRAGMA user_version").fetchone()[0]


def tables(s):
    return {r[0] for r in s._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def indexes(s, table):
    return {r[1] for r in s._conn.execute(f"PRAGMA index_list({table})")}


def drop_v5(s):
    for t in ("observations", "captures", "trains"):
        s._conn.execute(f"DROP TABLE {t}")


def test_schema_version_at_least_5():
    assert SCHEMA_VERSION >= 5


def test_fresh_db_has_v5_tables_and_indexes():
    s = Store(":memory:")
    s.migrate()
    assert version(s) == SCHEMA_VERSION
    assert V5_TABLES <= tables(s)
    cols = {r[1] for r in s._conn.execute("PRAGMA table_info(observations)")}
    assert {"capture_id", "service_id", "board", "row_index", "observed_at", "raw_text",
            "fields_json", "train_no", "sched_time", "delay_min", "delay_read", "platform",
            "station", "station_raw", "operator", "operator_raw", "row_conf", "uncertain",
            "validation_state", "processing_version"} <= cols
    cap = {r[1] for r in s._conn.execute("PRAGMA table_info(captures)")}
    assert {"captured_at", "image_hash", "path", "width", "height", "bytes", "ok", "n_rows",
            "processing_version", "duration_ms", "error", "expires_at"} <= cap
    tr = {r[1] for r in s._conn.execute("PRAGMA table_info(trains)")}
    assert {"train_no", "first_seen", "last_seen", "operators_json", "routes_json",
            "journeys", "observations"} <= tr
    idx = indexes(s, "observations")
    assert {"ix_observations_service", "ix_observations_observed",
            "ix_observations_capture", "ix_observations_train"} <= idx
    s.close()


def test_board_check_constraint():
    s = Store(":memory:")
    s.migrate()
    s._conn.execute("INSERT INTO captures(captured_at, image_hash, ok, n_rows)"
                    " VALUES ('2026-10-20T10:00:00+00:00', 'h', 1, 0)")
    with pytest.raises(sqlite3.IntegrityError):
        s._conn.execute("INSERT INTO observations(capture_id, board, row_index, observed_at,"
                        " raw_text, validation_state, processing_version)"
                        " VALUES (1, 'sideways', 0, 'x', '', 'ok', 'p')")
    s.close()


def _seeded_v3(tmp_path, name="old.db"):
    s = Store(str(tmp_path / name))
    s.migrate()
    s.ingest(rows(), T0)
    s.ingest(rows(), T0 + timedelta(minutes=5))
    drop_v5(s)
    s._conn.execute("DROP TABLE weather_observations")  # a real v3 has no v4 table either
    s._conn.execute("PRAGMA user_version = 3")
    return s


@pytest.mark.parametrize("start", [3, 4])
def test_migrate_v3_or_v4_to_v5_keeps_data_and_backfills(tmp_path, start):
    s = _seeded_v3(tmp_path)
    if start == 4:  # the real v4 step (weather); its rows must survive v4 -> v5 untouched
        s._migrate_to_4()
        s._conn.execute("INSERT INTO weather_observations(observed_at, fetched_at, temperature_c)"
                        " VALUES ('2026-10-20T10:00:00Z', '2026-10-20T10:01:00Z', 12.5)")
        assert version(s) == 4
    n_services = s._conn.execute("SELECT COUNT(*) FROM services").fetchone()[0]
    n_events = s._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    s.migrate()
    s.migrate()  # idempotent
    assert version(s) == SCHEMA_VERSION
    assert V5_TABLES <= tables(s)
    assert s._conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == n_services == 4
    assert s._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == n_events
    if start == 4:
        assert s._conn.execute("SELECT temperature_c FROM weather_observations").fetchone()[0] == 12.5
    else:  # v3 -> v5 runs the v4 step too
        assert "weather_observations" in tables(s)
    got = {r["train_no"]: r for r in s._conn.execute("SELECT * FROM trains")}
    assert set(got) == {1621, 1622, 1732}
    t = got[1621]
    assert t["journeys"] == 2          # arrival + departure services
    assert t["observations"] == 0      # no OCR observations recorded before v5
    ops = json.loads(t["operators_json"])
    assert ops == [{"operator": "CFR Calatori", "journeys": 2}]
    routes = json.loads(t["routes_json"])
    assert {(r["board"], r["station"], r["journeys"]) for r in routes} == {
        ("arrival", "Brasov", 1), ("departure", "Constanta", 1)}
    assert t["first_seen"].endswith("+00:00") and t["first_seen"] < t["last_seen"]
    assert got[1732]["journeys"] == 1
    s.close()


@pytest.mark.parametrize("start", [1, 2])
def test_migrate_v1_v2_to_v5(tmp_path, start):
    s = _seeded_v3(tmp_path)
    for col in ("operator_raw", "station_raw", "uncertain"):
        s._conn.execute(f"ALTER TABLE services DROP COLUMN {col}")
    if start == 1:
        s._conn.execute("ALTER TABLE services DROP COLUMN last_read")
    s._conn.execute(f"PRAGMA user_version = {start}")
    s.migrate()
    assert version(s) == SCHEMA_VERSION
    assert V5_TABLES <= tables(s)
    assert s._conn.execute("SELECT COUNT(*) FROM trains").fetchone()[0] == 3
    s.close()


def test_migrate_live_v2_fixture_to_v5(tmp_path):
    db = tmp_path / "live.db"
    shutil.copy(Path(__file__).parent / "fixtures" / "live_v2.db", db)
    s = Store(str(db))
    s.migrate()
    assert version(s) == SCHEMA_VERSION
    n = s._conn.execute("SELECT COUNT(DISTINCT train_no) FROM services").fetchone()[0]
    assert s._conn.execute("SELECT COUNT(*) FROM trains").fetchone()[0] == n
    total = s._conn.execute("SELECT SUM(journeys) FROM trains").fetchone()[0]
    assert total == s._conn.execute("SELECT COUNT(*) FROM services").fetchone()[0]
    s.close()


def test_failed_v5_migration_rolls_back(tmp_path, monkeypatch):
    s = _seeded_v3(tmp_path)
    from app import observations

    def boom(conn, train_nos):
        raise RuntimeError("backfill failed")

    monkeypatch.setattr(observations, "refresh_trains", boom)
    with pytest.raises(RuntimeError):
        s.migrate()
    assert version(s) == 4  # the v4 (weather) step committed on its own; v5 rolled back
    assert "weather_observations" in tables(s)
    assert not (V5_TABLES & tables(s))  # nothing half-created
    monkeypatch.undo()
    s.migrate()
    assert version(s) == SCHEMA_VERSION
    s.close()
