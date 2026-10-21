# © 2026 Andy217Ace
"""Schema v6: services.delay_read_at — proof that the delay cell was actually read."""
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
FIXTURE = Path(__file__).parent / "fixtures" / "live_v2.db"


def R(board, no, t, delay=0, **kw):
    return Row(board=board, train_type="IR", train_no=no, station="BRASOV",
               operator="CFR Calatori", sched_time=t, delay_min=delay, **kw)


def rows(over=None):
    over = over or {}
    base = [R("arrival", 1621, "12:10"), R("arrival", 1622, "12:20"),
            R("departure", 1731, "12:15"), R("departure", 1732, "12:30")]
    return [over.get(r.train_no, r) for r in base]


def version(s):
    return s._conn.execute("PRAGMA user_version").fetchone()[0]


def col(s, no, name="delay_read_at"):
    return s._conn.execute(f"SELECT {name} FROM services WHERE train_no=?", (no,)).fetchone()[0]


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def test_schema_version_is_6():
    assert SCHEMA_VERSION == 6


def test_fresh_db_has_column(store):
    assert version(store) == 6
    cols = {r[1] for r in store._conn.execute("PRAGMA table_info(services)")}
    assert "delay_read_at" in cols


def test_ingest_sets_delay_read_at_only_when_read(store):
    store.ingest(rows({1622: R("arrival", 1622, "12:20", delay_read=False)}), T0)
    assert col(store, 1621) == T0.isoformat()
    assert col(store, 1622) is None  # never read: no proof, stays NULL
    t1 = T0 + timedelta(minutes=1)
    store.ingest(rows({1621: R("arrival", 1621, "12:10", 5, delay_read=False)}), t1)
    assert col(store, 1621) == T0.isoformat()  # unread frame keeps the last proof
    assert col(store, 1621, "last_delay") == 0
    assert col(store, 1622) == t1.isoformat()  # read now
    t2 = T0 + timedelta(minutes=2)
    store.ingest(rows({1621: R("arrival", 1621, "12:10", 5)}), t2)
    assert col(store, 1621) == t2.isoformat()
    assert col(store, 1621, "last_delay") == 5


def _v5(tmp_path):
    """A v5 database (current schema minus delay_read_at) with legacy services."""
    p = tmp_path / "v5.db"
    s = Store(str(p))
    s.migrate()
    s.close()
    c = sqlite3.connect(p)
    c.execute("ALTER TABLE services DROP COLUMN delay_read_at")
    c.execute("PRAGMA user_version = 5")

    def svc(no, delay, first, last):
        return c.execute(
            "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
            " sched_time, first_seen, last_seen, last_delay, status) VALUES"
            " ('arrival','2026-10-20','IR',?,'BRASOV','CFR',?,?,?,?,'gone')",
            (no, "12:%02d" % (no % 60), first, last, delay)).lastrowid

    f, l = "2026-10-20T11:00:00+03:00", "2026-10-20T12:30:00+03:00"
    a = svc(1, 0, f, l)    # no evidence at all -> NULL
    b = svc(2, 7, f, l)    # non-zero delay can't be a default -> first_seen
    d = svc(3, 0, f, l)    # delay event 5 -> 0 only: a 0 is not proof
    e = svc(4, 12, f, l)   # delay event 0 -> 12 at 11:40
    g = svc(5, 0, f, l)    # observation with delay_read=1 (UTC stamp)
    c.execute("INSERT INTO events(service_id, ts, kind, old, new) VALUES"
              " (?, '2026-10-20T11:20:00+03:00', 'delay', '5', '0')", (d,))
    c.execute("INSERT INTO events(service_id, ts, kind, old, new) VALUES"
              " (?, '2026-10-20T11:40:00+03:00', 'delay', '0', '12')", (e,))
    cap = c.execute("INSERT INTO captures(captured_at, image_hash, ok) VALUES"
                    " ('2026-10-20T09:00:00+00:00', 'h', 1)").lastrowid
    for sid, read, at in ((g, 1, "2026-10-20T09:25:00+00:00"),
                          (g, 0, "2026-10-20T09:28:00+00:00"),
                          (e, 1, "2026-10-20T09:05:00+00:00")):
        c.execute("INSERT INTO observations(capture_id, service_id, board, row_index, observed_at,"
                  " delay_min, delay_read, validation_state, processing_version)"
                  " VALUES (?,?,'arrival',0,?,0,?,'ok','t')", (cap, sid, at, read))
    c.commit()
    c.close()
    return p, (a, b, d, e, g)


def test_v5_to_v6_backfill(tmp_path):
    p, (a, b, d, e, g) = _v5(tmp_path)
    s = Store(str(p))
    s.migrate()
    assert version(s) == 6
    got = dict(s._conn.execute("SELECT id, delay_read_at FROM services"))
    assert got[a] is None
    assert got[b] == "2026-10-20T11:00:00+03:00"
    assert got[d] is None
    # max(event 11:40 local, observation 09:05Z = 12:05 local) -> the observation
    assert got[e] == "2026-10-20T12:05:00+03:00"
    assert got[g] == "2026-10-20T12:25:00+03:00"  # stored in local time, like services
    s.migrate()  # idempotent
    assert dict(s._conn.execute("SELECT id, delay_read_at FROM services")) == got
    s.close()


def test_v6_failure_rolls_back(tmp_path, monkeypatch):
    p, _ = _v5(tmp_path)
    s = Store(str(p))
    import app.store as st

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(st, "_backfill_delay_read_at", boom)
    with pytest.raises(RuntimeError):
        s.migrate()
    assert version(s) == 5
    cols = {r[1] for r in s._conn.execute("PRAGMA table_info(services)")}
    assert "delay_read_at" not in cols
    s.close()


def test_live_fixture_migrates(tmp_path):
    p = tmp_path / "live.db"
    shutil.copy(FIXTURE, p)
    s = Store(str(p))
    s.migrate()
    assert version(s) == 6
    n = s._conn.execute("SELECT COUNT(*) FROM services").fetchone()[0]
    assert n > 0
    s.close()
