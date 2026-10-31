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
# show their own holes: 12; round 4 / R22: 18), never above the recorded baseline except
# for the cells Ruling R22 turns into None on purpose (precaution, cost accepted by the
# ruling): srv 010204 dep 8, 041906 dep 8, 170107 dep 10 (8 decided against Tesseract's
# "3"), 080506 dep 2 (6 decided against Tesseract's and the templates' "5"), 103106 dep 1
# (8 with "0" near), 105404 dep 7 (a "1" at 0.48 < MIN_SCORE)
PLATFORM_MAX_UNREAD = 18
R22_COST = 6
assert PLATFORM_MAX_UNREAD <= BASE["platform"]["unread"] + R22_COST
WRONG_8_AS_3 = "ocr_truth/2026_10_22_121707-b8eafa67"  # departures r1: board 8, read 3
# round 4 (R21): blind hold-out frame, arrival line 1: a BLANK platform cell under glare
# read "4" (a 4x3 px glare dot stretched into a full glyph); now a regression frame
GLARE_DOT_BLANK = "ocr_truth/holdout/2026_10_24_160005-57702940"
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
    for frame in NEW_FRAMES + [WRONG_8_AS_3, GLARE_DOT_BLANK]:
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
    ("8", "U", False), ("8", "", False),   # R22: every labelled 8 has its lower hole
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


# --- round 4 (R21, R22): glare dot on a blank cell; 8 vs 0; MIN_SCORE; Tesseract agreement

def test_glare_dot_on_a_blank_platform_cell_stays_none():
    """Real hold-out frame 24_160005, arrival line 1: the board shows no platform; a glare
    dot at the cell's edge was read "4" (trusted 0.70). Now None."""
    assert _lines(GLARE_DOT_BLANK)[("arrival", 1)]["platform"] is None


class _Trusted(_Stub):
    def read(self, cell, allowed):
        return self.g[0], self.g[1], True


def test_a_speck_stretched_into_a_glyph_is_no_digit():
    import numpy as np

    from app.ocr.reader import _numeric
    cell = np.full((39, 80), 255, np.uint8)
    cell[23:27, 77:80] = 0  # the real dot: 4 rows x 3 px at the right edge
    stub = _Trusted("4", 0.70, 0.052, "4")  # what the templates made of it
    for tess in ("", "4"):
        assert _numeric("platform", cell, (tess, 80.0), stub)[0] == ""


ZERO_SPLIT = _box((10, 28), (32, 50))  # a 0 cut in the middle by a glare streak: 2 equal holes


@pytest.mark.parametrize("stub,tess", [
    (("8", 0.80, 0.02, "80"), "8"),  # the templates' own 8, confirmed by Tesseract
    (("8", 0.80, 0.02, "80"), ""),   # the same, recovered from templates + holes
    (("0", 0.80, 0.02, "08"), "8"),  # the templates' 0, Tesseract 8 (the 8 holes agree)
])
def test_an_untrusted_8_with_a_near_0_is_unread(stub, tess):
    from app.ocr.reader import _numeric
    assert _numeric("platform", ZERO_SPLIT, (tess, 80.0), _Stub(*stub))[0] == ""


def test_a_trusted_8_without_its_lower_hole_is_unread():
    from app.ocr.reader import _numeric
    upper_only = _box((10, 24))  # a blurred 9 / 3 with one closed upper counter
    stub = _Trusted("8", 0.85, 0.2, "8")
    assert _numeric("platform", upper_only, ("8", 80.0), stub)[0] == ""
    assert _numeric("platform", EIGHT, ("8", 80.0), stub)[0] == "8"  # both holes: kept


def test_an_untrusted_own_digit_needs_min_score():
    from app.ocr.reader import _numeric
    assert _numeric("platform", SOLID, ("1", 80.0), _Stub("1", 0.40, 0.2, "1"))[0] == ""
    assert _numeric("platform", SOLID, ("1", 80.0), _Stub("1", 0.62, 0.02, "17"))[0] == "1"
    assert _numeric("platform", SOLID, ("1", 80.0), _Stub("1", 0.62, 0.05, "1"))[0] == "1"


@pytest.mark.parametrize("cell,stub,tess,want", [
    (LOWER, ("5", 0.76, 0.003, "56"), "5", ""),   # 5 with a closed bowl / real 080506
    (LOWER, ("5", 0.76, 0.003, "56"), "", ""),    # Tesseract saw nothing
    (LOWER, ("5", 0.76, 0.003, "56"), "6", "6"),  # Tesseract agrees with the holes
    (EIGHT, ("6", 0.78, 0.01, "683"), "3", ""),   # real 010204 / 041906 / 170107 kind
    (EIGHT, ("6", 0.78, 0.01, "683"), "8", "8"),
    (EIGHT, ("3", 0.75, 0.01, "38"), "", ""),     # a 3 with both counters closed
])
def test_recovery_to_another_digit_needs_tesseract(cell, stub, tess, want):
    from app.ocr.reader import _numeric
    assert _numeric("platform", cell, (tess, 80.0), _Stub(*stub))[0] == want


# --- Task 2.3: Departures train number, lines 8-11 (rows "9/11": 0-based 9 and 11) ----
# Diagnosis (task-2.3-report.md): no geometry drift (the "no" cell sits at its nominal
# x0/x1 on every line); every wrong number came through untrusted templates: (A) the
# LED-module joint cuts the last digit "7" into a tall left piece and a short right piece
# (bar end), giving 5 glyphs (7907 -> 7307 / 79117 / 94107 / 73917), (B) a 9/0 or 9/8 near
# tie where Tesseract's unverified text was published (7909 -> 7309, 1659 -> 1653).

GROUP4 = (8, 9, 10, 11)
# measured after the fix on all 59 truth frames (236 cells): 236 ok / 0 unread / 0 wrong
# (c81b602: 224 / 0 / 12). A first-pass number left unread (doubtful glyph, Tesseract not
# settling a near tie) is re-read with the other binarisations, under the same rules
NO_GROUP4_MAX_UNREAD = 0


def test_departure_rows_9_11_number_never_wrong():
    cells = [c for f in sorted(TRUTH["frames"])
             for c in _cells(f, _lines(f), "no", ("departure",), GROUP4)]
    c = _count(cells)
    assert c["ok"] + c["unread"] + c["wrong"] >= 200
    assert c["wrong"] == 0, c["misses"]
    assert c["unread"] <= NO_GROUP4_MAX_UNREAD, c["misses"]


# the 12 real failures of departure_group4_fail at c81b602: now the label or None
GROUP4_WRONG = [("ocr_truth/srv/2026_10_21_212506-507579fb", 9, 7907),
                ("ocr_truth/srv/2026_10_21_212606-1a274ed1", 8, 7039),
                ("ocr_truth/srv/2026_10_22_051311-acf42e75", 9, 7917),
                ("ocr_truth/srv/2026_10_22_220006-a4ceb247", 11, 7909),
                ("ocr_truth/srv/2026_10_23_211505-11053345", 11, 7909),
                ("ocr_truth/srv/2026_10_24_100805-5b763752", 11, 9107),
                ("ocr_truth/srv/2026_10_24_173804-92e0c0df", 9, 1659),
                ("ocr_truth/srv/2026_10_25_061407-7494243c", 10, 7917),
                ("ocr_truth/srv/2026_10_25_232048-02d1ca2f", 11, 7909),
                ("ocr_truth/srv/2026_10_26_205906-aa606133", 11, 9101),
                ("ocr_truth/srv/2026_10_27_001707-b6f1134f", 9, 7909),
                ("ocr_truth/srv/2026_10_27_071406-defae43d", 11, 8121)]


@pytest.mark.parametrize("frame,line,board_shows", GROUP4_WRONG)
def test_departure_number_is_the_board_or_none(frame, line, board_shows):
    assert _lines(frame)[("departure", line)]["no"] in (board_shows, None)


# (A) the 7 cut by the joint is one glyph again: the four real ones read right
@pytest.mark.parametrize("frame,line,board_shows", [
    g for g in GROUP4_WRONG if g[2] in (7907, 7917, 9107) and "212606" not in g[0]])
def test_last_seven_cut_by_the_joint_reads(frame, line, board_shows):
    assert _lines(frame)[("departure", line)]["no"] == board_shows


# real component boxes (x, y, w, h; x3 mask) of srv 212506 departures line 9, "7907":
# the joint cuts the last 7 into bar+diagonal (tall) and the bar's right end (short)
BOXES_7907 = [[16, 8, 23, 32], [44, 7, 26, 33], [75, 7, 25, 33], [106, 7, 12, 33],
              [120, 7, 10, 17]]


def test_seven_cut_by_the_joint_is_glued():
    from app.ocr import digits
    out = digits._glue_seam_split([list(b) for b in BOXES_7907], 7, 33)
    assert len(out) == 4
    assert out[3][:4] == [106, 7, 24, 33]


@pytest.mark.parametrize("boxes", [
    [[106, 7, 12, 33], [120, 22, 10, 17]],   # the short piece is not at the line top
    [[106, 7, 12, 33], [121, 7, 14, 17]],    # too wide for one digit (29 > 0.85 x 33 px)
    [[106, 7, 12, 33], [126, 7, 4, 17]],     # gap beyond the joint's width (8 > 4.3 px)
    [[106, 7, 12, 15], [120, 7, 10, 17]],    # neither piece is a full-height stroke
])
def test_other_pieces_are_not_glued(boxes):
    from app.ocr import digits
    assert len(digits._glue_seam_split([list(b) for b in boxes], 7, 33)) == 2


# (B) Tesseract only breaks a near tie of the templates on the number, as on the platform
@pytest.mark.parametrize("stub,tess,want", [
    (("9", 0.791, 0.038, "90"), "3", ""),    # real 212606: 9/0 tie, Tesseract "3": unread
    (("9", 0.751, 0.016, "90"), "8", ""),    # real 205906: 9/0 tie, Tesseract "8": unread
    (("0", 0.775, 0.005, "086"), "8", "8"),  # real 054309: 0/8/6 tie settled by Tesseract
    (("1", 0.517, 0.135, "1"), "", ""),      # a weak "1" Tesseract did not see: unread
])
def test_tesseract_only_breaks_a_template_near_tie_on_the_number(stub, tess, want):
    from app.ocr.reader import _numeric
    assert _numeric("no", SOLID, (tess, 80.0), _Stub(*stub))[0] == want


class _Glyphs:
    """Templates stub with several glyphs: (ch, score, margin, near) each, full height."""

    def __init__(self, *gl):
        import numpy as np
        self.gl = [(ch, s, mg, np.ones((32, 32), np.float32), False) for ch, s, mg, _ in gl]
        self._near = [n for *_, n in gl]

    def glyphs(self, cell, allowed):
        return self.gl

    def read(self, cell, allowed):
        from app.ocr import digits
        return ("".join(g[0] for g in self.gl), min(g[1] for g in self.gl),
                all(digits.glyph_trusted(g[1], g[2]) for g in self.gl))

    def near(self, glyph, allowed):
        return next(n for g, n in zip(self.gl, self._near) if g[3] is glyph)


# a glyph that matches no template (score < MIN_SCORE) is not a digit Tesseract can confirm:
# real ocr14_delay100 044306 arrival 0, "401" with a 5 px sliver at the cell's right edge,
# read "1" 0.338 by the templates and "4011" by Tesseract under the "adapt" re-read
@pytest.mark.parametrize("weak,tess,want", [
    (("1", 0.338, 0.022, "17"), "4011", ""),  # confirmed only by Tesseract: unread
    (("7", 0.456, 0.028, "71"), "4017", ""),  # real 051311 kind (half of a cut 7)
    (("1", 0.62, 0.02, "17"), "4011", "4011"),  # a real but doubtful 1, confirmed: kept
])
def test_a_glyph_below_min_score_is_never_confirmed_on_the_number(weak, tess, want):
    from app.ocr.reader import _numeric
    m = _Glyphs(("4", 0.927, 0.21, "4"), ("0", 0.895, 0.091, "0"), ("1", 0.923, 0.21, "1"),
                weak)
    assert _numeric("no", SOLID, (tess, 80.0), m)[0] == want


def _three_and_sliver(sliver_w):
    """Three digit-sized blocks and a thin sliver at the right (x3 mask, 40 px high)."""
    import numpy as np
    cell = np.full((40, 163), 255, np.uint8)
    for x in (13, 43, 76):
        cell[3:40, x:x + 22] = 0
    cell[24:40, 136:136 + sliver_w] = 0
    return cell


@pytest.mark.parametrize("sliver_w,last,tess,want", [
    (3, ("7", 0.238, 0.023, "712"), "401", "401"),  # real 044306: Tesseract sees no 4th digit
    (3, ("7", 0.238, 0.023, "712"), "4017", ""),    # ...but never the sliver as a digit
    (12, ("7", 0.238, 0.023, "712"), "401", ""),    # a wide weak glyph may be a real digit
    (3, ("1", 0.52, 0.13, "1"), "401", ""),         # a weak but real-looking match: unread
])
def test_a_sliver_after_the_number_is_not_a_digit(sliver_w, last, tess, want):
    from app.ocr.reader import _numeric
    m = _Glyphs(("4", 0.927, 0.21, "4"), ("0", 0.895, 0.091, "0"), ("1", 0.923, 0.21, "1"),
                last)
    assert _numeric("no", _three_and_sliver(sliver_w), (tess, 80.0), m)[0] == want
