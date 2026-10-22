# © 2026 Andy217Ace
"""12 lines per panel: the 4x3 structure of the CFR board and the re-read of lines the
first OCR pass could not read (Beta 1.12).

Fixtures (tests/fixtures/ocr12/) are real captures of 21-22.10.2026 on which the
first pass lost a line (type or time unreadable: thin "1" next to a glare seam, a
small "*", "13:38" read "43:38"...), plus a complete frame and a corrupted frame
(truncated JPEG, shifted halves). The expected values were checked by eye on the
images. Synthetic variants cover an empty line (a board with fewer than 12 trains)
and a faded line.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.ocr import preprocess, reader, stats
from app.ocr.reader import read_board_debug

FIX = Path(__file__).parent / "fixtures" / "ocr12"


def _read(name: str, **kw):
    return read_board_debug((FIX / f"{name}.jpg").read_bytes(), **kw)


def _per_board(rows):
    return {b: sum(r.board == b for r in rows) for b in reader.BOARDS}


def _line(debug, board, idx):
    return next(d for d in debug if d["board"] == board and d["row_index"] == idx)


# (fixture, board, line, type, number, time) — the line the first pass lost
DEGRADED = [
    ("2026_10_22_001807-61bd84a4", "departure", 4, "IR", 16565, "04:41"),   # "4:4"
    ("2026_10_21_090907-b612b282", "arrival", 0, "RE", 10061, "11:03"),     # "*RE" lost
    ("2026_10_21_090907-b612b282", "arrival", 1, "IC", 552, "11:47"),
    ("2026_10_21_095407-217d4d46", "arrival", 11, "IRN", 347, "13:38"),     # "43:38"
    ("2026_10_21_090409-d9214f34", "arrival", 3, "IC", 552, "11:47"),       # "*C"
    ("2026_10_21_092905-dd4de195", "departure", 1, "RM", 7923, "12:30"),    # "*RI"
    ("2026_10_21_190106-efc14957", "departure", 10, "RE", 10101, "01:10"),  # "1:1:0"
]


def test_complete_frame_reads_12_per_panel_without_retries():
    rows, debug = _read("2026_10_21_213504-8f4c45f0")
    assert _per_board(rows) == {"arrival": 12, "departure": 12}
    assert all(d["state"] == "ok" and "retry" not in d for d in debug)
    assert all(r.train_no for r in rows)


@pytest.mark.parametrize("name,board,idx,ttype,no,sched", DEGRADED)
def test_degraded_line_is_recovered_by_a_reread(name, board, idx, ttype, no, sched):
    rows0, debug0 = _read(name, budget_s=0)  # first pass only
    assert _line(debug0, board, idx)["row"] is None
    assert _line(debug0, board, idx)["state"] == "unread"
    rows, debug = _read(name)
    line = _line(debug, board, idx)
    assert line["retry"]["variant"] in preprocess.VARIANTS
    r = line["row"]
    assert (r.train_type, r.train_no, r.sched_time) == (ttype, no, sched)
    assert _per_board(rows) == {"arrival": 12, "departure": 12}
    # a re-read never touches the lines the first pass read
    for d0, d in zip(debug0, debug):
        if d0["row"] is not None and d0["row"].train_no:
            assert d["row"] == d0["row"] and "retry" not in d


def test_accuracy_before_after_on_real_fixtures():
    names = sorted({n for n, *_ in DEGRADED}) + ["2026_10_21_213504-8f4c45f0"]
    before = after = 0
    for n in names:
        before += _per_board(_read(n, budget_s=0)[0]) == {"arrival": 12, "departure": 12}
        after += _per_board(_read(n)[0]) == {"arrival": 12, "departure": 12}
    assert (before, after) == (1, len(names))


def test_corrupted_frame_is_not_reread_into_invented_rows():
    """Truncated JPEG with shifted halves: most lines unreadable. Re-reading garbage
    only invents trains, so such a panel is left as read (rows rejected downstream
    by the partial-read guard)."""
    rows, debug = _read("2026_10_21_121106-8d157d03")
    first, _ = _read("2026_10_21_121106-8d157d03", budget_s=0)
    assert len(rows) == len(first)
    assert not any("retry" in d for d in debug)
    assert sum(d["state"] == "unread" for d in debug) > 2 * reader.MAX_RETRY_LINES


# -- synthetic: fewer than 12 trains on the board, faded line -----------------------

def _panel_geometry(img, board):
    half, x0 = preprocess.split_boards_offsets(img)[reader.BOARDS.index(board)]
    p = reader._Panel(half)
    return p, x0


def _blank_line(img, board, idx):
    """Paint one text line with its blue background: the board shows no train there."""
    out = img.copy()
    p, x0 = _panel_geometry(img, board)
    s = preprocess.SCALE
    y0, y1 = p.bands[idx][0] // s - 1, -(-p.bands[idx][1] // s) + 1
    region = out[y0:y1, x0:x0 + p.img.shape[1]]
    bright = np.minimum(region[:, :, 1], region[:, :, 2])
    bg = np.median(region[bright < p.level * 0.6], axis=0)
    region[:] = bg.astype(np.uint8)
    return out


def _fade_line(img, board, idx, k=0.55):
    """Lower the text contrast of one line (dim/yellowish line)."""
    out = img.copy().astype(np.float32)
    p, x0 = _panel_geometry(img, board)
    s = preprocess.SCALE
    y0, y1 = p.bands[idx][0] // s - 1, -(-p.bands[idx][1] // s) + 1
    region = out[y0:y1, x0:x0 + p.img.shape[1]]
    bg = np.median(region.reshape(-1, 3), axis=0)
    out[y0:y1, x0:x0 + p.img.shape[1]] = bg + (region - bg) * k
    return np.clip(out, 0, 255).astype(np.uint8)


def _jpg(img) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


def test_empty_line_keeps_its_slot_and_is_not_invented():
    img = cv2.imread(str(FIX / "2026_10_21_213504-8f4c45f0.jpg"))
    rows, debug = read_board_debug(_jpg(_blank_line(img, "arrival", 4)))
    arr = [d for d in debug if d["board"] == "arrival"]
    assert len(arr) == 12                                  # 4x3 grid: the slot stays
    assert _line(debug, "arrival", 4)["state"] == "empty"
    assert _line(debug, "arrival", 4)["row"] is None
    assert "retry" not in _line(debug, "arrival", 4)       # nothing to re-read
    assert _per_board(rows) == {"arrival": 11, "departure": 12}
    last = stats.snapshot()["last"]["boards"]["arrival"]
    assert (last["lines"], last["rows"], last["empty"]) == (12, 11, 1)


def test_two_empty_lines_in_a_group_still_give_12_slots():
    img = cv2.imread(str(FIX / "2026_10_21_213504-8f4c45f0.jpg"))
    img = _blank_line(_blank_line(img, "departure", 10), "departure", 11)
    rows, debug = read_board_debug(_jpg(img))
    dep = [d for d in debug if d["board"] == "departure"]
    assert len(dep) == 12
    assert [d["state"] for d in dep[9:]] == ["ok", "empty", "empty"]
    assert _per_board(rows)["departure"] == 10


def test_faded_line_is_kept_or_marked_unread_never_dropped():
    img = cv2.imread(str(FIX / "2026_10_21_213504-8f4c45f0.jpg"))
    rows, debug = read_board_debug(_jpg(_fade_line(img, "departure", 7)))
    dep = [d for d in debug if d["board"] == "departure"]
    assert len(dep) == 12
    assert _line(debug, "departure", 7)["state"] in ("ok", "unread")


# -- grid ----------------------------------------------------------------------------

def _layout(lines_per_group, group_h=54, gap=10, line_h=13, width=300):
    """A synthetic layout mask (x3) with 4 blue groups and the given text lines."""
    s = preprocess.SCALE
    h = 20 + 4 * (group_h + gap)
    rows = np.zeros(h, bool)
    mask = np.full((h * s, width), 255, np.uint8)
    y = 20
    for lines in lines_per_group:
        rows[y:y + group_h] = True
        for k in lines:
            ty = y + 3 + k * (group_h // 3)
            mask[ty * s:(ty + line_h - 3) * s, 10:width - 10] = 0
        y += group_h + gap
    return mask, rows


def test_structured_bands_repairs_a_group_with_a_missing_line():
    mask, rows = _layout([(0, 1, 2), (0, 2), (0, 1, 2), (0, 1, 2)])
    bands, repaired = preprocess.structured_bands(mask, rows)
    assert len(bands) == 12 and repaired == 1
    assert len(preprocess.row_bands(mask)) == 11
    assert not preprocess.band_has_ink(mask, bands[4])      # the empty line
    assert all(preprocess.band_has_ink(mask, b) for i, b in enumerate(bands) if i != 4)
    assert all(b[0] < c[0] for b, c in zip(bands, bands[1:]))  # top to bottom


def test_structured_bands_keeps_row_bands_when_each_group_has_3():
    mask, rows = _layout([(0, 1, 2)] * 4)
    bands, repaired = preprocess.structured_bands(mask, rows)
    assert repaired == 0 and bands == preprocess.row_bands(mask)


def test_structured_bands_unknown_layout_falls_back():
    mask, rows = _layout([(0, 1, 2)] * 4)
    rows[:] = False
    rows[20:200] = True  # one big group: not the 4x3 board
    bands, repaired = preprocess.structured_bands(mask, rows)
    assert repaired == 0 and bands == preprocess.row_bands(mask)


# -- budget, stats ---------------------------------------------------------------------

def test_budget_zero_means_no_retry_and_is_reported():
    rows, debug = _read("2026_10_22_001807-61bd84a4", budget_s=0)
    assert _per_board(rows) == {"arrival": 12, "departure": 11}
    line = _line(debug, "departure", 4)
    assert line["retry"] == {"attempts": 0, "variant": None}
    snap = stats.snapshot()
    assert snap["last"]["retried"] == 1 and snap["last"]["recovered"] == 0
    assert snap["window"]["frames"] == 1 and snap["window"]["full_frames"] == 0


def test_frame_budget_env(monkeypatch):
    monkeypatch.setenv("OCR_FRAME_BUDGET_S", "3.5")
    assert reader.frame_budget() == 3.5
    monkeypatch.setenv("OCR_FRAME_BUDGET_S", "x")
    assert reader.frame_budget() == reader.FRAME_BUDGET_S


def test_retry_stays_within_the_frame_budget():
    rows, _ = _read("2026_10_21_090907-b612b282")
    last = stats.snapshot()["last"]
    assert last["recovered"] == 2
    assert last["duration_ms"] <= reader.FRAME_BUDGET_S * 1000
    stats.reset()
    snap = stats.snapshot()
    assert snap["last"] is None and snap["window"]["frames"] == 0


# -- observations / Capturi OCR ----------------------------------------------------------

def test_line_version_roundtrip():
    from app.observations import PROCESSING_VERSION as V, line_version, parse_line_version
    assert line_version(V, {"state": "ok"}) == V
    assert parse_line_version(V) == {"state": "ok", "retry": None}
    v = line_version(V, {"state": "ok", "retry": {"attempts": 2, "variant": "lvl-"}})
    assert v == V + "+retry:lvl-:2"
    assert parse_line_version(v) == {"state": "ok",
                                     "retry": {"variant": "lvl-", "attempts": 2}}
    v = line_version(V, {"state": "unread", "retry": {"attempts": 6, "variant": None}})
    assert parse_line_version(v) == {"state": "unread",
                                     "retry": {"variant": None, "attempts": 6}}
    assert parse_line_version(line_version(V, {"state": "empty"}))["state"] == "empty"
    assert parse_line_version("ocr-tess-digits-1") == {"state": "ok", "retry": None}
    assert parse_line_version(None) == {"state": "ok", "retry": None}


def test_capture_admin_shows_rows_per_panel_and_rereads(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app import captures, observations
    from app.store import Store
    img = cv2.imread(str(FIX / "2026_10_22_001807-61bd84a4.jpg"))
    data = _jpg(_blank_line(img, "arrival", 2))
    rows, debug = read_board_debug(data)
    s = Store(":memory:")
    s.migrate()
    try:
        ts = datetime(2026, 10, 22, 3, 18, tzinfo=ZoneInfo("Europe/Bucharest")).timestamp()
        s.ingest(rows, datetime.fromtimestamp(ts, ZoneInfo("Europe/Bucharest")), "")
        cid = observations.record_capture(s, data, rows, debug, ts, capture_dir=None)
        listed = captures.list_captures(s)[0]
        assert listed["boards"]["arrivals"] == {"lines": 12, "rows": 11, "empty": 1,
                                                "unread": 0, "retried": 0, "recovered": 0}
        assert listed["boards"]["departures"] == {"lines": 12, "rows": 12, "empty": 0,
                                                  "unread": 0, "retried": 1, "recovered": 1}
        det = captures.capture_detail(s, cid)
        assert det["boards"] == listed["boards"]
        dep4 = next(o for o in det["observations"]
                    if o["board"] == "departure" and o["row_index"] == 4)
        assert dep4["line"]["retry"]["variant"] in preprocess.VARIANTS
        assert dep4["sched_time"] == "04:41" and dep4["train_no"] == 16565
        arr2 = next(o for o in det["observations"]
                    if o["board"] == "arrival" and o["row_index"] == 2)
        assert arr2["line"]["state"] == "empty" and arr2["validation_state"] == "incomplete"
        assert arr2["train_no"] is None  # an empty line is not a train (and not 0)
    finally:
        s.close()


def test_health_reports_ocr_rows_per_panel():
    from fastapi.testclient import TestClient

    from app.api import create_app
    from tests.test_api import settings
    _read("2026_10_22_001807-61bd84a4")
    with TestClient(create_app(settings(), start_poller=False)) as c:
        ocr = c.get("/api/health").json()["ocr"]
    assert ocr["expected_rows"] == 12
    assert ocr["last"]["boards"]["departure"]["rows"] == 12
    assert ocr["last"]["recovered"] == 1 and ocr["window"]["full_frames"] == 1
