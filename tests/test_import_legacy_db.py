# © 2026 Andy217Ace
"""scripts/import_legacy_db.py on small synthetic databases built through the Store."""
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from app.store import SCHEMA_VERSION, Store

SPEC = importlib.util.spec_from_file_location(
    "import_legacy_db",
    Path(__file__).resolve().parent.parent / "scripts" / "import_legacy_db.py")
il = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(il)

OLD, NEW = "2026-10-21", "2026-10-31"


def _t(day, hh, mm=0):
    return f"{day}T{hh:02d}:{mm:02d}:00+03:00"


def _build(path: Path, day: str, trains: list[tuple[int, str]], *, listed: int | None = None,
           ghost_pair: bool = False, tag: str = "x") -> Path:
    """A v9 database with, per train, a service, two events, two captures with one
    observation each, plus runs, weather, quality rows, a push subscription + follow."""
    st = Store(str(path))
    st.migrate()
    c = st._conn
    sids = []
    for k, (no, sched) in enumerate(trains):
        c.execute("INSERT INTO runs(ts, image_hash, ok, n_rows) VALUES (?,?,1,12)",
                  (_t(day, 8, k), f"run-{tag}-{k}"))
        status = "listed" if no == listed else "gone"
        sid = c.execute(
            "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
            " sched_time, first_seen, last_seen, last_delay, status, station_raw, operator_raw)"
            " VALUES ('departure',?,'IR',?,'BRASOV','CFR Calatori',?,?,?,5,?,'BRASOV','')",
            (day, no, sched, _t(day, 8, k), _t(day, 9, k), status)).lastrowid
        sids.append(sid)
        ev = c.execute("INSERT INTO events(service_id, ts, kind, old, new) VALUES (?,?,?,?,?)",
                       (sid, _t(day, 8, k), "appeared", None, None)).lastrowid
        ev2 = c.execute("INSERT INTO events(service_id, ts, kind, old, new) VALUES (?,?,?,?,?)",
                        (sid, _t(day, 9, k), "delay", "0", "5")).lastrowid
        c.execute("INSERT INTO event_quality(event_id, suspect, reason) VALUES (?,1,'t')", (ev2,))
        c.execute("INSERT INTO service_quality(service_id, updated_at) VALUES (?,?)",
                  (sid, _t(day, 9)))
        for j in range(2):
            cap = c.execute(
                "INSERT INTO captures(captured_at, image_hash, path, ok, n_rows, duration_ms)"
                " VALUES (?,?,?,1,12,100)",
                (_t(day, 8, k * 2 + j), f"img-{tag}-{k}-{j}", f"{day}/img-{k}-{j}.jpg")).lastrowid
            c.execute(
                "INSERT INTO observations(capture_id, service_id, board, row_index, observed_at,"
                " train_no, sched_time, station, validation_state, processing_version)"
                " VALUES (?,?,'departure',?,?,?,?,'BRASOV','ok','t')",
                (cap, sid, k, _t(day, 8, k * 2 + j), no, sched))
    if ghost_pair:
        c.execute("UPDATE service_quality SET ghost=1, ghost_reason='near_dup', ghost_of=?"
                  " WHERE service_id=?", (sids[0], sids[-1]))
    c.execute("INSERT INTO weather_observations(observed_at, fetched_at, temperature_c)"
              " VALUES (?,?,12.5)", (f"{day}T06:00:00Z", f"{day}T06:01:00Z"))
    c.execute("INSERT INTO subscriptions(endpoint, p256dh, auth, created_at)"
              " VALUES (?, 'k', 'a', ?)", (f"https://push.example/{tag}", _t(day, 7)))
    c.execute("INSERT INTO follows(subscription_id, train_no, service_date) VALUES (1, ?, ?)",
              (trains[0][0], day))
    from app.observations import refresh_trains
    refresh_trains(c, [no for no, _ in trains])
    st.close()
    return path


def _hashes(path: Path) -> dict:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    out = {}
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"
                          " AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
        h = hashlib.sha256()
        for r in c.execute(f"SELECT * FROM {t} ORDER BY 1"):
            h.update(repr(tuple(r)).encode())
        out[t] = h.hexdigest()
    c.close()
    return out


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def dbs(tmp_path):
    src_dir, tgt_dir = tmp_path / "old", tmp_path / "new"
    src_dir.mkdir()
    tgt_dir.mkdir()
    # 1741 in both (catalog merge), 2001 only in the source, 3001 only in the target
    src = _build(src_dir / "live.db", OLD, [(1741, "10:00"), (2001, "11:00"), (2002, "12:00")],
                 listed=2002, ghost_pair=True, tag="old")
    tgt = _build(tgt_dir / "tabela.db", NEW, [(1741, "10:00"), (3001, "13:00")], tag="new")
    return src, tgt


def _apply(src, tgt, **kw):
    return il.run(src, tgt, do_apply=True, manifest=tgt.parent / "m.json", **kw)


def test_dry_run_writes_nothing(dbs):
    src, tgt = dbs
    before, files = _hashes(tgt), set(tgt.parent.iterdir())
    rep = il.run(src, tgt)
    assert rep["mode"] == "dry-run"
    assert _hashes(tgt) == before
    assert {p.name for p in set(tgt.parent.iterdir()) - files} <= {
        "tabela.db-wal", "tabela.db-shm"}  # sqlite read-only open, no data written
    t = rep["plan"]["tables"]
    assert t["services"]["rows"] == 3 and t["observations"]["rows"] == 6
    assert t["subscriptions"]["action"] == "skip" and t["follows"]["action"] == "skip"
    # 2002 is a ghost in the source: never catalogued there, so not inserted here
    assert t["trains"] == {"action": "merge", "rows_inserted": 1, "rows_recomputed": 1,
                           "recomputed_examples": [1741]}
    assert rep["counts_after_projected"]["services"] == 5


def test_apply_remaps_ids_and_keeps_references(dbs):
    src, tgt = dbs
    rep = _apply(src, tgt)
    assert rep["checks"] == {"integrity_check": "ok", "foreign_key_check": []}
    c = sqlite3.connect(tgt)
    old = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    # every imported service keeps its events / observations / captures / quality rows
    for no, n_ev in old.execute("SELECT s.train_no, COUNT(e.id) FROM services s JOIN events e"
                                " ON e.service_id = s.id GROUP BY s.id"):
        sid = c.execute("SELECT id FROM services WHERE service_date=? AND train_no=?",
                        (OLD, no)).fetchone()[0]
        assert sid > 2  # above the target's ids
        assert c.execute("SELECT COUNT(*) FROM events WHERE service_id=?", (sid,)
                         ).fetchone()[0] == n_ev
        obs = c.execute("SELECT o.observed_at, cp.captured_at, cp.path FROM observations o"
                        " JOIN captures cp ON cp.id = o.capture_id WHERE o.service_id=?",
                        (sid,)).fetchall()
        assert len(obs) == 2 and all(a == b and p is None for a, b, p in obs)
        assert c.execute("SELECT COUNT(*) FROM service_quality WHERE service_id=?",
                         (sid,)).fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM event_quality q JOIN events e ON e.id=q.event_id"
                         " WHERE e.service_id=?", (sid,)).fetchone()[0] == 1
    # the ghost link follows the remapped service id
    g, of = c.execute("SELECT q.service_id, q.ghost_of FROM service_quality q WHERE ghost=1"
                      ).fetchone()
    assert c.execute("SELECT train_no FROM services WHERE id=?", (of,)).fetchone()[0] == 1741
    assert c.execute("SELECT service_date FROM services WHERE id=?", (of,)).fetchone()[0] == OLD
    # old runs below the current ones: the latest reading is still today's
    assert c.execute("SELECT MAX(id) FROM runs WHERE ts < ?", (NEW,)).fetchone()[0] <= 0
    st = Store(str(tgt))
    assert st.last_ok_run()[1].startswith(NEW)
    # a service left 'listed' by the old server is retired, never on today's board
    assert c.execute("SELECT status, miss_count FROM services WHERE train_no=2002").fetchone() \
        == ("gone", 1)
    assert {r["train_no"] for r in st.current_board()["departures"]} <= {1741, 3001}
    st.close()
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    m = json.loads((tgt.parent / "m.json").read_text(encoding="utf-8"))
    assert len(m["tables"]["observations"]["ids"]) == 6
    assert Path(rep["backup"]).is_file()


def test_subscriptions_follows_dq_meta_not_imported(dbs):
    src, tgt = dbs
    c = sqlite3.connect(tgt)
    dq = c.execute("SELECT * FROM dq_meta ORDER BY key").fetchall()
    c.close()
    _apply(src, tgt)
    c = sqlite3.connect(tgt)
    assert c.execute("SELECT endpoint FROM subscriptions").fetchall() == [
        ("https://push.example/new",)]
    assert c.execute("SELECT service_date FROM follows").fetchall() == [(NEW,)]
    assert c.execute("SELECT * FROM dq_meta ORDER BY key").fetchall() == dq


def test_trains_merged_not_duplicated(dbs):
    src, tgt = dbs
    _apply(src, tgt)
    c = sqlite3.connect(tgt)
    rows = {r[0]: r for r in c.execute(
        "SELECT train_no, first_seen, last_seen, journeys, observations FROM trains")}
    assert set(rows) == {1741, 2001, 3001}  # 2002: ghost, not catalogued in the source
    no, first, last, journeys, n_obs = rows[1741]
    assert first.startswith("2026-10-21") and last.startswith("2026-10-31")
    assert journeys == 2 and n_obs == 4
    assert c.execute("SELECT COUNT(*) FROM trains WHERE train_no=1741").fetchone()[0] == 1


def test_restore_returns_identical_content(dbs):
    src, tgt = dbs
    before = _hashes(tgt)
    _apply(src, tgt)
    assert _hashes(tgt) != before
    rep = il.run(None, tgt, restore_manifest=tgt.parent / "m.json")
    assert rep["checks"] == {"integrity_check": "ok", "foreign_key_check": []}
    assert _hashes(tgt) == before
    files = set(tgt.parent.iterdir())
    with pytest.raises(il.ImportAborted, match="already restored"):
        il.run(None, tgt, restore_manifest=tgt.parent / "m.json")
    assert set(tgt.parent.iterdir()) == files  # refused before any backup


def test_restore_refuses_changed_rows(dbs):
    src, tgt = dbs
    _apply(src, tgt)
    c = sqlite3.connect(tgt)
    c.execute("UPDATE services SET sched_time='10:05' WHERE service_date=? AND train_no=2001",
              (OLD,))
    c.commit()
    c.close()
    mid = _hashes(tgt)
    with pytest.raises(il.ImportAborted, match="services"):
        il.run(None, tgt, restore_manifest=tgt.parent / "m.json")
    assert _hashes(tgt) == mid


def test_abort_on_natural_key_collision(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    src = _build(tmp_path / "a" / "old.db", NEW, [(1741, "10:05")], tag="old")
    tgt = _build(tmp_path / "b" / "tabela.db", NEW, [(1741, "10:00")], tag="new")
    before = _hashes(tgt)
    with pytest.raises(il.ImportAborted, match="collision"):
        _apply(src, tgt)
    assert _hashes(tgt) == before
    assert not (tgt.parent / "m.json").exists()
    assert not list(tgt.parent.glob("*before-legacy-import*"))
    assert il.main(["--source", str(src), "--target", str(tgt)]) == 2  # dry run aborts too


def test_apply_twice_aborts(dbs):
    src, tgt = dbs
    _apply(src, tgt)
    mid = _hashes(tgt)
    with pytest.raises(il.ImportAborted, match="collision"):
        il.run(src, tgt, do_apply=True, manifest=tgt.parent / "m2.json")
    assert _hashes(tgt) == mid


def test_source_file_unchanged(dbs):
    src, tgt = dbs
    files = {p.name: _file_hash(p) for p in src.parent.iterdir()}
    rep = _apply(src, tgt)
    assert {p.name: _file_hash(p) for p in src.parent.iterdir()} == files
    assert rep["source_sha256_before"] == rep["source_sha256_after"]
    assert "source_changed" not in rep


def test_old_schema_source_is_migrated_on_a_copy(dbs):
    src, tgt = dbs
    c = sqlite3.connect(src)  # make it look like a v7 database (before weather v8 / v9)
    for t in ("correction_audit", "correction_archive", "correction_batches", "corrections",
              "settings"):
        c.execute(f"DROP TABLE IF EXISTS {t}")
    for col in ("relative_humidity_pct", "is_day", "rain_mm", "showers_mm", "snowfall_cm",
                "surface_pressure_hpa", "wind_gusts_kmh", "hourly_json"):
        c.execute(f"ALTER TABLE weather_observations DROP COLUMN {col}")
    c.execute("PRAGMA user_version = 7")
    c.commit()
    c.close()
    h = _file_hash(src)
    rep = _apply(src, tgt)
    assert rep["source_schema"] == {"original": 7, "migrated_copy": SCHEMA_VERSION}
    assert _file_hash(src) == h
    assert sqlite3.connect(src).execute("PRAGMA user_version").fetchone()[0] == 7
    assert not (src.parent / "backups").exists()  # the migration backup stayed in the temp dir
    c = sqlite3.connect(tgt)
    assert c.execute("SELECT COUNT(*) FROM weather_observations").fetchone()[0] == 2
