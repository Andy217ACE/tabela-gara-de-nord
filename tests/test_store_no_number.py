# © 2026 Andy217Ace
"""Un rând citit fără număr de tren (train_no 0) nu creează și nu modifică servicii."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import Row
from app.store import Store

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 11, 2, 12, 0, tzinfo=BUC)


def R(no, t="12:40", board="arrival", station="BRASOV", **kw):
    return Row(board=board, train_type="IR", train_no=no, station=station,
               operator="CFR Calatori", sched_time=t, delay_min=kw.pop("delay", 0),
               platform=kw.pop("platform", None), station_raw=station, **kw)


def frame(*extra):
    """Trei rânduri stabile pe fiecare panou (cadru valid) plus `extra`."""
    return [R(1001, "12:10"), R(1002, "12:20"), R(1003, "12:30"),
            R(2001, "12:15", board="departure"), R(2002, "12:25", board="departure"), *extra]


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def scalar(store, sql, *args):
    return store._conn.execute(sql, args).fetchone()[0]


def test_no_number_row_creates_no_service(store):
    store.ingest(frame(R(7908)), T0)  # 7908 citit corect
    ev = store.ingest(frame(R(7908), R(0, confidence=0.95)), T0 + timedelta(minutes=1))
    assert ev == []
    assert scalar(store, "SELECT COUNT(*) FROM services WHERE train_no=0") == 0
    assert scalar(store, "SELECT COUNT(*) FROM services WHERE train_no=7908") == 1


def test_no_number_row_does_not_change_existing_train(store):
    store.ingest(frame(R(7908)), T0)
    store.ingest(frame(R(7908), R(0, delay=15, platform=9, confidence=0.95)),
                 T0 + timedelta(minutes=1))
    s = store._conn.execute("SELECT train_no, sched_time, last_delay, last_platform"
                            " FROM services WHERE train_no=7908").fetchone()
    assert tuple(s) == (7908, "12:40", 0, None)


def test_no_number_row_alone_creates_nothing(store):
    store.ingest(frame(R(7908)), T0)
    store.ingest(frame(R(0, delay=15, confidence=0.95)), T0 + timedelta(minutes=1))
    assert scalar(store, "SELECT COUNT(*) FROM services WHERE train_no=0") == 0
    assert scalar(store, "SELECT last_delay FROM services WHERE train_no=7908") == 0


def test_no_number_row_is_not_fuzzy_matched_to_one_digit_train(store):
    """0 e o cifră de 5 (lev 1): fără filtru, Pass 3 ar lua trenul 5 ca misread."""
    store.ingest(frame(R(5)), T0)
    store.ingest(frame(R(0, delay=20, confidence=0.95)), T0 + timedelta(minutes=1))
    # trenul 5 nu e văzut în acest cadru: ultima lui vedere rămâne T0
    seen = store._conn.execute("SELECT last_seen FROM services WHERE train_no=5").fetchone()[0]
    assert seen == T0.isoformat()
    assert scalar(store, "SELECT COUNT(*) FROM services WHERE train_no=0") == 0


def test_no_number_rows_count_for_panel_judgement(store):
    """Rândurile fără număr rămân în contorul panoului: panoul nu e respins din cauza lor."""
    store.ingest(frame(R(0, "12:45", confidence=0.95),
                       R(0, "12:50", board="departure", confidence=0.95)), T0)
    assert store.last_rejected == {}
    assert scalar(store, "SELECT COUNT(*) FROM runs WHERE ok=1") == 1
