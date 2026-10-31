# © 2026 Andy217Ace
"""OCR quality wave 1 (Beta 1.16): hand-labelled truth set + the panel-seam fixes.

Truth set: tests/fixtures/ocr_truth/truth.json — 16 real captures (the 8 of
tests/fixtures/ocr13 + 8 picked for the measured errors of the audit), 384 lines, every
field checked by eye on the image (app/ocr/truth.py). The thresholds below are the
measured accuracy of this version: a change that misreads more cells fails here.

Seam: a vertical joint between two LED modules of the board runs through the last
digit of the train number. It cuts the thin "1" into its flag and its stem (two
components): the templates then saw 5 glyphs for "5021" (untrusted) and Tesseract
dropped the "1" (5021 -> 502, 1661 -> 166) or read "4" (9101 -> 9104, 1571 -> 1574).
In the time column the lit joint itself came out as a 2 px "glyph" (1:10 -> 1:40).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.ocr import digits, truth
from app.ocr.reader import read_board_debug

FIX = Path(__file__).parent / "fixtures"
TRUTH = truth.load(FIX / "ocr_truth" / "truth.json")

# measured on this version (Tesseract 5.5, local); `wrong` is a published misread,
# `unread` an honest gap. Beta 1.15 on the same set: wrong no 19, time 6, platform 5
# (+3 unread), station 2, operator 1; ok no 365, time 378, platform 376.
# Left wrong: number under glare (4), 8 read 3 (time 2, platform 1).
MAX_WRONG = {"no": 0, "time": 4, "type": 2, "platform": 0, "delay": 0,
             "station": 3, "operator": 5}
MIN_OK = {"no": 379, "time": 381, "type": 383, "platform": 382, "delay": 374,
          "station": 381, "operator": 382}

_cache: dict[str, list] = {}


def _debug(frame: str) -> list:
    if frame not in _cache:
        _cache[frame] = read_board_debug((FIX / f"{frame}.jpg").read_bytes(), budget_s=60.0)[1]
    return _cache[frame]


@pytest.fixture(scope="module")
def result():
    preds = {frame: truth.lines_of(_debug(frame)) for frame in TRUTH["frames"]}
    return truth.score(TRUTH, preds)


def test_truth_set_has_about_300_labelled_lines():
    lines = [line for b in TRUTH["frames"].values() for ls in b.values() for line in ls]
    assert len(lines) >= 300
    assert all(set(truth.FIELDS) <= set(line) for line in lines)


@pytest.mark.parametrize("field", truth.FIELDS)
def test_field_accuracy_does_not_regress(result, field):
    c = result["counts"][field]
    misses = result["misses"][field]
    assert c["wrong"] <= MAX_WRONG[field], misses
    assert c["ok"] >= MIN_OK[field], misses


def test_score_counts_unread_and_wrong_separately():
    t = {"frames": {"f": {"arrival": [{"no": 3021, "time": "05:40", "platform": None,
                                       "delay": "?"}]}}}
    got = {"f": {("arrival", 0): {"no": 302, "time": None, "platform": 4, "delay": 999}}}
    c = truth.score(t, got)["counts"]
    assert c["no"]["wrong"] == 1 and c["time"]["unread"] == 1
    assert c["platform"]["wrong"] == 1  # a value invented for a blank cell is wrong
    assert sum(c["delay"].values()) == 0  # "?" is not scored
    assert truth.score(t, {})["counts"]["no"]["unread"] == 1  # line not read at all


# --- template reading confirmed glyph by glyph by Tesseract ----------------------------

GOOD, WEAK = (0.9, 0.2), (0.85, 0.01)  # WEAK: near tie with the runner-up template


class _Fake:
    def __init__(self, glyphs):
        self._g = [(c, s, m, None, False) for c, s, m in glyphs]

    def glyphs(self, cell, allowed):
        return self._g

    def read(self, cell, allowed):
        return ("".join(c for c, *_ in self._g), min(s for _, s, *_ in self._g),
                all(digits.glyph_trusted(s, m) for _, s, m, *_ in self._g))


def _g(text, weak):
    return [(c, *(WEAK if i in weak else GOOD)) for i, c in enumerate(text)]


@pytest.mark.parametrize("glyphs,tess,want", [
    (_g("8121", {0}), "812", "8121"),     # Tesseract dropped the (trusted) last "1"
    (_g("1583", {2}), "13583", "1583"),   # ...or added a digit
    (_g("1584", {2}), "4584", "1584"),    # trusted "1" wins, doubtful "8" confirmed
    (_g("7908", {3}), "7308", "7908"),
    (_g("1583", {2}), "1533", ""),        # doubtful glyph not confirmed: unread (R24)
    (_g("8121", {0}), "21", ""),          # two digits apart: no alignment, unread (R24)
    (_g("8121", {3}), "812", ""),         # the dropped glyph is the doubtful one: unread
    (_g("79095", {3}), "7909", ""),       # only a dropped "1", never another digit: unread
    (_g("79111", {3}), "7919", ""),       # "9" split in two: no shifted alignment: unread
    (_g("5021", {3}), "502", ""),         # the dropped last "1" must be trusted: unread
    (_g("15211", {1}), "1521", "15211"),  # dropped last "1", the rest equal
    (_g("1583", {2}), "15373", ""),       # extra character but the rest differs: unread
])
def test_numeric_template_confirmed_by_tesseract(glyphs, tess, want):
    from app.ocr.reader import _numeric
    cell = np.zeros((10, 10), np.uint8)
    assert _numeric("no", cell, (tess, 80.0), _Fake(glyphs))[0] == want


# --- platform: digit top cut by the band, platforms 1-14 ------------------------------

def test_platform_cell_grows_up_when_the_digit_top_is_cut():
    from app.ocr.reader import grow_up
    mask = np.full((80, 40), 255, np.uint8)
    mask[2:10, 10:30] = 0    # bottom of the line above's digit (in the added rows)
    mask[22:60, 12:30] = 0   # this line's digit, starting 8 px above the band
    cell = grow_up(mask, (30, 62), 0, 40, 12)
    assert cell.shape == (44, 40)
    ys = np.nonzero((cell == 0).any(axis=1))[0]
    assert ys.min() == 22 - 18 and ys.max() == 59 - 18  # whole digit, nothing above it
    mask2 = np.full((80, 40), 255, np.uint8)
    mask2[34:60, 12:30] = 0  # ink not touching the top: cell unchanged
    assert grow_up(mask2, (30, 62), 0, 40, 12).shape == (32, 40)
    mask3 = mask.copy()
    mask3[24:34, 34:38] = 0  # a thin piece crossing the band top only: kept ("11")
    assert (grow_up(mask3, (30, 62), 0, 40, 12)[6:16, 34:38] == 0).all()


@pytest.mark.parametrize("s,exp", [("1", 1), ("14", 14), ("15", None), ("17", None),
                                   ("0", None)])
def test_platform_is_1_to_14(s, exp):
    from app.normalize import parse_platform
    assert parse_platform(s) == exp


# --- segmentation on synthetic cells (ink = 0 on white, x3 mask scale) ----------------

def _cell(boxes, h=42, w=160):
    c = np.full((h, w), 255, np.uint8)
    for x0, y0, x1, y1 in boxes:
        c[y0:y1, x0:x1] = 0
    return c


def _ring(x):  # a digit-sized "0"
    return [(x, 6, x + 24, 10), (x, 36, x + 24, 40), (x, 6, x + 5, 40), (x + 19, 6, x + 24, 40)]


def test_seam_split_one_is_glued_back_into_one_glyph():
    """The flag (upper left, small) and the stem of "1" 1-3 px apart: one glyph."""
    flag = (107, 9, 117, 20)
    for gap in (-1, 0, 1, 2, 3):  # -1: the flag's box overlaps the stem's by 1 px
        stem = (117 + gap, 6, 123 + gap, 40)
        spans = [s for _, s, _ in digits.segment_spans(_cell(_ring(14) + _ring(44) + _ring(74)
                                                             + [flag, stem]))]
        assert len(spans) == 4, (gap, spans)
        assert spans[-1] == (107, 123 + gap)


def test_digit_cut_in_two_by_the_seam_is_one_glyph():
    """7909: the joint cut the last "9" into a left part and a right part 1 px apart
    (seen as "9" + "1": 79091)."""
    left = [(106, 9, 119, 30), (106, 33, 119, 42)]
    right = (120, 9, 130, 42)
    spans = digits.segment_spans(_cell(_ring(16) + _ring(45) + _ring(75) + left + [right]))
    assert [s for _, s, _ in spans][-1] == (106, 130) and len(spans) == 4


def test_flag_far_from_the_stem_or_low_fragments_stay_separate():
    stem = (126, 6, 132, 40)
    far = digits.segment_spans(_cell(_ring(14) + [(107, 9, 117, 20), stem]))
    assert len(far) == 3  # 9 px apart: not the same glyph
    low = digits.segment_spans(_cell(_ring(14) + [(107, 26, 115, 37), (118, 6, 124, 40)]))
    assert len(low) == 3  # a fragment at the bottom, 3 px away, is no flag


def test_colon_next_to_a_one_is_not_glued():
    """1:10 — the colon (two dots) sits 3 px left of the stem of the next "1"."""
    colon = [(76, 12, 82, 17), (76, 27, 82, 32)]
    one = (85, 6, 91, 40)
    spans = digits.segment_spans(_cell(_ring(14) + _ring(44) + colon + [one]))
    assert [x1 - x0 for _, (x0, x1), _ in spans][-2:] == [6, 6]


def test_lit_seam_line_is_not_a_glyph():
    """A 2 px wide vertical joint (broken in pieces) between two digits is dropped."""
    seam = [(107, 0, 109, 3), (107, 12, 109, 23), (107, 27, 109, 29)]
    spans = digits.segment_spans(_cell(_ring(74) + seam + _ring(116), h=40))
    assert [s for _, s, _ in spans] == [(74, 98), (116, 140)]
    # a short thin sliver (what glare left of a digit) is kept: dropping it would turn
    # "4:37" into a trusted "7:37"
    sliver = digits.segment_spans(_cell([(18, 24, 20, 34)] + _ring(40), h=42))
    assert len(sliver) == 2


def test_reread_that_lost_a_glyph_of_the_first_pass_is_not_taken():
    """lvl+ wipes what glare left of the first digit of "4:37": the rest reads as a
    trusted "7:37". A re-read whose glyphs start (or end) half a line inside the first
    pass's is not used."""
    from app.ocr.reader import _lost_ink
    base = _cell([(18, 27, 25, 33), (26, 27, 36, 33)] + _ring(44) + _ring(84))
    lost = _cell(_ring(44) + _ring(84))
    assert _lost_ink(base, lost)
    assert not _lost_ink(base, base)
    assert not _lost_ink(lost, base)  # a re-read that sees more is fine


# --- +100 under glare: vote across frames (IRN 401, arrivals line 0, 23.10.2026) ------
# The board showed "+100" (checked by eye by the user, 07:47 RO). Glare hides the top
# of the middle digit: per frame the readers alternate 100 / 160 / 180, so a single
# frame stays unread ("three_digits"); several frames in a row vote.
D100 = sorted((FIX / "ocr14_delay100").glob("*.jpg"))


def _arr0(debug):
    return next(d for d in debug if d["board"] == "arrival" and d["row_index"] == 0)


def test_hundred_alone_in_one_frame_is_unread_never_a_guess():
    for path in D100:
        line = _arr0(read_board_debug(path.read_bytes(), budget_s=60.0)[1])
        assert line["row"].train_no == 401
        f = line["fields"]["delay"]
        assert f["norm"] is None and f["check"] == "three_digits"
        assert f["candidate"].startswith("+1") and len(f["candidate"]) == 4


def test_hundred_read_by_the_vote_of_consecutive_frames():
    from app.ocr.reader import DelayVotes
    votes, got = DelayVotes(), []
    for path in D100:
        line = _arr0(read_board_debug(path.read_bytes(), budget_s=60.0, votes=votes)[1])
        got.append(line["fields"]["delay"]["norm"])
        if got[-1] is not None:
            assert line["row"].delay_read and line["row"].delay_min == 100
            assert line["fields"]["delay"]["retry"]["variant"] == "vote"
    assert set(got) <= {100, None}  # never 160 / 180 / 150
    assert got.count(100) >= 4
    assert got[:3] == [None, None, None]  # never on the first frames


def _entry(no, cand, board="arrival"):
    from app.models import Row
    row = Row(board=board, train_type="IRN", train_no=no, station="X", operator="Y",
              sched_time="06:38", delay_min=0, delay_read=False, platform=None,
              flagged=False, confidence=0.9)
    f = {"raw": "+?", "norm": None, "check": "three_digits"} if cand else {"raw": "+?",
                                                                            "norm": None}
    if cand:
        f["candidate"] = cand
    return {"board": board, "row_index": 0, "row": row, "raw_text": "",
            "fields": {n: {"raw": "", "norm": None} for n in truth.FIELDS} | {"delay": f}}


def test_vote_needs_a_majority_of_at_least_four_frames():
    from app.ocr.reader import DelayVotes
    v = DelayVotes()
    seq = ["+100", "+160", "+100", "+160", "+100", "+160", "+100"]
    out = []
    for c in seq:
        e = _entry(401, c)
        v.apply([e])
        out.append(e["fields"]["delay"]["norm"])
    assert out == [None] * 6 + [100]  # 4 of 7, majority; 160 (3 of 7) never
    v2 = DelayVotes()
    for c in ["+100", "+100", "+100", None, "+100"]:  # a frame without candidate counts
        e = _entry(401, c)
        v2.apply([e])
    assert e["fields"]["delay"]["norm"] == 100
    v3 = DelayVotes()
    for c in ["+100"] * 3:
        v3.apply([_entry(401, c)])
    v3.apply([_entry(402, "+100")])  # train 401 gone from the board: its votes go
    e = _entry(401, "+100")
    v3.apply([e])
    assert e["fields"]["delay"]["norm"] is None


def test_glare_misreads_of_two_digit_delays_give_no_candidate():
    """+65 -> "+465", +55 -> "+355" (tests/test_ocr13.py GLARED): two digits on the
    board, never a 100+ candidate."""
    from tests.test_ocr13 import FIX as F13, GLARED
    for name, board, idx, _shown, _live in GLARED:
        _, debug = read_board_debug((F13 / f"{name}.jpg").read_bytes(), budget_s=60.0)
        line = next(d for d in debug if d["board"] == board and d["row_index"] == idx)
        assert "candidate" not in line["fields"]["delay"]
