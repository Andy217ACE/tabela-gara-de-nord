# © 2026 Andy217Ace
"""Task 3.2b: the live matching never hands a reading of one train to a DISTINCT train.

Two numbers once read in the same capture on the same board (app.quality.coexisting_numbers)
are two real trains (R 5011 / R 5014): Pass 1b (majority partner), Pass 3 (fuzzy) and the
vote rename must not attribute one's readings to the other. OCR noise (a pair never read
together) still matches exactly as before.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import quality
from app.models import Row
from app.store import Store

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 10, 22, 4, 0, tzinfo=BUC)


def R(no, t="04:47", board="departure", station="BUZAU", **kw):
    return Row(board=board, train_type="R", train_no=no, station=station,
               operator="CFR Calatori", sched_time=t, delay_min=0, platform=None,
               station_raw=station, **kw)


def frame(*extra):
    """Three steady rows on each panel (a valid frame) plus `extra`."""
    return [R(1001, "05:40", board="arrival", station="BRASOV"),
            R(1002, "05:50", board="arrival", station="BRASOV"),
            R(1003, "06:00", board="arrival", station="BRASOV"),
            R(2001, "05:45"), R(2002, "05:55"), *extra]


def at(m: float) -> datetime:
    return T0 + timedelta(minutes=m)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def svc(store, no):
    return store._conn.execute("SELECT * FROM services WHERE train_no=?", (no,)).fetchone()


def coexist(store, a, b, board="departure", times=("04:47", "04:47")):
    """History: `a` and `b` read in one capture on `board` (at `times`)."""
    c = store._conn
    cap = c.execute("INSERT INTO captures(captured_at, image_hash, ok) VALUES (?, ?, 1)",
                    ("2026-10-21T03:00:00+00:00", f"h-{a}-{b}-{times}")).lastrowid
    for i, (no, t) in enumerate(zip((a, b), times)):
        c.execute("INSERT INTO observations(capture_id, service_id, board, row_index,"
                  " observed_at, train_no, sched_time, station, validation_state,"
                  " processing_version) VALUES (?, NULL, ?, ?, '2026-10-21T03:00:00+00:00',"
                  " ?, ?, 'BUZAU', 'ok', 't')", (cap, board, i, no, t))


def count_queries(monkeypatch):
    calls = []
    real = quality.coexisting_numbers

    def spy(conn, train_no, among, **kw):
        calls.append((train_no, tuple(among), kw))
        return real(conn, train_no, among, **kw)
    monkeypatch.setattr(quality, "coexisting_numbers", spy)
    return calls


def _majority_setup(store):
    """5011 read 6 frames, then a listed 5014 service with no readings of its own."""
    for m in range(6):
        store.ingest(frame(R(5011)), at(m))
    store._conn.execute(
        "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
        " sched_time, first_seen, last_seen, station_raw) VALUES ('departure', ?, 'R', 5014,"
        " 'BUZAU', 'CFR Calatori', '04:47', ?, ?, 'BUZAU')",
        (at(0).date().isoformat(), at(5).isoformat(), at(5).isoformat()))


# -- Pass 1b (majority partner) ---------------------------------------------------------------

def test_majority_pass_routes_ocr_noise_as_before(store):
    _majority_setup(store)
    store.ingest(frame(R(5014)), at(6))
    assert svc(store, 5011)["last_seen"] == at(6).isoformat()  # given to the majority
    assert svc(store, 5014)["last_seen"] == at(5).isoformat()


def test_majority_pass_never_feeds_a_coexisting_train(store):
    _majority_setup(store)
    coexist(store, 5011, 5014)
    store.ingest(frame(R(5014)), at(6))
    assert svc(store, 5014)["last_seen"] == at(6).isoformat()  # its own reading
    assert svc(store, 5011)["last_seen"] == at(5).isoformat()


# -- Pass 3 (fuzzy) ---------------------------------------------------------------------------

def test_fuzzy_misread_still_matches_when_never_read_together(store):
    store.ingest(frame(R(5011)), at(0))
    coexist(store, 5011, 9999)  # an unrelated pair does not block it
    store.ingest(frame(R(5014)), at(1))
    assert svc(store, 5014) is None  # a misread of 5011, no new service
    assert svc(store, 5011)["last_seen"] == at(1).isoformat()


def test_neighbours_at_other_times_do_not_block_a_misread(store):
    # review: R 5011 04:47 and R 5013 05:30 are on the board together all the time; a
    # one-digit misread of 5013's row as "5011 05:30" is still 5013 (slot-level rule)
    store.ingest(frame(R(5011), R(5013, "05:30")), at(0))
    coexist(store, 5011, 5013, times=("04:47", "05:30"))
    store.ingest(frame(R(5011), R(5011, "05:30")), at(1))
    assert store._conn.execute("SELECT COUNT(*) FROM services WHERE train_no IN"
                               " (5011, 5013)").fetchone()[0] == 2
    assert svc(store, 5013)["last_seen"] == at(1).isoformat()


def test_fuzzy_never_claims_a_coexisting_train(store):
    store.ingest(frame(R(5011)), at(0))
    coexist(store, 5011, 5014)
    store.ingest(frame(R(5014)), at(1))
    assert svc(store, 5014) is not None and svc(store, 5014)["status"] == "listed"
    assert svc(store, 5011)["last_seen"] == at(0).isoformat()


# -- vote rename ------------------------------------------------------------------------------

def test_rename_never_turns_a_train_into_a_coexisting_one(store):
    # votes for 1571 piled up on service 1574 while the pair was not known to coexist
    store.ingest(frame(R(1574, "05:30", station="GALATI")), at(0))
    sid = svc(store, 1574)["id"]
    store.ingest(frame(R(1571, "05:30", station="GALATI")), at(1))
    store.ingest(frame(R(1571, "05:30", station="GALATI")), at(2))
    coexist(store, 1571, 1574, times=("05:30", "05:30"))
    store._apart.clear()  # (the pair's cached "never together" expires)
    store.ingest(frame(R(1571, "05:30", station="GALATI")), at(3))
    assert store._conn.execute("SELECT train_no FROM services WHERE id=?",
                               (sid,)).fetchone()[0] == 1574


# -- cache ------------------------------------------------------------------------------------

def test_cache_second_identical_frame_does_not_query(store, monkeypatch):
    store.ingest(frame(R(5011)), at(0))
    calls = count_queries(monkeypatch)
    store.ingest(frame(R(5014)), at(1))
    store.ingest(frame(R(5014)), at(2))
    assert len(calls) == 1
    assert svc(store, 5014) is None  # (noise: matched to 5011 both times)


def test_cache_common_path_does_not_query(store, monkeypatch):
    calls = count_queries(monkeypatch)
    for m in range(3):
        store.ingest(frame(R(5011)), at(m))
    assert calls == []


def test_cached_false_is_promoted_by_a_frame_reading_both(store, monkeypatch):
    calls = count_queries(monkeypatch)
    store.ingest(frame(R(5011)), at(0))
    store.ingest(frame(R(5014)), at(1))  # noise so far: cached "never together"
    assert len(calls) == 1 and svc(store, 5014) is None
    store.ingest(frame(R(5011), R(5014)), at(2))  # both in the 04:47 slot: two real trains
    s14 = svc(store, 5014)
    assert s14 is not None
    store.ingest(frame(R(5014)), at(3))  # (observations of at(2) were never recorded here)
    assert svc(store, 5014)["last_seen"] == at(3).isoformat()
    assert svc(store, 5011)["last_seen"] == at(2).isoformat()
    assert len(calls) == 1  # known from the frame, no new query


def test_cached_false_expires(store, monkeypatch):
    store.ingest(frame(R(5011)), at(0))
    calls = count_queries(monkeypatch)
    store.ingest(frame(R(5014)), at(1))
    assert len(calls) == 1
    for k in store._apart:  # the short TTL ran out
        store._apart[k] = 0.0
    coexist(store, 5011, 5014)  # e.g. recorded by a capture this Store did not diff
    store.ingest(frame(R(5014)), at(2))
    assert len(calls) == 2
    assert svc(store, 5014) is not None
