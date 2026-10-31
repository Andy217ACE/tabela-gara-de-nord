# © 2026 Andy217Ace
"""app.export: export CSV al istoricului (Val 4b): antet fix, interval ≤ 366 zile, limită
de rânduri, fără corecții și note, cerere limitată."""
import csv
import io
import sqlite3

import pytest

from app import export
from app.store import Store


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "tabela.db"
    s = Store(str(path))
    s.migrate()
    s.close()
    c = sqlite3.connect(path)
    rows = [
        # (board, date, train, station, sched, last_delay, delay_read_at, platform)
        ("departure", "2026-10-10", 1234, "BUCUREȘTI NORD", "08:10", 5, "2026-10-10T08:12:00", 3),
        ("departure", "2026-10-10", 1234, "BUCUREȘTI NORD", "08:40", 0, None, None),
        ("arrival", "2026-10-11", 555, "CRAIOVA", "09:00", 12, "2026-10-11T09:01:00", None),
        ("arrival", "2026-12-31", 555, "CRAIOVA", "09:00", 0, None, None),
    ]
    for i, (board, d, no, st, sched, delay, read, plat) in enumerate(rows, start=1):
        c.execute(
            "INSERT INTO services (id, board, service_date, train_type, train_no, station,"
            " operator, sched_time, first_seen, last_seen, last_delay, last_platform,"
            " delay_read_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (i, board, d, "R", no, st, "CFR", sched, d + "T06:00:00", d + "T07:00:00",
             delay, plat, read))
    c.commit()
    c.close()
    return path


def _rows(text):
    return list(csv.reader(io.StringIO(text)))


def test_header_is_fixed_and_has_no_correction_or_note_columns(db):
    text, truncated = export.history_csv(str(db), "2026-10-01", "2026-10-31")
    head = _rows(text)[0]
    assert tuple(head) == export.HEADER
    lowered = " ".join(head).lower()
    assert "corr" not in lowered and "nota" not in lowered and "note" not in lowered
    assert truncated is False


def test_rows_in_interval_with_known_and_unknown_delays(db):
    text, _ = export.history_csv(str(db), "2026-10-01", "2026-10-31")
    body = _rows(text)[1:]
    assert body == [
        ["2026-10-10", "08:10", "1234", "BUCUREȘTI NORD", "5", "3"],
        ["2026-10-10", "08:40", "1234", "BUCUREȘTI NORD", "", ""],
        ["2026-10-11", "09:00", "555", "CRAIOVA", "12", ""],
    ]


def test_train_filter(db):
    text, _ = export.history_csv(str(db), "2026-10-01", "2026-12-31", train="1234")
    assert {r[2] for r in _rows(text)[1:]} == {"1234"}


def test_interval_over_366_days_is_refused(db):
    with pytest.raises(export.ExportRefused) as e:
        export.history_csv(str(db), "2025-10-01", "2026-10-03")  # 367 days
    assert e.value.status == 422
    export.history_csv(str(db), "2025-10-01", "2026-10-02")  # 366 days: allowed


def test_inverted_or_malformed_dates_are_refused(db):
    for a, b in (("2026-10-05", "2026-10-01"), ("2026/10/01", "2026-10-05"), ("", "")):
        with pytest.raises(export.ExportRefused) as e:
            export.history_csv(str(db), a, b)
        assert e.value.status == 422


def test_row_limit_truncates_and_flags(db, monkeypatch):
    monkeypatch.setattr(export, "MAX_ROWS", 2)
    text, truncated = export.history_csv(str(db), "2026-10-01", "2026-10-31")
    assert len(_rows(text)) - 1 == 2
    assert truncated is True


def test_ghost_services_are_left_out(db):
    c = sqlite3.connect(db)
    c.execute("INSERT INTO service_quality (service_id, ghost, updated_at)"
              " VALUES (1, 1, '2026-10-10T09:00:00')")
    c.commit()
    c.close()
    text, _ = export.history_csv(str(db), "2026-10-01", "2026-10-31")
    assert ["2026-10-10", "08:10", "1234", "BUCUREȘTI NORD", "5", "3"] not in _rows(text)[1:]


def test_rate_limit_per_client(db):
    lim = export.RateLimiter(limit=3, window_s=60)
    for _ in range(3):
        assert lim.allow("1.2.3.4", now=100.0)
    assert lim.allow("1.2.3.4", now=100.0) is False
    assert lim.allow("5.6.7.8", now=100.0) is True
    assert lim.allow("1.2.3.4", now=161.0) is True  # window passed
