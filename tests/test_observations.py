# © 2026 Andy217Ace
"""record_capture: image saved unmodified, one observation per OCR line, catalog."""
import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import observations as obs
from app.models import Row
from app.ocr.reader import read_board_debug
from app.store import Store

FIX = Path(__file__).parent / "fixtures"
BUC = ZoneInfo("Europe/Bucharest")
TS = datetime(2026, 10, 20, 12, 0, tzinfo=BUC).timestamp()


@pytest.fixture(scope="module")
def board():
    data = (FIX / "board_1.jpg").read_bytes()
    rows, debug = read_board_debug(data)
    return data, rows, debug


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def _ingest(store, rows, ts=TS):
    return store.ingest(rows, datetime.fromtimestamp(ts, BUC), "")


def q(store, sql, *a):
    return store._conn.execute(sql, a).fetchall()


def test_record_saves_original_and_relative_path(store, board, tmp_path):
    data, rows, debug = board
    _ingest(store, rows)
    cid = obs.record_capture(store, data, rows, debug, TS, capture_dir=tmp_path,
                             duration_ms=1234)
    cap = q(store, "SELECT * FROM captures WHERE id=?", cid)[0]
    h = hashlib.sha1(data).hexdigest()
    assert cap["image_hash"] == h
    assert cap["path"] == f"2026/10/20/090000-{h[:8]}.jpg"  # UTC: 12:00 EEST = 09:00Z
    assert not Path(cap["path"]).is_absolute() and "\\" not in cap["path"]
    assert (tmp_path / cap["path"]).read_bytes() == data  # byte-for-byte
    assert cap["width"] > 200 and cap["height"] > 60
    assert cap["bytes"] == len(data) and cap["ok"] == 1 and cap["n_rows"] == len(rows)
    assert cap["duration_ms"] == 1234 and cap["error"] is None
    assert cap["processing_version"] == obs.PROCESSING_VERSION
    assert cap["captured_at"].endswith("+00:00")
    assert cap["expires_at"] > cap["captured_at"]


def test_observations_for_every_line_with_raw_text_and_link(store, board, tmp_path):
    data, rows, debug = board
    _ingest(store, rows)
    cid = obs.record_capture(store, data, rows, debug, TS, capture_dir=tmp_path)
    got = q(store, "SELECT * FROM observations WHERE capture_id=? ORDER BY id", cid)
    assert len(got) == len(debug) >= 24
    for o, d in zip(got, debug):
        assert o["raw_text"] == d["raw_text"]
        f = json.loads(o["fields_json"])
        assert set(f) == set(obs.FIELDS)
        assert {"raw", "norm", "conf", "bbox"} <= set(f["station"])
        assert o["validation_state"] in obs.STATES
        assert o["observed_at"].endswith("+00:00")
    linked = [o for o in got if o["validation_state"] in ("ok", "uncertain")]
    assert linked and all(o["service_id"] is not None for o in linked)
    for o in linked:
        s = q(store, "SELECT train_no, board FROM services WHERE id=?", o["service_id"])[0]
        assert (s["train_no"], s["board"]) == (o["train_no"], o["board"])
    t = q(store, "SELECT * FROM trains WHERE train_no=?", linked[0]["train_no"])[0]
    assert t["observations"] >= 1 and t["journeys"] >= 1


def test_same_image_twice_is_one_capture(store, board, tmp_path):
    data, rows, debug = board
    _ingest(store, rows)
    a = obs.record_capture(store, data, rows, debug, TS, capture_dir=tmp_path)
    b = obs.record_capture(store, data, rows, debug, TS + 60, capture_dir=tmp_path)
    assert a == b
    assert q(store, "SELECT COUNT(*) FROM captures")[0][0] == 1
    assert q(store, "SELECT COUNT(*) FROM observations")[0][0] == len(debug)
    cap = q(store, "SELECT captured_at, last_seen_at FROM captures")[0]
    assert cap["last_seen_at"] > cap["captured_at"]
    assert len(list(tmp_path.rglob("*.jpg"))) == 1


def _row(no=1621, **kw):
    base = dict(board="arrival", train_type="IR", train_no=no, station="BRASOV",
                operator="CFR Calatori", sched_time="12:10")
    base.update(kw)
    return Row(**base)


def test_incomplete_and_low_conf_lines_are_kept(store, tmp_path):
    good = _row()
    low = _row(1622, sched_time="12:20", confidence=0.2)
    unc = _row(1623, sched_time="12:30", uncertain=True)
    unread = _row(1624, sched_time="12:40", delay_read=False)
    debug = [
        {"board": "arrival", "row_index": i, "row": r, "conf": r.confidence,
         "raw_text": f"IR {r.train_no} raw", "fields": {}}
        for i, r in enumerate((good, low, unc, unread))
    ] + [{"board": "departure", "row_index": 0, "row": None, "conf": 0.1,
          "raw_text": "?? 17 BUCURESTI", "fields": {"no": {"raw": "17", "norm": 17}}}]
    cid = obs.record_capture(store, b"not-a-jpeg", [good, low, unc, unread], debug, TS,
                             capture_dir=tmp_path)
    states = [r[0] for r in q(store, "SELECT validation_state FROM observations"
                                     " WHERE capture_id=? ORDER BY id", cid)]
    assert states == ["ok", "rejected_low_conf", "uncertain", "uncertain", "incomplete"]
    inc = q(store, "SELECT * FROM observations WHERE validation_state='incomplete'")[0]
    assert inc["raw_text"] == "?? 17 BUCURESTI" and inc["service_id"] is None
    assert inc["train_no"] == 17
    # unread delay: stored as NULL, never as 0
    u = q(store, "SELECT delay_min, delay_read FROM observations WHERE train_no=1624")[0]
    assert (u["delay_min"], u["delay_read"]) == (None, 0)
    # catalog: only usable observations; the incomplete 17 and low-conf 1622 are not trains
    nos = {r[0] for r in q(store, "SELECT train_no FROM trains")}
    assert nos == {1621, 1623, 1624}
    cap = q(store, "SELECT width, height FROM captures")[0]
    assert (cap["width"], cap["height"]) == (None, None)  # undecodable image: no size


def test_no_link_when_store_did_not_match(store, tmp_path):
    rows = [_row()]  # a single row: the run is invalid, services untouched
    _ingest(store, rows)
    obs.record_capture(store, b"x", rows, None, TS, capture_dir=tmp_path)
    o = q(store, "SELECT service_id, validation_state FROM observations")[0]
    assert o["service_id"] is None and o["validation_state"] == "ok"


def test_failed_ocr_capture_has_error_and_no_observations(store, tmp_path):
    cid = obs.record_capture(store, b"img", None, None, TS, capture_dir=tmp_path,
                             error="OCR failed: boom")
    cap = q(store, "SELECT ok, n_rows, error FROM captures WHERE id=?", cid)[0]
    assert tuple(cap) == (0, 0, "OCR failed: boom")
    assert q(store, "SELECT COUNT(*) FROM observations")[0][0] == 0


def test_unwritable_capture_dir_keeps_metadata(store, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_bytes(b"")
    cid = obs.record_capture(store, b"img", [], None, TS, capture_dir=blocker)
    assert q(store, "SELECT path FROM captures WHERE id=?", cid)[0][0] is None


def test_capture_dir_none_records_metadata_only(store, tmp_path):
    cid = obs.record_capture(store, b"img", [], None, TS, capture_dir=None)
    assert q(store, "SELECT path FROM captures WHERE id=?", cid)[0][0] is None


def test_jittered_service_links(store, tmp_path):
    rows = [_row(1621, sched_time="12:10"), _row(1622, sched_time="12:20"),
            _row(1731, board="departure", sched_time="12:15"),
            _row(1732, board="departure", sched_time="12:30")]
    _ingest(store, rows, TS)
    moved = [replace(rows[0], sched_time="12:11")] + rows[1:]
    _ingest(store, moved, TS + 60)
    obs.record_capture(store, b"y", moved, None, TS + 60, capture_dir=None)
    o = q(store, "SELECT service_id FROM observations WHERE train_no=1621")[0]
    s = q(store, "SELECT sched_time FROM services WHERE id=?", o[0])[0]
    assert s[0] == "12:10"  # stored sched_time wins; linked despite the misread


def test_list_and_detail_trains(store, tmp_path):
    rows = [_row(1621), _row(1622, sched_time="12:20"),
            _row(1731, board="departure", sched_time="12:15", station="CONSTANTA",
                 operator="Transferoviar"),
            _row(1732, board="departure", sched_time="12:30")]
    _ingest(store, rows)
    obs.record_capture(store, b"z", rows, None, TS, capture_dir=None)
    all_ = obs.list_trains(store)
    assert {t["train_no"] for t in all_} == {1621, 1622, 1731, 1732}
    assert [t["train_no"] for t in obs.list_trains(store, "173")] in ([1731, 1732], [1732, 1731])
    assert [t["train_no"] for t in obs.list_trains(store, "constan")] == [1731]
    assert [t["train_no"] for t in obs.list_trains(store, "transfer")] == [1731]
    assert obs.list_trains(store, "%") == []
    assert len(obs.list_trains(store, limit=1)) == 1
    d = obs.train_detail(store, 1731)
    assert d["journeys"] == 1 and d["observations"] == 1
    assert len(d["journeys_list"]) == 1 and d["journeys_list"][0]["observations"] == 1
    assert d["journeys_list"][0]["first_seen"].endswith("+00:00")
    assert obs.train_detail(store, 9999) is None


# -- review fixes (INT2) ---------------------------------------------------------------

def test_failed_transaction_leaves_no_orphan_image(store, board, tmp_path, monkeypatch):
    data, rows, debug = board
    _ingest(store, rows)

    def boom(conn, nos):
        raise RuntimeError("db failure")
    monkeypatch.setattr(obs, "refresh_trains", boom)
    with pytest.raises(RuntimeError):
        obs.record_capture(store, data, rows, debug, TS, capture_dir=tmp_path)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]  # file removed, no .tmp
    assert q(store, "SELECT COUNT(*) FROM captures")[0][0] == 0


def test_low_disk_keeps_metadata_without_file(store, board, tmp_path, monkeypatch):
    data, rows, debug = board
    _ingest(store, rows)
    monkeypatch.setenv("CAPTURE_MIN_FREE_MB", str(10 ** 9))  # floor far above any disk
    cid = obs.record_capture(store, data, rows, debug, TS, capture_dir=tmp_path)
    assert q(store, "SELECT path FROM captures WHERE id=?", cid)[0][0] is None
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]
    assert q(store, "SELECT COUNT(*) FROM observations WHERE capture_id=?", cid)[0][0] > 0


def test_retention_zero_writes_no_image(store, board, tmp_path):
    data, rows, debug = board
    _ingest(store, rows)
    cid = obs.record_capture(store, data, rows, debug, TS, capture_dir=tmp_path,
                             retention_days=0)
    assert q(store, "SELECT path FROM captures WHERE id=?", cid)[0][0] is None
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_unread_confidence_is_null_not_zero(store, board, tmp_path):
    data, rows, debug = board
    _ingest(store, rows)
    dbg = [dict(e, conf=None) for e in debug]
    cid = obs.record_capture(store, data, rows, dbg, TS, capture_dir=None)
    vals = {r[0] for r in q(store, "SELECT row_conf FROM observations WHERE capture_id=?", cid)}
    assert vals == {None}


def test_catalog_follows_ingest_without_captures(store, board):
    _, rows, _ = board
    _ingest(store, rows)
    obs.refresh_catalog(store, rows)
    nos = {r.train_no for r in rows if r.confidence >= 0.5}
    got = {r[0] for r in q(store, "SELECT train_no FROM trains")}
    assert nos and nos <= got
    assert q(store, "SELECT SUM(observations) FROM trains")[0][0] == 0  # no captures


def test_observations_have_covering_index_for_catalog(store):
    idx = {r[1] for r in q(store, "PRAGMA index_list(observations)")}
    assert "ix_observations_train_state" in idx
