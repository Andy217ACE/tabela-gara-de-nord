# © 2026 Andy217Ace
"""read_board_debug: same rows as read_board plus per-cell raw text, conf and bbox."""
from pathlib import Path

import cv2
import pytest

from app.ocr.reader import COLUMNS, read_board, read_board_debug
from tests.ocr_truth_images import capture

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def result():
    return read_board_debug(capture(FIX / "board_1.jpg").read_bytes())


def test_rows_identical_to_read_board(result):
    rows, _ = result
    assert rows == read_board(capture(FIX / "board_1.jpg").read_bytes())


def test_debug_covers_every_row(result):
    rows, debug = result
    linked = [d["row"] for d in debug if d["row"] is not None]
    assert linked == rows  # same order, same objects
    assert len(debug) >= len(rows)


def test_debug_fields_have_raw_conf_bbox_in_image(result):
    _, debug = result
    img = cv2.imread(str(capture(FIX / "board_1.jpg")))
    h, w = img.shape[:2]
    for d in debug:
        assert d["board"] in ("arrival", "departure")
        assert isinstance(d["row_index"], int)
        assert set(d["fields"]) == set(COLUMNS)
        assert isinstance(d["raw_text"], str)
        for f in d["fields"].values():
            assert isinstance(f["raw"], str)
            assert f["conf"] is None or 0 <= f["conf"] <= 100
            x, y, bw, bh = f["bbox"]
            assert 0 <= x and 0 <= y and bw > 0 and bh > 0
            assert x + bw <= w + 1 and y + bh <= h + 1
        # arrivals sit in the left half, departures in the right
        x = d["fields"]["no"]["bbox"][0]
        assert (x < w / 2) == (d["board"] == "arrival")


def test_debug_normalised_values_match_row(result):
    _, debug = result
    for d in debug:
        r = d["row"]
        if r is None:
            continue
        f = d["fields"]
        assert f["no"]["norm"] == r.train_no
        assert f["time"]["norm"] == r.sched_time
        assert f["station"]["norm"] == r.station
        assert f["operator"]["norm"] == r.operator
        assert f["platform"]["norm"] == r.platform
        assert f["type"]["norm"] == r.train_type
        assert r.train_no and str(r.train_no) in d["raw_text"]
