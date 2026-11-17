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
