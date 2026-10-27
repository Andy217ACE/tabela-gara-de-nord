# © 2026 Andy217Ace
"""app.dbbackup when the backup directory cannot be listed or written (Beta 1.31 hotfix).

Production (Beta 1.29): /var/lib/tabela/backups was root:root 0700 (created by update.sh
as root), the service runs as `tabela` -> Path.iterdir() raised PermissionError inside
store.migrate() and the app never started. The rule now: an unreadable backup directory
never crashes the start by itself; the database is migrated only when a backup is known
to exist (made now, in the backup dir or in the fallback dir next to the database, or
announced by update.sh through its marker file); otherwise the start is refused with an
explicit error and the database is left untouched."""
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

from app import dbbackup
from app.store import SCHEMA_VERSION, Store


def _v8_db(path: Path) -> None:
    """A populated database at schema v8 (the production state before Beta 1.29)."""
    s = Store(str(path))
    s.migrate()
    s.close()
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE IF NOT EXISTS keepme(x)")
    c.execute("INSERT INTO keepme VALUES (42)")
    for t in ("correction_audit", "correction_archive", "correction_batches", "corrections"):
        c.execute(f"DROP TABLE {t}")
    c.execute("PRAGMA user_version = 8")
    c.commit()
    c.close()


def _version(path: Path) -> int:
    c = sqlite3.connect(path)
    try:
        return c.execute("PRAGMA user_version").fetchone()[0]
    finally:
        c.close()


def _deny(monkeypatch, *dirs: Path) -> None:
    """Simulate `root:root 0700` for the service user: listing (Path.iterdir, os.scandir,
    os.listdir) and creating/writing inside these directories raise PermissionError."""
    denied = [os.path.normcase(os.path.abspath(d)) for d in dirs]

    def hit(p) -> bool:
        s = os.path.normcase(os.path.abspath(os.fspath(p)))
        return any(s == d or s.startswith(d + os.sep) for d in denied)

    real_iterdir, real_mkdir = Path.iterdir, Path.mkdir
    real_scandir, real_listdir, real_connect = os.scandir, os.listdir, sqlite3.connect

    def iterdir(self):
        if hit(self):
            raise PermissionError(13, "Permission denied", str(self))
        return real_iterdir(self)

    def mkdir(self, *a, **kw):
        if hit(self):
            raise PermissionError(13, "Permission denied", str(self))
        return real_mkdir(self, *a, **kw)

    def scandir(p="."):
        if hit(p):
            raise PermissionError(13, "Permission denied", str(p))
        return real_scandir(p)

    def listdir(p="."):
        if hit(p):
            raise PermissionError(13, "Permission denied", str(p))
        return real_listdir(p)

    def connect(db, *a, **kw):
        target = str(db)
        if not target.startswith("file:") and hit(target):
            raise sqlite3.OperationalError("unable to open database file")
        return real_connect(db, *a, **kw)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(os, "listdir", listdir)
    monkeypatch.setattr(dbbackup.sqlite3, "connect", connect)


@pytest.fixture
def db(tmp_path, monkeypatch):
    bk = tmp_path / "backups"
    bk.mkdir()
    monkeypatch.setenv("BACKUP_DIR", str(bk))
    path = tmp_path / "tabela.db"
    _v8_db(path)
    return path


def _errors(caplog):
    return [r for r in caplog.records if r.levelno >= logging.ERROR and r.name == "app.dbbackup"]


# -- (a) unlistable backup directory: the start does not crash --------------------------------

def test_unlistable_backup_dir_does_not_crash_and_backs_up_where_it_can(db, monkeypatch, caplog):
    bk = db.parent / "backups"

    def iterdir(self):
        if Path(self) == bk:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)
    real = Path.iterdir
    monkeypatch.setattr(Path, "iterdir", iterdir)
    caplog.set_level(logging.INFO, logger="app.dbbackup")
    s = Store(str(db))
    s.migrate()  # before the hotfix: PermissionError -> "Application startup failed"
    s.close()
    assert _version(db) == SCHEMA_VERSION
    made = list(bk.glob("tabela-*-v8.db"))
    assert len(made) == 1 and _version(made[0]) == 8
    errs = _errors(caplog)
    assert len(errs) == 1  # one clear ERROR: which directory and why
    assert str(bk) in errs[0].getMessage() and "Permission denied" in errs[0].getMessage()


def test_recent_backup_is_found_when_the_dir_is_listable(db):
    bk = db.parent / "backups"
    old = bk / "tabela-20260101-000000-v8.db"
    shutil.copy(db, old)
    assert dbbackup.ensure(str(db), 8) == old  # update.sh's copy is reused, no new one


def test_unlistable_and_unwritable_dir_uses_fallback_next_to_db(db, monkeypatch, caplog):
    bk = db.parent / "backups"
    _deny(monkeypatch, bk)
    caplog.set_level(logging.INFO, logger="app.dbbackup")
    s = Store(str(db))
    s.migrate()
    s.close()
    assert _version(db) == SCHEMA_VERSION
    fb = list((db.parent / dbbackup.FALLBACK_DIRNAME).glob("tabela-*-v8.db"))
    assert len(fb) == 1 and _version(fb[0]) == 8
    c = sqlite3.connect(fb[0])
    assert c.execute("SELECT x FROM keepme").fetchone()[0] == 42
    c.close()
    msgs = " ".join(r.getMessage() for r in _errors(caplog))
    assert str(bk) in msgs


def _marker(db: Path, version: int, age_s: float = 0.0, dbline: str | None = None) -> Path:
    m = db.parent / dbbackup.MARKER_NAME
    m.write_text(f"version={version}\nbackup=/var/lib/tabela/backups/tabela-x-v{version}.db\n"
                 f"db={dbline if dbline is not None else db}\n", encoding="utf-8")
    t = time.time() - age_s
    os.utime(m, (t, t))
    return m


def test_no_backup_anywhere_but_update_sh_marker_allows_migration(db, monkeypatch, caplog):
    _marker(db, 8)
    _deny(monkeypatch, db.parent / "backups", db.parent / dbbackup.FALLBACK_DIRNAME)
    caplog.set_level(logging.INFO, logger="app.dbbackup")
    s = Store(str(db))
    s.migrate()
    s.close()
    assert _version(db) == SCHEMA_VERSION
    assert "tabela-x-v8.db" in caplog.text  # the backup update.sh announced is logged


@pytest.mark.parametrize("kind", ["none", "old", "other_version", "other_db"])
def test_no_backup_and_no_valid_marker_refuses_to_migrate(db, monkeypatch, kind):
    if kind == "old":
        _marker(db, 8, age_s=dbbackup.RECENT_S + 60)
    elif kind == "other_version":
        _marker(db, 7)
    elif kind == "other_db":
        _marker(db, 8, dbline=str(db.parent / "other.db"))
    _deny(monkeypatch, db.parent / "backups", db.parent / dbbackup.FALLBACK_DIRNAME)
    s = Store(str(db))
    with pytest.raises(dbbackup.BackupUnavailable) as e:
        s.migrate()
    s.close()
    msg = str(e.value)
    assert "v8" in msg and str(db.parent / "backups") in msg and "update.sh" in msg
    assert _version(db) == 8  # untouched: nothing migrated without a known backup
    c = sqlite3.connect(db)
    assert c.execute("SELECT x FROM keepme").fetchone()[0] == 42
    c.close()


def test_nothing_to_protect_needs_no_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "bk"))
    _deny(monkeypatch, tmp_path / "bk", tmp_path / dbbackup.FALLBACK_DIRNAME)
    s = Store(str(tmp_path / "fresh.db"))  # brand-new database: nothing to back up
    s.migrate()
    s.close()
    assert _version(tmp_path / "fresh.db") == SCHEMA_VERSION


# -- (b) the real thing on this OS: a directory the current user cannot list --------------------

def _make_unlistable(d: Path):
    """Return an undo callable, or None when the OS will not deny us (root, no icacls)."""
    if os.name == "nt":
        icacls = shutil.which("icacls")
        user = os.environ.get("USERNAME")
        if not icacls or not user:
            return None
        r = subprocess.run([icacls, str(d), "/deny", f"{user}:(RD)"], capture_output=True)
        if r.returncode != 0:
            return None
        return lambda: subprocess.run([icacls, str(d), "/remove:d", user], capture_output=True)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return None
    os.chmod(d, 0)
    return lambda: os.chmod(d, 0o700)


def test_real_unlistable_backup_dir(db, caplog):
    bk = db.parent / "backups"
    undo = _make_unlistable(bk)
    if undo is None:
        pytest.skip("cannot deny directory listing to the current user here")
    try:
        try:
            list(bk.iterdir())
        except PermissionError:
            pass
        else:
            pytest.skip("the OS still lets the current user list the directory")
        caplog.set_level(logging.INFO, logger="app.dbbackup")
        s = Store(str(db))
        s.migrate()  # must not raise PermissionError
        s.close()
        assert _version(db) == SCHEMA_VERSION
        assert any(str(bk) in r.getMessage() for r in _errors(caplog))
    finally:
        undo()
    made = list(bk.glob("tabela-*-v8.db")) + list(
        (db.parent / dbbackup.FALLBACK_DIRNAME).glob("tabela-*-v8.db"))
    assert len(made) == 1 and _version(made[0]) == 8
