# © 2026 Andy217Ace
"""scripts/purge_ghosts.py on a synthetic database (R 5011 + misread duplicates)."""
import importlib.util
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from app import quality
from app.store import Store
from tests.test_store_quality import _seed_history

SPEC = importlib.util.spec_from_file_location(
    "purge_ghosts", Path(__file__).resolve().parent.parent / "scripts" / "purge_ghosts.py")
pg = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pg)


def _db(tmp_path):
    db = tmp_path / "p.db"
    s = Store(str(db))
    s.migrate()
    c = s._conn
    c.execute("UPDATE dq_meta SET value='2026-10-22T00:00:00+03:00' WHERE key='live_since'")
    ids = _seed_history(c)
    # one observation linked to a ghost (kept, only unlinked by the purge)
    cap = c.execute("INSERT INTO captures(captured_at, image_hash, ok) VALUES ('x','h',1)").lastrowid
    c.execute("INSERT INTO observations(capture_id, service_id, board, row_index, observed_at,"
              " train_no, validation_state, processing_version)"
              " VALUES (?,?,'departure',0,'2026-10-21T01:10:00+00:00',5014,'ok','t')",
              (cap, ids["dups"][0]))
    c.execute("INSERT INTO events(service_id, ts, kind) VALUES (?, '2026-10-21T07:10:00+03:00',"
              " 'appeared')", (ids["dups"][0],))
    quality.backfill(c)
    s.close()
    return db, ids


def _dump(db):
    c = sqlite3.connect(db)
    out = {t: c.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
           for t in ("services", "events", "service_quality", "observations", "trains")}
    c.close()
    return out


def test_dry_run_is_default_and_writes_nothing(tmp_path, capsys):
    db, ids = _db(tmp_path)
    before = _dump(db)
    assert pg.main(["--db", str(db)]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["mode"] == "dry-run"
    assert rep["would_remove"]["services"] == 8
    assert rep["would_remove"]["observation_links"] == 1
    assert sum(rep["by_reason"].values()) == 8 and set(rep["by_reason"]) <= {"near_dup", "short"}
    assert len(rep["examples"]) == 8
    assert any(e["ghost_of"] == ids["5011"] for e in rep["examples"])
    assert _dump(db) == before
    assert "purged_rows" not in {r[0] for r in sqlite3.connect(db).execute(
        "SELECT name FROM sqlite_master")}


def test_apply_needs_backup_dir(tmp_path):
    db, _ = _db(tmp_path)
    import pytest
    with pytest.raises(SystemExit):
        pg.main(["--db", str(db), "--apply"])


def test_apply_archives_backs_up_is_idempotent_and_restores(tmp_path, capsys):
    db, ids = _db(tmp_path)
    before = _dump(db)
    assert pg.main(["--db", str(db), "--apply", "--backup-dir", str(tmp_path / "bk")]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert Path(rep["backup"]).exists()
    bk = sqlite3.connect(rep["backup"])
    assert bk.execute("SELECT COUNT(*) FROM services").fetchone()[0] == len(before["services"])
    bk.close()
    c = sqlite3.connect(db)
    left = {r[0] for r in c.execute("SELECT id FROM services")}
    assert not (left & set(ids["dups"])) and ids["5011"] in left
    assert c.execute("SELECT service_id FROM observations").fetchone()[0] is None  # kept, unlinked
    assert c.execute("SELECT COUNT(*) FROM purged_rows").fetchone()[0] > 8
    c.close()
    # idempotent
    pg.main(["--db", str(db), "--apply", "--backup-dir", str(tmp_path / "bk")])
    assert json.loads(capsys.readouterr().out)["would_remove"]["services"] == 0
    # reversible: exactly as before
    pg.main(["--db", str(db), "--restore"])
    capsys.readouterr()
    after = _dump(db)
    for t in ("services", "events", "service_quality", "observations"):
        assert after[t] == before[t], t
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM purged_rows").fetchone()[0] == 0


def test_listed_or_recent_ghost_never_purged(tmp_path):
    db, ids = _db(tmp_path)
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    c.execute("UPDATE services SET status='listed' WHERE id=?", (ids["dups"][0],))
    got = {r["id"] for r in pg.candidates(c, 60)}
    assert ids["dups"][0] not in got and len(got) == 7
    recent = {r["id"] for r in pg.candidates(c, 60, now=datetime(2026, 10, 21, 1, 0).astimezone())}
    assert recent == set()
    c.close()
