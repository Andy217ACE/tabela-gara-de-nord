# © 2026 Andy217Ace
"""Consensus per train over the frames (app.consensus): one misread frame does not decide."""
import json
from datetime import date

import pytest

from app import consensus
from app.store import Store

DAY = date(2026, 10, 20)
SD = DAY.isoformat()


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def _fields(delay=None, platform=None, check=None):
    d = {"norm": delay}
    if check:
        d["check"] = check
    return {"no": {"norm": 1234}, "time": {"norm": "10:00"}, "type": {"norm": "R"},
            "station": {"norm": "Cluj-Napoca"}, "operator": {"norm": "CFR Călători"},
            "delay": d, "platform": {"norm": platform}}


def _service(store, delay_stored=0):
    c = store._conn
    c.execute("INSERT INTO services(board, service_date, train_type, train_no, station,"
              " operator, sched_time, first_seen, last_seen, last_delay, status)"
              " VALUES ('arrival', ?, 'R', 1234, 'Cluj-Napoca', 'CFR Călători', '10:00',"
              " '2026-10-20T10:00:00', '2026-10-20T10:00:00', ?, 'listed')",
              (SD, delay_stored))
    return c.execute("SELECT id FROM services WHERE train_no=1234").fetchone()[0]


def _frames(store, sid, values, state="ok"):
    """One capture per frame, oldest first; `values` = delay norm per frame (or a dict)."""
    c = store._conn
    base = c.execute("SELECT COALESCE(MAX(id), 0) FROM captures").fetchone()[0]
    for i, v in enumerate(values):
        n = base + i + 1
        at = f"2026-10-20T{10 + n // 60:02d}:{n % 60:02d}:00+00:00"  # one frame a minute
        c.execute("INSERT INTO captures(captured_at, last_seen_at, image_hash, ok, n_rows,"
                  " processing_version) VALUES (?, ?, ?, 1, 1, 'test')",
                  (at, at, f"h{n:06d}"))
        cid = c.execute("SELECT id FROM captures WHERE image_hash=?",
                        (f"h{n:06d}",)).fetchone()[0]
        fields = v if isinstance(v, dict) else _fields(delay=v)
        c.execute("INSERT INTO observations(capture_id, service_id, board, row_index,"
                  " observed_at, fields_json, train_no, validation_state, processing_version)"
                  " VALUES (?, ?, 'arrival', 0, ?, ?, 1234, ?, 'test')",
                  (cid, sid, at, json.dumps(fields), state))


def test_one_misread_digit_in_three_of_twenty_frames_is_outvoted(store):
    sid = _service(store, delay_stored=17)  # the last reading (a misread) is what is stored
    seq = [12] * 20
    for i in (5, 11, 19):  # 12 read as 17 in three frames, the last one included
        seq[i] = 17
    _frames(store, sid, seq)
    cons = consensus.service_consensus(store._conn, [sid])
    assert cons[sid]["delay"] == 12
    board = store.current_board()["arrivals"]
    assert board[0]["delay_min"] == 12  # the live board shows the consensus, not the last read
    hist = store.history(DAY, train=1234)
    assert hist[0]["final_delay"] == 12
    assert hist[0]["max_delay"] >= 12


def test_only_the_last_fifteen_readings_vote(store):
    sid = _service(store)
    _frames(store, sid, [7] * 25 + [9] * 15)
    assert consensus.service_consensus(store._conn, [sid])[sid]["delay"] == 9


def test_mixed_readings_without_majority_stay_unsettled(store):
    sid = _service(store, delay_stored=20)
    _frames(store, sid, [10] * 5 + [20] * 5 + [30] * 5)  # 5 + 5 + 5 of the last 15
    cons = consensus.service_consensus(store._conn, [sid])
    assert "delay" not in cons.get(sid, {})  # no value invented
    assert store.current_board()["arrivals"][0]["delay_min"] == 20  # stored value stays


def test_too_few_votes_no_consensus(store):
    sid = _service(store)
    _frames(store, sid, [5, 5])  # two readings: below MIN_VOTES
    assert consensus.service_consensus(store._conn, [sid]) == {}


def test_unsafe_frames_do_not_vote(store):
    sid = _service(store)
    _frames(store, sid, [99] * 10, state="rejected_low_conf")
    _frames(store, sid, [5] * 3)
    assert consensus.service_consensus(store._conn, [sid])[sid]["delay"] == 5


def test_inferred_delay_does_not_vote_for_itself(store):
    sid = _service(store)
    inferred = _fields(delay=45, check="glare_inferred")
    _frames(store, sid, [inferred] * 10 + [15] * 3)
    assert consensus.service_consensus(store._conn, [sid])[sid]["delay"] == 15


def test_unread_delay_does_not_vote(store):
    sid = _service(store)
    _frames(store, sid, [None] * 12 + [4] * 3)
    assert consensus.service_consensus(store._conn, [sid])[sid]["delay"] == 4


def test_winner_needs_strict_majority_and_no_tie():
    assert consensus.winner([1, 1, 1, 2]) == 1           # 3 of 4: strict majority
    assert consensus.winner([1, 1, 2, 2]) is None        # tie
    assert consensus.winner([1, 1, 1, 2, 2, 2, 3, 3]) is None  # 3 of 8: not a majority
    assert consensus.winner([1, 1]) is None              # below MIN_VOTES
    assert consensus.winner([0, 0, 0, None, None]) == 0  # 0 (on time) is a value
