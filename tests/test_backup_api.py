# © 2026 Andy217Ace
"""app.backup_api: copie online a bazei (WAL), verificare, retenție de 5 copii (Val 4b)."""
import sqlite3
import threading

import pytest

from app import backup_api
from app.store import SCHEMA_VERSION, Store


@pytest.fixture
def live(tmp_path):
    path = tmp_path / "tabela.db"
    s = Store(str(path))
    s.migrate()
    s.close()
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE IF NOT EXISTS keepme(x)")
    c.executemany("INSERT INTO keepme VALUES (?)", [(i,) for i in range(500)])
    c.commit()
    c.close()
    return path


def test_make_backup_is_a_valid_single_file_copy(live, tmp_path):
    dest = tmp_path / "backups"
    out = backup_api.make_backup(str(live), dest)
    assert out.parent == dest and out.name.endswith(f"-v{SCHEMA_VERSION}.db")
    assert backup_api.verify_backup(out) is True
    c = sqlite3.connect(f"file:{out}?mode=ro", uri=True)
    try:
        assert c.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert c.execute("PRAGMA journal_mode").fetchone()[0] != "wal"
        assert c.execute("SELECT count(*) FROM keepme").fetchone()[0] == 500
    finally:
        c.close()


def test_make_backup_online_while_a_writer_is_active(live, tmp_path):
    stop = threading.Event()
    errors = []

    def writer():
        try:
            w = sqlite3.connect(live, timeout=10)
            i = 1000
            while not stop.is_set():
                w.execute("INSERT INTO keepme VALUES (?)", (i,))
                w.commit()
                i += 1
            w.close()
        except sqlite3.Error as e:  # pragma: no cover - reported below
            errors.append(e)

    t = threading.Thread(target=writer)
    t.start()
    try:
        out = backup_api.make_backup(str(live), tmp_path / "b")
    finally:
        stop.set()
        t.join()
    assert not errors
    assert backup_api.verify_backup(out) is True


def test_verify_rejects_truncated_and_garbage_files(live, tmp_path):
    out = backup_api.make_backup(str(live), tmp_path / "b")
    data = out.read_bytes()
    cut = tmp_path / "cut.db"
    cut.write_bytes(data[: len(data) // 2])
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a database" * 100)
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    assert backup_api.verify_backup(cut) is False
    assert backup_api.verify_backup(junk) is False
    assert backup_api.verify_backup(empty) is False
    assert backup_api.verify_backup(tmp_path / "missing.db") is False


def test_verify_does_not_touch_the_live_database(live, tmp_path):
    before = live.read_bytes()
    out = backup_api.make_backup(str(live), tmp_path / "b")
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"x" * 4096)
    backup_api.verify_backup(out)
    backup_api.verify_backup(junk)
    assert live.read_bytes() == before


def test_keeps_exactly_five_copies(live, tmp_path):
    dest = tmp_path / "b"
    made = [backup_api.make_backup(str(live), dest) for _ in range(6)]
    kept = sorted(p.name for p in dest.glob("tabela-*.db"))
    assert len(kept) == 5
    assert made[-1].name in kept
    assert made[0].name not in kept


def test_keep_argument_is_honoured(live, tmp_path):
    dest = tmp_path / "b"
    for _ in range(3):
        backup_api.make_backup(str(live), dest, keep=2)
    assert len(list(dest.glob("tabela-*.db"))) == 2
