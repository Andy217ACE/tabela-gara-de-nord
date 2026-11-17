# © 2026 Andy217Ace
"""Export CSV: caractere românești și stații cu virgulă rămân valide (Review Focus 3)."""
import csv
import io
import sqlite3

import pytest

from app import export
from app.store import Store


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    s = Store(str(p))
    s.migrate()
    s.close()
    c = sqlite3.connect(p)
    c.execute(
        "INSERT INTO services (id, board, service_date, train_type, train_no, station,"
        " operator, sched_time, first_seen, last_seen, last_delay, last_platform)"
        " VALUES (1,'departure','2026-10-10','R',1234,'TÂRGU MUREȘ, VEST','CFR','08:10',"
        "'2026-10-10T06:00:00','2026-10-10T07:00:00',5,3)")
    c.commit()
    c.close()
    return str(p)


def test_comma_and_diacritics_roundtrip(db):
    text, _ = export.history_csv(db, "2026-10-10", "2026-10-10")
    rows = list(csv.reader(io.StringIO(text)))
    assert tuple(rows[0]) == export.HEADER
    assert rows[1][3] == "TÂRGU MUREȘ, VEST"
    assert len(rows[1]) == len(export.HEADER)
    assert '"TÂRGU MUREȘ, VEST"' in text  # ghilimele în jurul virgulei


def test_over_366_days_is_422(db):
    with pytest.raises(export.ExportRefused) as e:
        export.history_csv(db, "2025-01-01", "2026-10-10")
    assert e.value.status == 422


def test_export_csv_has_utf8_bom(monkeypatch, tmp_path):
    """Excel citește diacriticele din CSV doar dacă fișierul începe cu BOM UTF-8."""
    from fastapi.testclient import TestClient
    from app import export
    from app.api import create_app
    from app.config import Settings

    monkeypatch.setattr(export, "history_csv", lambda *a, **k: ("Stație,Întârziere\nBucureşti,5\n", False))
    monkeypatch.setenv("CAPTURE_DIR", str(tmp_path / "captures"))
    cfg = Settings(db_path=str(tmp_path / "t.db"), source_url="https://example.com/x",
                   vapid_private_key="", vapid_public_key="", vapid_subject="mailto:a@b.c",
                   tesseract_cmd="tesseract-does-not-exist", poller_restart_backoff=0.01)
    with TestClient(create_app(cfg)) as client:
        r = client.get("/api/export/history.csv?from=2026-10-01&to=2026-10-31")
    assert r.status_code == 200
    assert r.content.startswith(b"\xef\xbb\xbf")
    assert r.content[3:].decode("utf-8").startswith("Stație,Întârziere")
