# © 2026 Andy217Ace
"""Cell boxes frame the whole glyphs (Beta 1.22+ band fix).

The admin overlay drew the type / train-number rectangles of the last group (rows 9-11)
a pixel or two too high: the line band is cut on the ink of the whole line, the camera
tilts the board, so the left-hand cells sit lower than the band and their glyph bottoms
fell outside the rectangle. Fixture: a real capture of 26.10.2026 (departures, group 4:
"R 9301", "RM 7905", "R 9101"). Reading accuracy is unchanged (the cells fed to
Tesseract are still cut by the band; the digit templates were calibrated on them).
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.ocr import preprocess, reader
from tests.ocr_truth_images import capture

FIX = Path(__file__).parent / "fixtures" / "band_group4.jpg"


def _glyph_rows(gray: np.ndarray, box: tuple[int, int, int, int]) -> tuple[int, int]:
    """[top, bottom) image rows of the bright glyphs of a cell, from the grayscale image
    (independent of the mask the boxes were derived from)."""
    x, y, w, h = box
    ya, yb = max(0, y - 6), min(gray.shape[0], y + h + 6)
    reg = gray[ya:yb, x:x + w]
    thr = (np.percentile(reg, 10) + np.percentile(reg, 98)) / 2
    on = (reg > thr).sum(axis=1) >= 2
    mid = y + h // 2 - ya
    a = mid
    while a > 0 and on[a - 1]:
        a -= 1
    c = mid
    while c < len(on) and on[c]:
        c += 1
    return ya + a, ya + c


@pytest.fixture(scope="module")
def panels():
    img = cv2.imread(str(capture(FIX)))
    assert img is not None
    return [(reader._Panel(half), cv2.cvtColor(half, cv2.COLOR_BGR2GRAY).astype(float))
            for half, _ in preprocess.split_boards_offsets(img)]


@pytest.mark.parametrize("board", [0, 1])
def test_boxes_cover_type_and_number_glyphs_in_every_group(panels, board):
    p, gray = panels[board]
    assert len(p) == 12
    for i in range(12):
        boxes = p.boxes(i)
        for name in ("type", "no"):
            x, y, w, h = boxes[name]
            top, bot = _glyph_rows(gray, boxes[name])
            assert y <= top, (board, i, name, "top", y, top)
            assert y + h >= bot, (board, i, name, "bottom", y + h, bot)


def test_last_group_departures_are_not_cut_at_the_bottom(panels):
    """The reported rows: 9301, 7905, 9101 (rows 9-11 of the departures)."""
    p, gray = panels[1]
    for i in (9, 10, 11):
        x, y, w, h = p.boxes(i)["no"]
        _, bot = _glyph_rows(gray, (x, y, w, h))
        assert y + h > bot, (i, y + h, bot)


def test_cells_for_reading_are_still_the_band_cuts(panels):
    """Only the drawn boxes grew: the cell images keep the calibrated band cut."""
    p, _ = panels[1]
    y0, y1 = p.bands[11]
    assert p.cells(11, grow=False)["no"].shape[0] == y1 - y0


def test_extend_span_follows_own_ink_only():
    ink = np.zeros(60, int)
    ink[20:32] = 5   # the band's glyphs
    ink[32:35] = 5   # ... continuing below the band (tilt)
    ink[40:50] = 5   # the next line: never reached
    assert preprocess.extend_span(ink, 20, 32, None, 40) == (20, 35)
    # growth stops at the half gap to the neighbour even when ink continues
    ink[35:50] = 5
    assert preprocess.extend_span(ink, 20, 32, None, 40)[1] <= 36
    # no ink at the edge: unchanged
    ink2 = np.zeros(60, int)
    ink2[20:30] = 5
    assert preprocess.extend_span(ink2, 20, 32) == (20, 32)
    # cap: at most 35 % of the band height
    ink3 = np.full(100, 5)
    a, b = preprocess.extend_span(ink3, 40, 60)
    assert (40 - a) <= 7 and (b - 60) <= 7
