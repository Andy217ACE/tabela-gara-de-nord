# © 2026 Andy217Ace
"""Hotfix Beta 1.02: one-character misreads, low-confidence new services,
partial panel reads (per-panel ingest) and rejected-frame capture."""
import asyncio
import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import pytest

from app import poller, rejected
from app.models import Row
from app.store import (CONFIRM_CONFIDENCE, PARTIAL_ACCEPT_AFTER, Store)

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=BUC)
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def R(board, no, t, station="BRASOV", **kw):
    return Row(board=board, train_type="IR", train_no=no, station=station,
               operator="CFR Calatori", sched_time=t, station_raw=station, **kw)


def frame(n_arr=3, n_dep=3, **over):
    """A plausible frame; `over` replaces rows by (board, index)."""
    rows = [R("arrival", 1600 + k, f"12:{10 + k:02d}", station=f"ST A{k}") for k in range(n_arr)]
    rows += [R("departure", 1700 + k, f"12:{10 + k:02d}", station=f"ST D{k}")
             for k in range(n_dep)]
    return rows


def services(store, where="1=1"):
    return store._conn.execute(
        f"SELECT board, train_no, sched_time, status FROM services WHERE {where}"
        " ORDER BY board, train_no").fetchall()


def at(m):
    return T0 + timedelta(minutes=m)


# -- one-character misreads ----------------------------------------------------

def test_misread_train_digit_does_not_duplicate(store):
    base = frame() + [R("arrival", 1234, "12:40")]
    store.ingest(base, at(0))
    misread = frame() + [R("arrival", 1284, "12:40")]  # "3" read as "8" in one frame
    ev = store.ingest(misread, at(1))
    assert [e for e in ev if e.kind == "appeared"] == []
    store.ingest(base, at(2))
    store.ingest(base, at(3))
    nos = [s["train_no"] for s in services(store, "board='arrival'")]
    assert nos.count(1234) == 1 and 1284 not in nos
    assert not services(store, "status='gone'")
    board = [r["train_no"] for r in store.current_board()["arrivals"]]
    assert board.count(1234) == 1 and 1284 not in board


def test_dropped_digit_does_not_duplicate(store):
    store.ingest(frame() + [R("arrival", 1234, "12:40")], at(0))
    store.ingest(frame() + [R("arrival", 234, "12:40")], at(1))  # leading "1" unread
    assert [s["train_no"] for s in services(store, "board='arrival'")].count(234) == 0


def test_misread_time_digit_does_not_duplicate(store):
    store.ingest(frame() + [R("departure", 10021, "06:52")], at(0))
    ev = store.ingest(frame() + [R("departure", 10021, "05:52")], at(1))
    assert [e for e in ev if e.kind == "appeared"] == []
    assert len(services(store, "train_no=10021")) == 1


def test_really_different_trains_stay_two(store):
    # two digits differ
    store.ingest(frame() + [R("arrival", 1234, "12:40"), R("arrival", 1567, "12:40")], at(0))
    assert len(services(store, "train_no IN (1234, 1567)")) == 2
    # one digit differs but another station
    store.ingest(frame() + [R("arrival", 1234, "12:40"), R("arrival", 1567, "12:40"),
                            R("arrival", 1284, "12:40", station="SINAIA")], at(1))
    assert len(services(store, "train_no IN (1234, 1567, 1284)")) == 3


def test_one_digit_apart_both_on_the_same_frame_are_two_trains(store):
    store.ingest(frame() + [R("arrival", 1234, "12:40")], at(0))
    store.ingest(frame() + [R("arrival", 1234, "12:40"), R("arrival", 1284, "12:40")], at(1))
    assert len(services(store, "train_no IN (1234, 1284)")) == 2


def test_one_digit_apart_read_together_both_stay_on_the_board(store):
    store.ingest(frame() + [R("arrival", 1234, "12:40"), R("arrival", 1284, "12:40")], at(0))
    arr = [r["train_no"] for r in store.current_board()["arrivals"]]
    assert 1234 in arr and 1284 in arr


def test_stored_misread_is_renamed_when_the_other_reading_persists(store):
    store.ingest(frame() + [R("arrival", 1284, "12:40")], at(0))  # first reading misread
    sid = store._conn.execute("SELECT id FROM services WHERE train_no=1284").fetchone()[0]
    for m in (1, 2):
        store.ingest(frame() + [R("arrival", 1234, "12:40")], at(m))
        assert services(store, "train_no=1284")  # not yet
    ev = store.ingest(frame() + [R("arrival", 1234, "12:40")], at(3))
    assert [e for e in ev if e.kind == "appeared"] == []
    row = store._conn.execute("SELECT id, train_no FROM services WHERE train_no=1234").fetchone()
    assert tuple(row) == (sid, 1234) and not services(store, "train_no=1284")
    assert [r["train_no"] for r in store.current_board()["arrivals"]].count(1234) == 1


def test_no_rename_when_the_stored_reading_comes_back(store):
    store.ingest(frame() + [R("arrival", 1234, "12:40")], at(0))
    for m, no in enumerate((1284, 1284, 1234, 1284, 1284), start=1):
        store.ingest(frame() + [R("arrival", no, "12:40")], at(m))
    assert services(store, "train_no=1234") and not services(store, "train_no=1284")


def test_board_api_collapses_leftover_near_duplicates(store):
    store.ingest(frame() + [R("arrival", 1234, "12:40")], at(0))
    # a duplicate created before the hotfix (e.g. live DB): inserted directly
    store._conn.execute(
        "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
        " sched_time, first_seen, last_seen, station_raw) VALUES"
        " ('arrival', '2026-10-20', 'IR', 1284, 'BRASOV', 'CFR Calatori', '12:40', ?, ?,"
        " 'BRASOV')", (at(-1).isoformat(), at(-1).isoformat()))
    arr = [r["train_no"] for r in store.current_board()["arrivals"]]
    assert (arr.count(1234), arr.count(1284)) == (1, 0)  # the most recently read stays


# -- low-confidence new services ----------------------------------------------

def test_low_confidence_new_service_needs_a_second_reading(store):
    store.ingest(frame(), at(0))
    weak = R("arrival", 1999, "12:50", confidence=CONFIRM_CONFIDENCE - 0.1)
    ev = store.ingest(frame() + [weak], at(1))
    assert ev == [] and not services(store, "train_no=1999")
    assert 1999 not in [r["train_no"] for r in store.current_board()["arrivals"]]
    ev = store.ingest(frame() + [weak], at(2))  # second consecutive reading confirms it
    assert [e.kind for e in ev] == ["appeared"]
    first = store._conn.execute(
        "SELECT first_seen FROM services WHERE train_no=1999").fetchone()[0]
    assert first == at(1).isoformat()


def test_low_confidence_new_service_not_confirmed_if_not_consecutive(store):
    weak = R("arrival", 1999, "12:50", confidence=CONFIRM_CONFIDENCE - 0.1)
    store.ingest(frame() + [weak], at(0))
    store.ingest(frame(), at(1))
    store.ingest(frame() + [weak], at(2))
    assert not services(store, "train_no=1999")


def test_confident_new_service_appears_at_once(store):
    store.ingest(frame() + [R("arrival", 1999, "12:50", confidence=0.9)], at(0))
    assert services(store, "train_no=1999")


# -- partial panel reads ----------------------------------------------------------

def test_partial_panel_keeps_last_state_and_ingests_the_other(store):
    store.ingest(frame(12, 12), at(0))
    for m in range(1, 5):  # arrivals suddenly shows 2 rows for several frames
        rows = frame(2, 12)
        rows = [r for r in rows if r.board == "departure"] + [
            R("departure", 1799, "12:59")] * (m == 4) + [r for r in rows if r.board == "arrival"]
        store.ingest(rows, at(m))
        assert store.last_rejected == {"arrival": "partial read (2 of 12 rows)"}
    assert not services(store, "board='arrival' AND status='gone'")
    assert len(services(store, "board='arrival'")) == 12
    assert services(store, "train_no=1799")  # departures still ingested
    ages = store.board_ages(at(4))
    assert ages["arrival"] == pytest.approx(240.0) and ages["departure"] == pytest.approx(0.0)
    assert store.last_ok_age(at(4)) == pytest.approx(0.0)


def test_panel_that_really_shrank_is_accepted_after_a_while(store):
    store.ingest(frame(12, 12), at(0))
    for m in range(1, PARTIAL_ACCEPT_AFTER):
        store.ingest(frame(2, 12), at(m))
    assert "arrival" in store.last_rejected
    assert not services(store, "status='gone'")
    for m in range(PARTIAL_ACCEPT_AFTER, PARTIAL_ACCEPT_AFTER + 2):  # GONE after 2 misses
        store.ingest(frame(2, 12), at(m))
    assert store.last_rejected == {}
    assert len(services(store, "board='arrival' AND status='listed'")) == 2


def test_both_panels_unreadable_is_a_failed_run(store):
    store.ingest(frame(12, 12), at(0))
    assert store.ingest(frame(1, 1), at(1)) == []
    assert store._conn.execute("SELECT ok FROM runs ORDER BY id DESC").fetchone()[0] == 0
    assert set(store.last_rejected) == {"arrival", "departure"}


def _augmented_two_rows() -> bytes:
    """board_1 with the arrivals panel blanked below its second row (blue)."""
    from app.ocr import preprocess, reader

    img = cv2.imread(str(FIX / "board_1.jpg"))
    (arr, ax), _ = preprocess.split_boards_offsets(img)
    y0 = reader._cell_grid_geo(arr)[2][1]["time"][1] - 2
    rows = preprocess.panel_rows(arr)
    bg = np.median(arr[rows].reshape(-1, 3), axis=0).astype(np.uint8)
    img[y0:, ax:ax + arr.shape[1]][rows[y0:]] = bg
    return cv2.imencode(".png", img)[1].tobytes()


@pytest.mark.skipif(not (os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")),
                    reason="tesseract not installed")
def test_augmented_frame_with_two_arrival_rows_is_rejected_for_arrivals(store):
    from app.ocr.reader import read_board

    full = read_board((FIX / "board_1.jpg").read_bytes())
    partial = read_board(_augmented_two_rows())
    assert sum(r.board == "arrival" for r in partial) == 2
    assert sum(r.board == "departure" for r in partial) >= 10
    store.ingest(full, at(0))
    n_arr = len(services(store, "board='arrival'"))
    for m in (1, 2, 3):
        store.ingest(partial, at(m))
    assert "partial read" in store.last_rejected["arrival"]
    assert "departure" not in store.last_rejected
    assert len(services(store, "board='arrival' AND status='listed'")) == n_arr


# -- rejected frames on disk ----------------------------------------------------------

def test_save_rejected_writes_image_and_reasons_and_keeps_last(tmp_path):
    d = tmp_path / "rej" / "sub"
    for k in range(rejected.REJECTED_KEEP + 5):
        p = rejected.save_rejected(str(d), b"img%d" % k, 1_000_000 + k, {"arrival": "partial"})
        assert p and os.path.exists(p)
    jpgs = sorted(x for x in os.listdir(d) if x.endswith(".jpg"))
    assert len(jpgs) == rejected.REJECTED_KEEP
    assert len([x for x in os.listdir(d) if x.endswith(".json")]) == rejected.REJECTED_KEEP
    meta = json.loads((d / (jpgs[-1][:-4] + ".json")).read_text(encoding="utf-8"))
    assert meta["reasons"] == {"arrival": "partial"}
    assert (d / jpgs[-1]).read_bytes() == b"img%d" % (rejected.REJECTED_KEEP + 4)


def test_save_rejected_disabled_or_failing_never_raises(tmp_path):
    assert rejected.save_rejected(None, b"x", 0, {}) is None
    f = tmp_path / "file"
    f.write_bytes(b"")
    assert rejected.save_rejected(str(f), b"x", 0, {"a": "b"}) is None  # not a directory


def test_poller_saves_frames_on_rows_rejected(monkeypatch, tmp_path):
    stop = asyncio.Event()
    now = [100.0]

    async def fake_fetch(client, url):
        return b"img-%d" % int(now[0] // 60)

    monkeypatch.setattr(poller, "fetch_board_image", fake_fetch)
    monkeypatch.setattr(poller, "read_board", lambda data: ["row"])

    async def sleep(d):
        now[0] += d
        if now[0] > 300:
            stop.set()

    calls = []

    async def on_rows(rows, ts):
        calls.append(ts)
        return {"arrival": "partial read (2 of 12 rows)"} if len(calls) == 2 else {}

    class S:
        source_url = "http://x"

    d = tmp_path / "rejected"
    asyncio.run(asyncio.wait_for(poller.run_poller(
        S(), on_rows, None, stop, clock=lambda: now[0], sleep=sleep,
        last_image_path=None, rejected_dir=str(d)), timeout=5))
    assert len(calls) >= 3
    assert len([x for x in os.listdir(d) if x.endswith(".jpg")]) == 1
