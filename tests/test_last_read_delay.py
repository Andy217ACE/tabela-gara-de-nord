# © 2026 Andy217Ace
"""Reflexie pe rând: pe tablă rămâne ultima întârziere citită sigur a trenului, cu vechimea
ei (`delay_last_read_age_s`), doar cât timp e recentă; trenul e legat de serviciu, nu de rând."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import Row
from app.store import DELAY_LAST_READ_MAX_S, Store

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=BUC)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def R(no, t, delay=0, read=True, row_station="BRASOV"):
    return Row(board="arrival", train_type="IR", train_no=no, station=row_station,
               operator="CFR Calatori", sched_time=t, station_raw=row_station,
               delay_min=delay, delay_read=read)


def at(m):
    return T0 + timedelta(minutes=m)


def frame(train):
    """A plausible frame (both panels read) with the train on the arrivals panel."""
    arr = [R(1600 + k, f"12:{10 + k:02d}", 0, row_station=f"ST {k}") for k in range(2)]
    dep = [Row(board="departure", train_type="IR", train_no=1700 + k, station=f"ST D{k}",
               operator="CFR Calatori", sched_time=f"12:{10 + k:02d}", station_raw=f"ST D{k}")
           for k in range(3)]
    return arr + [train] + dep


def seen_ok(store, train, minutes=(0, 1, 2, 3, 4)):
    """The train read on several frames (a ghost is one seen for under 2 minutes)."""
    for m in minutes:
        store.ingest(frame(train), at(m))


def board_row(store, no, now):
    rows = store.current_board(now)["arrivals"]
    return next(r for r in rows if r["train_no"] == no)


def test_last_safe_reading_kept_with_age(store):
    seen_ok(store, R(1234, "12:40", 15), (0, 1))  # two readings: the change is confirmed
    store.ingest(frame(R(1234, "12:40", 0, read=False)), at(3))  # glare: unreadable
    row = board_row(store, 1234, at(3))
    assert row["delay_min"] == 15 and row["delay_read"] is False
    assert row["delay_last_read_age_s"] == 120  # the reading of minute 1, two minutes ago


def test_last_reading_expires_after_threshold(store):
    seen_ok(store, R(1234, "12:40", 15), (0, 1))
    store.ingest(frame(R(1234, "12:40", 0, read=False)), at(2))
    late = at(1) + timedelta(seconds=DELAY_LAST_READ_MAX_S + 1)
    assert board_row(store, 1234, late)["delay_last_read_age_s"] is None


def test_never_read_delay_gives_no_age(store):
    seen_ok(store, R(1234, "12:40", 0, read=False))
    row = board_row(store, 1234, at(4))
    assert row["delay_read"] is False and row["delay_last_read_age_s"] is None


def test_readable_delay_has_no_last_read_label(store):
    seen_ok(store, R(1234, "12:40", 15), (0, 1, 2))
    row = board_row(store, 1234, at(2))
    assert row["delay_read"] is True and row["delay_min"] == 15
    assert row["delay_last_read_age_s"] == 0
