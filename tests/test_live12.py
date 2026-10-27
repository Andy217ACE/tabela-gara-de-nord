# © 2026 Andy217Ace
"""Beta 1.18: the LIVE board shows at most the 12 rows of a panel's last complete
frame. A train no longer read waits GONE_AFTER_MISSES frames before it is 'gone'
(unchanged); meanwhile it stays in the database and the history, but not on LIVE."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import Row
from app.store import GONE_AFTER_MISSES, PANEL_ROWS, Store

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=BUC)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def R(board, no, t, station):
    return Row(board=board, train_type="IR", train_no=no, station=station,
               operator="CFR Calatori", sched_time=t, station_raw=station)


def panel(board, first, n, base=1600):
    """`n` rows of `board` starting with the `first`-th train (times 12:10, 12:15...)."""
    return [R(board, base + k, f"{12 + (10 + 5 * k) // 60:02d}:{(10 + 5 * k) % 60:02d}",
              f"ST {board[0]}{k}") for k in range(first, first + n)]


def frame(first_arr=0, n_arr=PANEL_ROWS, first_dep=0, n_dep=PANEL_ROWS):
    return panel("arrival", first_arr, n_arr) + panel("departure", first_dep, n_dep, base=1700)


def at(m):
    return T0 + timedelta(minutes=m)


def nos(store, key="arrivals", **kw):
    return [r["train_no"] for r in store.current_board(**kw)[key]]


def test_panel_rows_is_twelve():
    assert PANEL_ROWS == 12


def test_complete_frame_hides_train_waiting_to_go(store):
    store.ingest(frame(), at(0))
    assert len(nos(store)) == 12
    store.ingest(frame(first_arr=1), at(1))  # 1600 left, 1612 came in: 13 listed
    listed = store._conn.execute(
        "SELECT COUNT(*) FROM services WHERE board='arrival' AND status='listed'").fetchone()[0]
    assert listed == 13
    live = nos(store)
    assert len(live) == 12 and 1600 not in live and 1612 in live
    assert len(nos(store, "departures")) == 12


def test_waiting_train_kept_in_db_and_history_and_goes_gone_as_before(store):
    for m in range(-5, 1):  # read often enough not to be judged a one-off ghost
        store.ingest(frame(), at(m))
    ev = store.ingest(frame(first_arr=1), at(1))
    assert not [e for e in ev if e.kind == "gone"]
    s = store._conn.execute(
        "SELECT status, miss_count FROM services WHERE train_no=1600").fetchone()
    assert s["status"] == "listed" and s["miss_count"] == 1
    hist = [h["train_no"] for h in store.history(T0.date())]
    assert 1600 in hist
    gone = []
    for m in range(2, 2 + GONE_AFTER_MISSES):
        gone += [e.row.train_no for e in store.ingest(frame(first_arr=1), at(m))
                 if e.kind == "gone"]
    assert gone == [1600]  # the GONE rule and its event are unchanged
    assert 1600 in [h["train_no"] for h in store.history(T0.date())]


def test_train_back_after_one_miss_shows_again(store):
    store.ingest(frame(), at(0))
    store.ingest(frame(first_arr=1), at(1))
    assert 1600 not in nos(store)
    store.ingest(frame(), at(2))
    assert 1600 in nos(store)


def test_incomplete_frame_hides_nothing(store):
    store.ingest(frame(), at(0))
    store.ingest(frame(first_arr=1, n_arr=10), at(1))  # 10 of 12 rows read
    live = nos(store)
    assert 1600 in live and len(live) == 12
    assert len(nos(store, "departures")) == 12


def test_rejected_panel_hides_nothing(store):
    store.ingest(frame(), at(0))
    store.ingest(frame(first_arr=1), at(1))
    assert 1600 not in nos(store)
    store.ingest(frame(first_arr=1, n_arr=2), at(2))  # arrivals panel rejected
    assert "arrival" in store.last_rejected
    assert 1600 in nos(store)


def test_stale_panel_hides_nothing(store):
    store.ingest(frame(), at(0))
    store.ingest(frame(first_arr=1), at(1))
    assert 1600 not in nos(store, now=at(2), stale_s=180)
    assert 1600 in nos(store, now=at(10), stale_s=180)


def test_after_restart_nothing_hidden(store):
    store.ingest(frame(), at(0))
    store.ingest(frame(first_arr=1), at(1))
    fresh = Store.__new__(Store)
    fresh.__dict__.update(store.__dict__)
    fresh._complete = {}  # in-memory state lost
    assert 1600 in [r["train_no"] for r in fresh.current_board()["arrivals"]]


def test_api_board_shows_at_most_twelve_per_panel(monkeypatch):
    from fastapi.testclient import TestClient

    from app.api import create_app
    from tests.test_api import settings
    now = datetime.now(BUC).replace(second=0, microsecond=0)
    app = create_app(settings(), start_poller=False)
    with TestClient(app) as c:
        st = c.app.state.store
        st.ingest(frame(), now - timedelta(minutes=1))
        st.ingest(frame(first_arr=1, first_dep=2), now)
        body = c.get("/api/board").json()
        assert len(body["arrivals"]) == 12 and len(body["departures"]) == 12
        assert 1600 not in [r["train_no"] for r in body["arrivals"]]
