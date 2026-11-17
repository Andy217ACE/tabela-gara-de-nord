# © 2026 Andy217Ace
"""app.backup_restore: fațada Val 4b (copie, verificare, restaurare, listare)."""
import sqlite3
import time

import pytest

from app import backup_restore as br
from app import restore
from app.store import Store


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(restore, "service_active", lambda p: False)
    p = tmp_path / "tabela.db"
    s = Store(str(p))
    s.migrate()
    s.close()
    return p


def test_list_backups_newest_first_and_keeps_five(live, tmp_path):
    d = tmp_path / "backups"
    for _ in range(7):
        br.make_backup(str(live), d)
        time.sleep(0.01)
    found = br.list_backups(d)
    assert len(found) == 5
    assert found == sorted(found, reverse=True)


def test_list_backups_missing_dir_is_empty(tmp_path):
    assert br.list_backups(tmp_path / "nope") == []


def test_truncated_backup_rejected_and_live_untouched(live, tmp_path):
    b = br.make_backup(str(live), tmp_path / "backups")
    bad = tmp_path / "bad.db"
    bad.write_bytes(b.read_bytes()[:100])
    assert br.verify_backup(bad) is False
    before = live.read_bytes()
    with pytest.raises(br.RestoreRefused):
        br.restore(bad, live, confirm=br.CONFIRM)
    assert live.read_bytes() == before


def test_restore_older_schema_is_migrated_by_store(live, tmp_path):
    b = br.make_backup(str(live), tmp_path / "backups")
    c = sqlite3.connect(b)
    c.execute("PRAGMA user_version = 8")
    c.commit()
    c.close()
    br.restore(b, live, confirm=br.CONFIRM)
    s = Store(str(live))
    s.migrate()  # nu aruncă: migrare, nu eroare
    s.close()
