# © 2026 Andy217Ace
"""Journey final-result rules (Etapa C): final_confirmed only with evidence."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import journeys
from app.models import Row
from app.store import Store

BUC = ZoneInfo("Europe/Bucharest")


def iso(h, m, s=0):
    return datetime(2026, 10, 20, h, m, s, tzinfo=BUC).isoformat()


def svc(**kw):
    base = dict(id=1, board="arrival", service_date="2026-10-20", train_type="IR", train_no=1621,
                station="BRASOV", operator="CFR Calatori", sched_time="12:10",
                first_seen=iso(11, 30), last_seen=iso(12, 20), last_delay=5, last_platform=3,
                status="gone", uncertain=0, delay_read_at=iso(12, 10), gone_at=iso(12, 22),
                appeared_at=iso(11, 30))
    base.update(kw)
    return base


def test_confirmed_with_read_delay_and_late_disappearance():
    r = journeys.result(svc(), gap_min=15)
    assert r["state"] == "confirmed"
    assert r["final_delay"] == 5 and r["observed_delay"] == 5
    assert r["estimated_at"] == iso(12, 15)
    assert r["disappeared_at"] == iso(12, 22)
    assert r["reason"] is None


def test_in_progress_while_listed():
    r = journeys.result(svc(status="listed", gone_at=None), gap_min=15)
    assert r["state"] == "in_progress" and r["final_delay"] is None


def test_unknown_without_any_delay_reading():
    r = journeys.result(svc(delay_read_at=None, last_delay=0), gap_min=15)
    assert r["state"] == "unknown"
    assert r["observed_delay"] is None and r["final_delay"] is None  # missing is not 0
    assert r["estimated_at"] is None


def test_unconfirmed_when_disappearance_not_observed():
    r = journeys.result(svc(gone_at=None), gap_min=15)
    assert r["state"] == "unconfirmed" and "nu a fost observată" in r["reason"]
    assert r["final_delay"] is None and r["observed_delay"] == 5


def test_reappeared_after_gone_then_retired_silently_is_unconfirmed():
    r = journeys.result(svc(gone_at=iso(12, 0), appeared_at=iso(12, 5)), gap_min=15)
    assert r["state"] == "unconfirmed"


def test_unconfirmed_when_gone_before_estimated_time():
    r = journeys.result(svc(gone_at=iso(12, 14), delay_read_at=iso(12, 10)), gap_min=15)
    assert r["state"] == "unconfirmed" and "12:15" in r["reason"]


def test_unconfirmed_when_last_reading_too_old():
    r = journeys.result(svc(delay_read_at=iso(11, 40), gone_at=iso(12, 22)), gap_min=15)
    assert r["state"] == "unconfirmed" and "15 min" in r["reason"]
    assert journeys.result(svc(delay_read_at=iso(11, 40)), gap_min=60)["state"] == "confirmed"


def test_service_date_after_midnight():
    r = journeys.result(svc(service_date="2026-10-21", sched_time="00:05",
                            gone_at=datetime(2026, 10, 21, 0, 20, tzinfo=BUC).isoformat(),
                            delay_read_at=datetime(2026, 10, 21, 0, 10, tzinfo=BUC).isoformat()),
                        gap_min=15)
    assert r["sched_at"].startswith("2026-10-21T00:05")
    assert r["state"] == "confirmed"


def test_gap_from_env(monkeypatch):
    monkeypatch.setenv("FINAL_READ_MAX_GAP_MIN", "40")
    assert journeys.final_gap_min() == 40
    monkeypatch.setenv("FINAL_READ_MAX_GAP_MIN", "x")
    assert journeys.final_gap_min() == 15
    monkeypatch.setenv("FINAL_READ_MAX_GAP_MIN", "0")
    assert journeys.final_gap_min() == 15


# ---- integration with the store -------------------------------------------------

def R(board, no, t, delay=0, **kw):
    return Row(board=board, train_type="IR", train_no=no, station="BRASOV",
               operator="CFR Calatori", sched_time=t, delay_min=delay, **kw)


def frame(skip=(), **delays):
    out = []
    for board, nos in (("arrival", (1621, 1622, 1623)), ("departure", (1731, 1732, 1733))):
        for i, no in enumerate(nos):
            if no in skip:
                continue
            d = delays.get(f"t{no}", 0)
            out.append(R(board, no, "12:%02d" % (10 + 10 * i), d))
    return out


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def at(h, m):
    return datetime(2026, 10, 20, h, m, tzinfo=BUC)


@pytest.mark.usefixtures("legacy_rules")  # journey rules, not debounce
def test_store_journey_confirmed_end_to_end(store):
    store.ingest(frame(), at(12, 0))
    store.ingest(frame(t1621=5), at(12, 8))
    store.ingest(frame(skip=(1621,)), at(12, 16))
    store.ingest(frame(skip=(1621,)), at(12, 17))
    sid = store._conn.execute("SELECT id FROM services WHERE train_no=1621").fetchone()[0]
    d = journeys.detail(store, sid)
    assert d["status"] == "gone"
    assert d["result"]["state"] == "confirmed" and d["result"]["final_delay"] == 5
    assert d["service_date"] == "2026-10-20"
    kinds = [e["kind"] for e in d["events"]]
    assert kinds[0] == "appeared" and kinds[-1] == "gone" and "delay" in kinds
    vals = [p["delay"] for p in d["delay_series"]]
    assert vals == [5]  # the 0 of the first frame was read too but only events/obs are points


@pytest.mark.usefixtures("legacy_rules")  # journey rules, not debounce
def test_store_journey_unread_delay_is_unknown(store):
    rows = frame()
    rows[0] = R("arrival", 1621, "12:10", 0, delay_read=False)
    store.ingest(rows, at(12, 0))
    store.ingest(frame(skip=(1621,)), at(12, 16))
    store.ingest(frame(skip=(1621,)), at(12, 17))
    sid = store._conn.execute("SELECT id FROM services WHERE train_no=1621").fetchone()[0]
    assert journeys.detail(store, sid)["result"]["state"] == "unknown"


def test_detail_missing():
    s = Store(":memory:")
    s.migrate()
    assert journeys.detail(s, 999) is None
    s.close()


def test_series_skips_unapplied_observation(store):
    store.ingest(frame(t1621=15), at(12, 0))
    store.ingest(frame(t1621=945), at(12, 1))  # held: not applied
    store.ingest(frame(t1621=16), at(12, 2))
    store.ingest(frame(t1621=16), at(12, 3))  # a change is applied when read twice
    sid = store._conn.execute("SELECT id FROM services WHERE train_no=1621").fetchone()[0]
    c = store._conn
    cap = c.execute("INSERT INTO captures(captured_at, image_hash, ok) VALUES ('x','h',1)").lastrowid
    for k, (v, state) in enumerate(((15, "ok"), (945, "ok"), (16, "ok"), (99, "rejected_low_conf"))):
        c.execute("INSERT INTO observations(capture_id, service_id, board, row_index, observed_at,"
                  " delay_min, delay_read, validation_state, processing_version)"
                  " VALUES (?,?,'arrival',0,?,?,1,?,'t')",
                  (cap, sid, at(12, k).isoformat(), v, state))
    vals = [p["delay"] for p in journeys.detail(store, sid)["delay_series"]]
    assert 945 not in vals and 99 not in vals and vals[-1] == 16


def test_series_skips_repeated_plus_misread(store):
    """Beta 1.13: "+45" read "+465" in two consecutive glared frames is not drawn (a value
    >= DELAY_BIG is drawn only when the store applied it)."""
    store.ingest(frame(t1621=45), at(12, 0))
    store.ingest(frame(t1621=45), at(12, 1))
    sid = store._conn.execute("SELECT id FROM services WHERE train_no=1621").fetchone()[0]
    c = store._conn
    cap = c.execute("INSERT INTO captures(captured_at, image_hash, ok) VALUES ('x','h2',1)").lastrowid
    for k, v in enumerate((45, 465, 465, 45)):
        c.execute("INSERT INTO observations(capture_id, service_id, board, row_index, observed_at,"
                  " delay_min, delay_read, validation_state, processing_version)"
                  " VALUES (?,?,'arrival',0,?,?,1,'ok','t')",
                  (cap, sid, at(12, 2 + k).isoformat(), v))
    vals = [p["delay"] for p in journeys.detail(store, sid)["delay_series"]]
    assert 465 not in vals and 45 in vals


def test_plus_revert():
    assert journeys.plus_revert({"old": "410", "new": "10"})
    assert journeys.plus_revert({"old": "240", "new": "20"})
    assert not journeys.plus_revert({"old": "40", "new": "10"})
    assert not journeys.plus_revert({"old": None, "new": "10"})
