# © 2026 Andy217Ace
"""app.restore: restaurare doar cu confirmare, doar cu serviciul oprit, cu verificare și
copie de siguranță a stării curente (Val 4b)."""
import sqlite3

import pytest

from app import restore
from app.backup_api import make_backup
from app.store import SCHEMA_VERSION, Store


def _count(path, table="keepme"):
    c = sqlite3.connect(path)
    try:
        return c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        c.close()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(restore, "service_active", lambda db_path: False)
    db = tmp_path / "tabela.db"
    s = Store(str(db))
    s.migrate()
    s.close()
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE keepme(x)")
    c.executemany("INSERT INTO keepme VALUES (?)", [(i,) for i in range(100)])
    c.commit()
    c.close()
    backup = make_backup(str(db), tmp_path / "copies")  # 100 rows
    c = sqlite3.connect(db)
    c.executemany("INSERT INTO keepme VALUES (?)", [(i,) for i in range(100, 150)])  # newer
    c.commit()
    c.close()
    return db, backup


def test_refused_without_the_confirmation_token(env):
    db, backup = env
    with pytest.raises(restore.RestoreRefused):
        restore.restore(backup, db, confirm="")
    with pytest.raises(restore.RestoreRefused):
        restore.restore(backup, db, confirm="da")
    assert _count(db) == 150


def test_refused_while_the_service_runs(env, monkeypatch):
    db, backup = env
    monkeypatch.setattr(restore, "service_active", lambda db_path: True)
    with pytest.raises(restore.RestoreRefused, match="serviciul"):
        restore.restore(backup, db, confirm=restore.CONFIRM)
    assert _count(db) == 150


def test_corrupt_backup_is_refused_and_live_db_untouched(env, tmp_path):
    db, backup = env
    bad = tmp_path / "bad.db"
    bad.write_bytes(backup.read_bytes()[:1000])
    before = db.read_bytes()
    with pytest.raises(restore.RestoreRefused):
        restore.restore(bad, db, confirm=restore.CONFIRM)
    assert db.read_bytes() == before
    assert not list(db.parent.glob("*.restore-tmp"))


def test_restore_replaces_live_db_and_keeps_pre_restore_copy(env):
    db, backup = env
    restore.restore(backup, db, confirm=restore.CONFIRM)
    assert _count(db) == 100
    pre = [p for p in (db.parent / "backups").glob("tabela-*.db")
           if _count(p) == 150]
    assert len(pre) == 1  # the state before the restore is kept


def test_stale_wal_and_shm_do_not_survive_the_restore(env):
    db, backup = env
    (db.parent / (db.name + "-wal")).write_bytes(b"stale wal")
    (db.parent / (db.name + "-shm")).write_bytes(b"stale shm")
    restore.restore(backup, db, confirm=restore.CONFIRM)
    assert not (db.parent / (db.name + "-wal")).exists()
    assert not (db.parent / (db.name + "-shm")).exists()
    assert _count(db) == 100


def test_older_schema_copy_is_migrated_on_start(env):
    db, backup = env
    old = sqlite3.connect(backup)
    old.execute("PRAGMA user_version = 8")
    old.commit()
    old.close()
    restore.restore(backup, db, confirm=restore.CONFIRM)
    s = Store(str(db))
    s.migrate()
    s.close()
    c = sqlite3.connect(db)
    try:
        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        c.close()
