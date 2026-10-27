# © 2026 Andy217Ace
"""Truth set + recorded baseline for the "cut platform" and Departures r9/r11 work (Beta 1.31).

Task 2.1 only measures: it adds hand-labelled frames to ``tests/fixtures/ocr_truth/truth.json``
(every cell read by eye on the image, never from the database or from the reader) and records
what the reader (Beta 1.30) gets on them in ``tests/fixtures/ocr_truth/baseline-1.31.json``.
Tasks 2.2/2.3 fix the reader against this set and select their frames from the baseline file:

  platform_cut        frames where the reader currently gets a ``platform`` cell wrong or None
  platform_edge_risk  frames where the board shows a two-digit platform at the right edge
                      (the digit the cut would hit); a superset to watch for regressions
  departure_r9_r11    frames scored on ``no`` at Departures rows 9 and 11 (1-based = line
                      indexes 8 and 10); every new frame

Re-record only on purpose:  OCR_RECORD_BASELINE=1 pytest tests/test_ocr_platform_cut.py
(OMP_THREAD_LIMIT=1; by default the test only verifies the file and never writes).
"""
from __future__ import annotations

import collections
import json
import os
from pathlib import Path

import pytest

from app.ocr import truth
from app.ocr.reader import read_board_debug

FIX = Path(__file__).parent / "fixtures"
TRUTH_PATH = FIX / "ocr_truth" / "truth.json"
BASELINE = FIX / "ocr_truth" / "baseline-1.31.json"
TRUTH = truth.load(TRUTH_PATH)

# the 16 captures of Beta 1.16 (tests/test_ocr14.py); every other frame is new in 1.31
ORIGINAL_PREFIXES = ("ocr13/", "ocr_truth/")
R9_R11 = (8, 10)  # 1-based rows 9 and 11 -> line indexes
NEW_FRAMES = sorted(f for f in TRUTH["frames"] if not f.startswith(ORIGINAL_PREFIXES))


def _count(cells: list[tuple]) -> dict:
    """cells: (board, line, label, read) -> ok/unread/wrong + the cells that are not ok."""
    c = collections.Counter()
    misses = []
    for board, line, label, read in cells:
        if read == label:
            c["ok"] += 1
            continue
        c["unread" if read is None else "wrong"] += 1
        misses.append([board, line, label, read])
    return {"ok": c["ok"], "unread": c["unread"], "wrong": c["wrong"], "misses": misses}


def _cells(frame: str, lines: dict, field: str, boards=("arrival", "departure"), rows=None):
    out = []
    for board in boards:
        for i, label in enumerate(TRUTH["frames"][frame][board]):
            if (rows is not None and i not in rows) or label.get(field, truth.SKIP) == truth.SKIP:
                continue
            out.append((board, i, label[field], lines.get((board, i), {}).get(field)))
    return out


def _sum(per_frame: dict, key: str) -> dict:
    return {k: sum(v[key][k] for v in per_frame.values()) for k in ("ok", "unread", "wrong")}


def measure() -> dict:
    """Run the reader on the new frames and build the baseline document."""
    per_frame = {}
    for frame in NEW_FRAMES:
        _, debug = read_board_debug((FIX / f"{frame}.jpg").read_bytes(), budget_s=60.0)
        lines = truth.lines_of(debug)
        per_frame[frame] = {
            "platform": _count(_cells(frame, lines, "platform")),
            "no_departure_r9_r11": _count(_cells(frame, lines, "no", ("departure",), R9_R11)),
        }
    edge = [f for f in NEW_FRAMES
            if any(isinstance(l.get("platform"), int) and l["platform"] >= 10
                   for b in TRUTH["frames"][f].values() for l in b)]
    return {
        "reader": "Beta 1.30 (PROCESSING_VERSION ocr-tess-grid-4), measured before Tasks 2.2/2.3",
        "rows_r9_r11_line_indexes": list(R9_R11),
        "frames": NEW_FRAMES,
        "platform_cut": [f for f in NEW_FRAMES
                         if per_frame[f]["platform"]["unread"] + per_frame[f]["platform"]["wrong"]],
        "platform_edge_risk": edge,
        "departure_r9_r11": [f for f in NEW_FRAMES
                             if _cells(f, {}, "no", ("departure",), R9_R11)],
        "platform": _sum(per_frame, "platform"),
        "no_departure_r9_r11": _sum(per_frame, "no_departure_r9_r11"),
        "per_frame": per_frame,
    }


def record_baseline() -> None:
    BASELINE.write_text(json.dumps(measure(), ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")


def test_new_frames_are_fully_labelled():
    assert len(NEW_FRAMES) >= 10
    for frame in NEW_FRAMES:
        assert (FIX / f"{frame}.jpg").exists(), frame
        assert set(TRUTH["frames"][frame]) == {"arrival", "departure"}
        for lines in TRUTH["frames"][frame].values():
            assert len(lines) == 12
            assert all(set(truth.FIELDS) <= set(line) for line in lines)


def test_baseline_recorded():
    if os.environ.get("OCR_RECORD_BASELINE") == "1":
        record_baseline()
    assert BASELINE.exists(), "run once with OCR_RECORD_BASELINE=1"
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert base["frames"] == NEW_FRAMES
    for key in ("platform", "no_departure_r9_r11"):
        assert set(base[key]) == {"ok", "unread", "wrong"}
        assert sum(base[key].values()) > 0
        assert base[key] == _sum(base["per_frame"], key)
    assert set(base["per_frame"]) == set(NEW_FRAMES)
    for key in ("platform_cut", "platform_edge_risk", "departure_r9_r11"):
        assert set(base[key]) <= set(NEW_FRAMES)
    assert base["departure_r9_r11"] == NEW_FRAMES
    # the cut list is exactly the frames with a platform that is not ok
    assert base["platform_cut"] == [f for f in NEW_FRAMES if
                                    base["per_frame"][f]["platform"]["unread"]
                                    + base["per_frame"][f]["platform"]["wrong"]]


# --- Task 2.2: platform read robustly (wrong 0; unread never above the baseline) -------

BASE = json.loads(BASELINE.read_text(encoding="utf-8"))
# unread threshold fixed from the measured baseline, never looser (baseline unread is 0:
# no local frame shows a real cut-platform failure, so the threshold is 0)
PLATFORM_MAX_UNREAD = BASE["platform"]["unread"]
WRONG_8_AS_3 = "ocr_truth/2026_10_22_121707-b8eafa67"  # departures r1: board 8, read 3
_reads: dict[str, dict] = {}


def _lines(frame: str, image: bytes | None = None, key: str | None = None) -> dict:
    key = key or frame
    if key not in _reads:
        data = image if image is not None else (FIX / f"{frame}.jpg").read_bytes()
        _reads[key] = truth.lines_of(read_board_debug(data, budget_s=60.0)[1])
    return _reads[key]


def _platform_counts(frames, lines_of) -> dict:
    cells = [c for f in frames for c in _cells(f, lines_of(f), "platform")]
    return _count(cells)


def test_platform_cut_frames():
    c = _platform_counts(NEW_FRAMES, _lines)
    assert c["wrong"] == 0, c["misses"]
    assert c["unread"] <= PLATFORM_MAX_UNREAD, c["misses"]


def test_platform_blank_stays_none():
    """A blank platform cell (no platform yet) is read None, never an invented digit."""
    blanks = 0
    for frame in NEW_FRAMES + [WRONG_8_AS_3]:
        for board, line, label, read in _cells(frame, _lines(frame), "platform"):
            if label is None:
                blanks += 1
                assert read is None, (frame, board, line, read)
    assert blanks >= 100


def test_untrusted_platform_digit_is_not_replaced_by_a_rejected_tesseract_digit():
    """Real frame: a clear 8 whose templates are a near tie (8 0.832 / 6 0.811); Tesseract
    reads 3, which the templates rank 4th (0.746). Never publish 3: 8 or None."""
    got = _lines(WRONG_8_AS_3)[("departure", 1)]["platform"]
    assert got in (8, None), got


class _Stub:
    """One untrusted glyph `ch` (score, margin) whose near-tie candidates are `near`."""

    def __init__(self, ch, score, margin, near):
        self.g, self._near = (ch, score, margin, None, False), near

    def glyphs(self, cell, allowed):
        return [self.g]

    def read(self, cell, allowed):
        return self.g[0], self.g[1], False

    def near(self, glyph, allowed):
        if isinstance(self._near, Exception):
            raise self._near
        return self._near


TIE_8_6 = ("8", 0.832, 0.021, "86")  # real 121707: 8 / 6 near tie, "3" far behind


@pytest.mark.parametrize("stub,tess,want", [
    (TIE_8_6, "3", ""),    # 3 is not among the near-tie candidates: unread
    (TIE_8_6, "6", "6"),   # 6 is (0.811 vs 0.832): Tesseract breaks the tie
    (TIE_8_6, "", ""),     # Tesseract saw nothing
    (("4", 0.55, 0.02, "41"), "1", ""),  # tie between weak matches (fused glyph): unread
    (("8", 0.832, 0.021, RuntimeError("boom")), "6", ""),  # check failed: fail safe
])
def test_tesseract_only_breaks_a_template_near_tie_on_platform(stub, tess, want):
    import numpy as np

    from app.ocr.reader import _numeric
    cell = np.zeros((10, 10), np.uint8)
    assert _numeric("platform", cell, (tess, 80.0), _Stub(*stub))[0] == want


def _glyph(r0, r1):
    import numpy as np
    g = np.zeros((32, 32), np.float32)
    g[r0:r1, 10:20] = 1.0
    return g


@pytest.mark.parametrize("third,want", [
    (("2", 0.213, 0.003, (28, 32)), "11"),  # real 152405: a 4-row sliver, not a digit
    (("2", 0.45, 0.003, (4, 32)), ""),      # a weak but tall glyph is a digit: unread
    (("2", 0.65, 0.003, (28, 32)), ""),     # a short glyph matching well is kept: unread
])
def test_a_sliver_is_not_a_platform_digit(third, want):
    import numpy as np

    from app.ocr.reader import _numeric

    class _M:
        gl = [("1", 0.935, 0.204, _glyph(0, 29), False), ("1", 0.892, 0.218, _glyph(0, 28), False),
              (*third[:3], _glyph(*third[3]), False)]

        def glyphs(self, cell, allowed):
            return self.gl

        def read(self, cell, allowed):
            return "112", 0.213, False

        def near(self, glyph, allowed):
            return "1"

    assert _numeric("platform", np.zeros((10, 10), np.uint8), ("11", 80.0), _M())[0] == want
