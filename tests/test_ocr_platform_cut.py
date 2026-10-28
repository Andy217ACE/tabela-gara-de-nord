# © 2026 Andy217Ace
"""Truth set + recorded baseline for the "cut platform" and Departures r9/r11 work (Beta 1.31).

Task 2.1 only measures: it adds hand-labelled frames to ``tests/fixtures/ocr_truth/truth.json``
(every cell read by eye on the image, never from the database or from the reader) and records
what the reader gets on them in ``tests/fixtures/ocr_truth/baseline-1.31.json``. Tasks 2.2/2.3
fix the reader against this set and select their frames from the baseline file. The frames are
the local ones of Task 2.1 plus real production frames (``ocr_truth/srv/``, Task 2.1-S, chosen
because the reader got a platform or a Departures number wrong on them):

  platform_cut        frames where the reader currently gets a ``platform`` cell wrong or None
  platform_edge_risk  frames where the board shows a two-digit platform at the right edge
                      (the digit the cut would hit); a superset to watch for regressions
  departure_r9_r11    frames scored on ``no`` at Departures rows 9 and 11 (1-based = line
                      indexes 8 and 10)
  departure_r9_r11_fail     of those, frames where that ``no`` is currently not ok
  departure_idx_9_11_fail   frames where ``no`` at line indexes 9 and 11 (rows 10 and 12 in
                      1-based terms) is not ok: the real failures cluster here, so "r9/r11" in
                      the live reports may be 0-based line indexes
  departure_group4_fail     union of the two (the last group of Departures, lines 8..11)

Adding or relabelling truth frames requires re-recording the baseline (the test compares
``frames`` and the counters with truth.json).
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
SERVER_PREFIX = "ocr_truth/srv/"  # real production frames (Task 2.1-S), new in 1.31
R9_R11 = (8, 10)  # 1-based rows 9 and 11 -> line indexes
IDX_9_11 = (9, 11)  # line indexes 9 and 11
NEW_FRAMES = sorted(f for f in TRUTH["frames"]
                    if f.startswith(SERVER_PREFIX) or not f.startswith(ORIGINAL_PREFIXES))


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
            "no_departure_idx_9_11": _count(_cells(frame, lines, "no", ("departure",), IDX_9_11)),
        }
    edge = [f for f in NEW_FRAMES
            if any(isinstance(l.get("platform"), int) and l["platform"] >= 10
                   for b in TRUTH["frames"][f].values() for l in b)]
    def _bad(key):
        return [f for f in NEW_FRAMES if per_frame[f][key]["unread"] + per_frame[f][key]["wrong"]]

    group4 = sorted(set(_bad("no_departure_r9_r11")) | set(_bad("no_departure_idx_9_11")))
    return {
        "reader": "commit c81b602 (PROCESSING_VERSION ocr-tess-grid-5), measured before Task 2.3",
        "rows_r9_r11_line_indexes": list(R9_R11),
        "rows_idx_9_11_line_indexes": list(IDX_9_11),
        "frames": NEW_FRAMES,
        "platform_cut": [f for f in NEW_FRAMES
                         if per_frame[f]["platform"]["unread"] + per_frame[f]["platform"]["wrong"]],
        "platform_edge_risk": edge,
        "departure_r9_r11": [f for f in NEW_FRAMES
                             if _cells(f, {}, "no", ("departure",), R9_R11)],
        "departure_r9_r11_fail": _bad("no_departure_r9_r11"),
        "departure_idx_9_11_fail": _bad("no_departure_idx_9_11"),
        "departure_group4_fail": group4,
        "platform": _sum(per_frame, "platform"),
        "no_departure_r9_r11": _sum(per_frame, "no_departure_r9_r11"),
        "no_departure_idx_9_11": _sum(per_frame, "no_departure_idx_9_11"),
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
    for key in ("platform", "no_departure_r9_r11", "no_departure_idx_9_11"):
        assert set(base[key]) == {"ok", "unread", "wrong"}
        assert sum(base[key].values()) > 0
        assert base[key] == _sum(base["per_frame"], key)
    assert set(base["per_frame"]) == set(NEW_FRAMES)
    for key in ("platform_cut", "platform_edge_risk", "departure_r9_r11",
                "departure_r9_r11_fail", "departure_idx_9_11_fail", "departure_group4_fail"):
        assert set(base[key]) <= set(NEW_FRAMES)
    # a real selection: only frames scored on r9/r11 are listed, and the failing lists are
    # exactly the frames whose cells are not ok in the per-frame counters
    assert set(base["departure_r9_r11"]) == {
        f for f in NEW_FRAMES if _cells(f, {}, "no", ("departure",), R9_R11)}
    for key, cnt in (("departure_r9_r11_fail", "no_departure_r9_r11"),
                     ("departure_idx_9_11_fail", "no_departure_idx_9_11")):
        assert base[key] == [f for f in NEW_FRAMES if
                             base["per_frame"][f][cnt]["unread"] + base["per_frame"][f][cnt]["wrong"]]
    assert base["departure_group4_fail"] == sorted(
        set(base["departure_r9_r11_fail"]) | set(base["departure_idx_9_11_fail"]))
    # the truth set holds the real failures Task 2.3 needs (targets of Task 2.1-S)
    assert len(base["platform_cut"]) >= 15
    assert len(base["departure_group4_fail"]) >= 10
    # the cut list is exactly the frames with a platform that is not ok
    assert base["platform_cut"] == [f for f in NEW_FRAMES if
                                    base["per_frame"][f]["platform"]["unread"]
                                    + base["per_frame"][f]["platform"]["wrong"]]


# --- Task 2.2: platform read robustly (wrong 0; unread never above the baseline) -------

BASE = json.loads(BASELINE.read_text(encoding="utf-8"))
# unread threshold: measured after the fix (real server frames: 21 cells of platform_cut
# were 8 wrong + 13 unread at c81b602; round 2: 11; round 3 / R20, recovered digits must
# show their own holes: 12), never above the recorded baseline
PLATFORM_MAX_UNREAD = 12
assert PLATFORM_MAX_UNREAD <= BASE["platform"]["unread"]
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
    """One untrusted glyph `ch` (score, margin, full line height) whose near-tie
    candidates are `near`."""

    def __init__(self, ch, score, margin, near):
        import numpy as np
        self.g = (ch, score, margin, np.ones((32, 32), np.float32), False)
        self._near = near

    def glyphs(self, cell, allowed):
        return [self.g]

    def read(self, cell, allowed):
        return self.g[0], self.g[1], False

    def near(self, glyph, allowed):
        if isinstance(self._near, Exception):
            raise self._near
        return self._near


TIE_8_6 = ("8", 0.832, 0.021, "86")  # real 121707: 8 / 6 near tie, "3" far behind


def _box(*holes, size=(60, 30)):
    """One glyph, black on white: a filled box with hollow (y0, y1) rows cut out of its
    middle columns (each hole 8 px wide)."""
    import numpy as np
    cell = np.full(size, 255, np.uint8)
    cell[4:56, 6:24] = 0
    for y0, y1 in holes:
        cell[y0:y1, 11:19] = 255
    return cell


SOLID = _box()                          # no hole
LOWER = _box((36, 50))                  # one lower hole (a 6)
EIGHT = _box((10, 24), (34, 48))        # two holes of the same size (an 8)


@pytest.mark.parametrize("cell,stub,tess,want", [
    (SOLID, TIE_8_6, "3", ""),   # 3 is not among the near-tie candidates: unread
    (SOLID, TIE_8_6, "6", ""),   # Tesseract's 6 but no lower hole (R20): unread
    (SOLID, TIE_8_6, "", ""),    # Tesseract saw nothing; no 8 holes either
    (LOWER, ("5", 0.76, 0.003, "56"), "6", "6"),  # real 080506: 5/6 tie, the hole says 6
    (EIGHT, TIE_8_6, "8", "8"),  # the templates' own 8 (confirmed) showing both holes
    (SOLID, ("4", 0.55, 0.02, "41"), "1", ""),  # tie between weak matches (fused glyph)
    (SOLID, ("8", 0.832, 0.021, RuntimeError("boom")), "6", ""),  # check failed: fail safe
])
def test_tesseract_only_breaks_a_template_near_tie_on_platform(cell, stub, tess, want):
    from app.ocr.reader import _numeric
    assert _numeric("platform", cell, (tess, 80.0), _Stub(*stub))[0] == want


# R20 (Task 2.2 round 3): a digit the templates alone do not trust must show its own
# holes; 8 and 4 must never absorb a blurred or glare-closed 3, 5, 6, 9 or 0
@pytest.mark.parametrize("cell,stub,tess", [
    (_box((10, 24)), ("3", 0.75, 0.01, "38"), "8"),   # 3, one counter closed: only "U"
    (_box((36, 50)), ("3", 0.75, 0.01, "38"), "8"),   # 3, the other counter closed
    (SOLID, ("5", 0.76, 0.01, "56"), "6"),             # blurred 5 / 6 tie, no hole at all
    (_box((10, 13), (34, 50)), ("6", 0.75, 0.01, "68"), "8"),  # 6 with a closed hook
    (_box((10, 26), (44, 47)), ("9", 0.75, 0.01, "98"), "8"),  # 9 with a closed tail
    (_box((10, 14), (18, 50)), ("0", 0.75, 0.01, "08"), "8"),  # 0 cut by a glare streak
    (SOLID, ("4", 0.66, 0.039, "41"), "1"),            # real 103806: hole-free 4, Tess. 1
])
def test_an_untrusted_digit_needs_its_own_holes(cell, stub, tess):
    from app.ocr.reader import _numeric
    for t in (tess, ""):  # Tesseract's digit, and the templates + shape recovery
        assert _numeric("platform", cell, (t, 80.0), _Stub(*stub))[0] == ""


def test_glyphs_not_aligned_with_the_segmentation_are_unread():
    import numpy as np

    from app.ocr.reader import _numeric

    class _Two(_Stub):
        def glyphs(self, cell, allowed):
            return [self.g, self.g]  # two glyphs, the cell holds one

    assert _numeric("platform", EIGHT, ("8", 80.0), _Two(*TIE_8_6))[0] == ""
    assert np.asarray(EIGHT).shape == (60, 30)


def _glyph(r0, r1):
    import numpy as np
    g = np.zeros((32, 32), np.float32)
    g[r0:r1, 10:20] = 1.0
    return g


def _ones_and_sliver():
    """Two "1" stems and a sliver in the bottom corner (real ocr13 152405)."""
    import numpy as np
    cell = np.full((60, 70), 255, np.uint8)
    cell[5:56, 8:15] = 0
    cell[5:56, 28:35] = 0
    cell[51:56, 50:61] = 0
    return cell


@pytest.mark.parametrize("third,want", [
    (("2", 0.213, 0.003, (28, 32)), "11"),  # real 152405: a 4-row sliver, not a digit
    (("2", 0.45, 0.003, (4, 32)), ""),      # a weak but tall glyph is a digit: unread
    (("2", 0.65, 0.003, (28, 32)), ""),     # a short glyph matching well is kept: unread
])
def test_a_sliver_is_not_a_platform_digit(third, want):
    from app.ocr import digits
    from app.ocr.reader import _numeric
    cell = _ones_and_sliver()
    assert len(digits.segment_spans(cell)) == 3

    class _M:
        gl = [("1", 0.935, 0.204, _glyph(0, 29), False), ("1", 0.892, 0.218, _glyph(0, 28), False),
              (*third[:3], _glyph(*third[3]), False)]

        def glyphs(self, cell, allowed):
            return self.gl

        def read(self, cell, allowed):
            return "112", 0.213, False

        def near(self, glyph, allowed):
            return "1"

    assert _numeric("platform", cell, ("11", 80.0), _M())[0] == want


# --- round 2: glyph shape (holes) and lost ink, measured on real server frames --------

def _draw(*loops, size=(60, 30)):
    """Black-on-white glyph: a filled box with the given hollow (y0, y1) loops cut out."""
    import numpy as np
    cell = np.full(size, 255, np.uint8)
    cell[4:56, 6:24] = 0
    for y0, y1 in loops:
        cell[y0:y1, 11:19] = 255
    return cell


@pytest.mark.parametrize("loops,holes", [
    ((), ""), (((10, 24),), "U"), (((36, 50),), "L"), (((10, 24), (36, 50)), "UL"),
])
def test_holes_are_counted_above_and_below_the_middle(loops, holes):
    from app.ocr.reader import _holes
    assert _holes(_draw(*loops), 0, 30) == holes


@pytest.mark.parametrize("ch,holes,ok", [
    ("3", "L", False), ("5", "L", False),  # blurred 8 / 6 read 3 / 5: the hole says no
    ("6", "UL", False),                    # blurred 8 read 6: upper hole
    ("8", "UL", True), ("8", "L", True), ("6", "L", True), ("6", "", True),
    ("9", "L", False), ("9", "U", True), ("0", "UL", False), ("4", "U", True),
    ("1", "", True), ("1", "U", False), ("7", "", True),
])
def test_digit_must_fit_the_glyph_holes(ch, holes, ok):
    from app.ocr.reader import _fits
    assert _fits(ch, holes) is ok


# the 8 wrong cells of the real cut-platform frames at c81b602: now the label or None
CUT_WRONG = [("ocr_truth/srv/2026_10_22_041906-0901ecd4", 8, 8),
             ("ocr_truth/srv/2026_10_23_173806-4a34f182", 4, 8),
             ("ocr_truth/srv/2026_10_24_085709-b107ed8c", 5, 8),
             ("ocr_truth/srv/2026_10_27_093605-272f9ed9", 2, 8),
             ("ocr_truth/srv/2026_10_24_224505-e04669e6", 2, 6),
             ("ocr_truth/srv/2026_10_27_080506-faf616ce", 2, 6),
             ("ocr_truth/srv/2026_10_26_155305-19468666", 1, 6),
             ("ocr_truth/srv/2026_10_22_120408-e5206d05", 5, 4)]


@pytest.mark.parametrize("frame,line,board_shows", CUT_WRONG)
def test_blurred_platform_digit_is_never_misread(frame, line, board_shows):
    assert _lines(frame)[("departure", line)]["platform"] in (board_shows, None)
