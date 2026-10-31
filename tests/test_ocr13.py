# © 2026 Andy217Ace
"""Delay column (Beta 1.13): the "+" is never read as a digit, a glared digit is unread.

Fixtures (tests/fixtures/ocr13/) are real captures of 21-22.10.2026 where the live
OCR stored "+465", "+355", "+240", "+435", "+230" for delays the board showed as
"+65", "+55", "+20", "+45", "+20": a glare blob on the board covers the first digit of
the delay in the top arrival rows, fuses it with the "+" and Tesseract read one digit
too many (or flipped the blurred digit). Every delay cell below was checked by eye on
the images: CLEAN cells are sharp and must read exactly; GLARED cells may read the
value shown or stay unread (None) — never another number, never 0.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.normalize import parse_delay
from app.ocr import digits, reader
from app.ocr.engine import CellResult
from app.ocr.reader import DELAY_UNREAD, _delay, read_board_debug
from tests.ocr_truth_images import capture

FIX = Path(__file__).parent / "fixtures" / "ocr13"

# frame -> {(board, line): delay shown on the board}
CLEAN = {
    "2026_10_21_143006-c3f9a8b7": {("arrival", 0): 60, ("arrival", 2): 25, ("arrival", 7): 35,
                                   ("departure", 2): 20},
    "2026_10_21_154305-5f2ac174": {("arrival", 0): 55, ("arrival", 2): 25, ("arrival", 7): 10,
                                   ("arrival", 9): 20, ("departure", 0): 60,
                                   ("departure", 1): 10},
    "2026_10_22_054309-ca4812a1": {("arrival", 1): 20, ("arrival", 2): 10, ("arrival", 3): 5,
                                   ("arrival", 7): 15},
    "2026_10_22_061953-5fed5dc7": {("arrival", 1): 15, ("arrival", 2): 15, ("arrival", 3): 10,
                                   ("departure", 0): 20, ("departure", 2): 5},
    "2026_10_22_070049-e2db40a5": {("departure", 0): 10},
    "2026_10_22_150306-764bb6bc": {("arrival", 1): 55, ("arrival", 2): 10, ("arrival", 3): 15,
                                   ("arrival", 6): 25, ("arrival", 7): 10,
                                   ("departure", 1): 35},
    "2026_10_22_151207-69c13b67": {("arrival", 1): 55, ("arrival", 2): 20, ("arrival", 3): 5,
                                   ("arrival", 5): 25, ("arrival", 6): 10,
                                   ("departure", 0): 35},
    "2026_10_22_152405-50bf039f": {("arrival", 1): 10, ("arrival", 2): 25, ("arrival", 3): 20,
                                   ("departure", 0): 35},
}
# glare over the first digit: (frame, board, line, value shown, value stored live)
GLARED = [
    ("2026_10_22_150306-764bb6bc", "arrival", 0, 65, 465),
    ("2026_10_22_152405-50bf039f", "arrival", 0, 55, 355),
    ("2026_10_22_070049-e2db40a5", "arrival", 0, 45, 465),
    ("2026_10_22_061953-5fed5dc7", "arrival", 0, 45, 465),
    ("2026_10_22_054309-ca4812a1", "arrival", 0, 20, 230),
    ("2026_10_21_154305-5f2ac174", "arrival", 1, 45, 435),
    ("2026_10_21_143006-c3f9a8b7", "arrival", 1, 20, 240),
]
# 151207: the glare also hides the arrival line 0 number/time; Beta 1.12 already left
# that line unread with Tesseract 5.5 (it read with 5.3.4 live): no 12/12 check on it.
FULL = sorted(set(CLEAN) - {"2026_10_22_151207-69c13b67"})

_cache: dict[str, tuple] = {}


def _read(name: str):
    if name not in _cache:
        _cache[name] = read_board_debug(capture(FIX / f"{name}.jpg").read_bytes())
    return _cache[name]


def _line(debug, board, idx):
    return next(d for d in debug if d["board"] == board and d["row_index"] == idx)


@pytest.mark.parametrize("name", FULL)
def test_frames_keep_12_rows_per_panel(name):
    rows, _ = _read(name)
    per = {b: sum(r.board == b and bool(r.train_no) for r in rows) for b in reader.BOARDS}
    # 070049 departures line 2 shows 8121 (truth.json); the reader published 2121, now
    # unread (Ruling R24: a number Tesseract alone read is not published)
    want = 11 if name == "2026_10_22_070049-e2db40a5" else 12
    assert per == {"arrival": 12, "departure": want}


@pytest.mark.parametrize("name", sorted(CLEAN))
def test_clean_delays_read_exactly(name):
    _, debug = _read(name)
    for (board, idx), shown in CLEAN[name].items():
        d = _line(debug, board, idx)
        assert d["fields"]["delay"]["norm"] == shown, (board, idx, d["fields"]["delay"])
        if d["row"] is None:
            continue
        assert d["row"].delay_read and d["row"].delay_min == shown


@pytest.mark.parametrize("name,board,idx,shown,live", GLARED)
def test_glared_delay_is_the_value_shown_or_unread(name, board, idx, shown, live):
    _, debug = _read(name)
    d = _line(debug, board, idx)
    got = d["fields"]["delay"]["norm"]
    assert got in (shown, None), d["fields"]["delay"]
    if got is None:  # unread: a missing delay, never "on time"
        assert d["row"] is not None and not d["row"].delay_read
        assert d["fields"]["delay"]["raw"] == DELAY_UNREAD
        assert d["fields"]["delay"]["check"]


@pytest.mark.parametrize("name", sorted(CLEAN))
def test_no_delay_of_three_digits_and_empty_cells_stay_on_time(name):
    rows, debug = _read(name)
    assert all(r.delay_min < 100 for r in rows)
    for d in debug:
        if d["row"] is not None and d["fields"]["delay"]["raw"] == "":
            assert d["row"].delay_read and d["row"].delay_min == 0


def test_glare_frames_no_longer_give_the_live_misreads():
    """The values stored live (465, 355, 240, 435, 230) do not come out any more."""
    for name, board, idx, _shown, live in GLARED:
        if live >= 100:
            _, debug = _read(name)
            assert _line(debug, board, idx)["fields"]["delay"]["norm"] != live


# --- unit rules of _delay on synthetic cells ----------------------------------------

def _cross(h=24, w=20, t=4):
    g = np.zeros((32, 32), np.float32)
    y0, x0 = (32 - h) // 2, (32 - w) // 2
    g[16 - t // 2:16 + t - t // 2, x0:x0 + w] = 1
    g[y0:y0 + h, 16 - t // 2:16 + t - t // 2] = 1
    return g


def test_is_plus_accepts_a_cross_and_rejects_digits_and_blobs():
    assert digits.is_plus(_cross())
    blob = np.zeros((32, 32), np.float32)
    blob[6:26, 6:26] = 1
    assert not digits.is_plus(blob)  # glare fused into a filled block
    m = digits.DigitMatcher.load()
    for ch, tpl in zip(m.labels, m.templates):
        if ch.isdigit():
            assert not digits.is_plus(tpl), ch


class _Fake:
    """A matcher returning fixed glyphs (character, score, margin)."""

    def __init__(self, glyphs, fused=False):
        self._g = [(c, s, mg, _cross() if c == "+" else np.ones((32, 32), np.float32), fused)
                   for c, s, mg in glyphs]

    def glyphs(self, cell, allowed):
        return self._g


CELL = np.full((30, 90), 255, np.uint8)
GOOD = (0.9, 0.2)
WEAK = (0.7, 0.01)  # untrusted (near tie with the runner-up)


@pytest.mark.parametrize("glyphs,tess,want,why", [
    # all glyphs trusted: the template reading, whatever Tesseract says
    ([("+", *GOOD), ("6", *GOOD), ("5", *GOOD)], ("+465", 80.0), "+65", None),
    # a weak glyph is accepted only where Tesseract reads the same digit
    ([("+", *GOOD), ("4", *WEAK), ("5", *GOOD)], ("+45", 91.0), "+45", None),
    ([("+", *GOOD), ("8", *WEAK), ("5", *GOOD)], ("+65", 57.0), DELAY_UNREAD, "disagree"),
    # Tesseract with one digit too many ("+" fused with the glare): unread
    ([("+", *GOOD), ("4", *WEAK), ("5", *GOOD)], ("+465", 77.0), DELAY_UNREAD, "count"),
    # three digits: every glyph trusted and both readers agreeing, else unread
    ([("+", *GOOD), ("1", *GOOD), ("2", *GOOD), ("0", *GOOD)], ("+120", 90.0), "+120", None),
    ([("+", *GOOD), ("1", *GOOD), ("2", *GOOD), ("0", *GOOD)], ("+20", 90.0),
     DELAY_UNREAD, "three_digits"),
    ([("+", *GOOD), ("4", *WEAK), ("6", *GOOD), ("5", *GOOD)], ("+465", 90.0),
     DELAY_UNREAD, "three_digits"),
    # no "+" in front: not a delay as the board prints it
    ([("4", *GOOD), ("5", *GOOD)], ("45", 90.0), DELAY_UNREAD, "no_plus"),
    ([("+", *GOOD), ("1", *GOOD), ("2", *GOOD), ("3", *GOOD), ("4", *GOOD)], ("+1234", 90.0),
     DELAY_UNREAD, "digits"),
    ([("+", *GOOD)], ("+", 90.0), DELAY_UNREAD, "digits"),
    ([("+", *GOOD), ("+", *GOOD), ("5", *GOOD)], ("++5", 90.0), DELAY_UNREAD, "plus_twice"),
])
def test_delay_rules(glyphs, tess, want, why):
    text, conf, reason = _delay(CELL, tess, _Fake(glyphs))
    assert (text, reason) == (want, why)
    if want == DELAY_UNREAD:
        assert conf is None and parse_delay(text) is None  # missing, never 0


def test_weak_digit_cut_out_of_a_fused_blob_is_unread_even_if_tesseract_agrees():
    """Glare fuses "+" and the first digit into one blob: both readers guess the hidden
    upper half the same way ("+85" for the "+65" on the board)."""
    g = [("+", *GOOD), ("8", *WEAK), ("5", *GOOD)]
    assert _delay(CELL, ("+85", 48.0), _Fake(g, fused=True))[::2] == (DELAY_UNREAD, "glare")
    assert _delay(CELL, ("+85", 48.0), _Fake(g, fused=False))[0] == "+85"
    good = [("+", *GOOD), ("6", *GOOD), ("5", *GOOD)]  # trusted glyphs stay read
    assert _delay(CELL, ("+65", 90.0), _Fake(good, fused=True))[0] == "+65"


def test_empty_delay_cell_is_on_time_and_no_matcher_keeps_tesseract():
    assert _delay(CELL, ("", None), _Fake([]))[0] == ""
    assert parse_delay("") == 0
    assert _delay(CELL, ("+25", 88.0), None) == ("+25", 88.0, None)


class _Engine:
    """Tesseract stand-in: '+465' in the delay column, plausible text elsewhere."""

    def read_cells(self, image, whitelist, lang, psm):
        return [CellResult("+465", 80.0, (12, 12, 40, 20))] if whitelist == "0123456789+" else []


def test_unread_delay_keeps_the_row_and_reports_why():
    rows, debug = read_board_debug(capture(FIX / "2026_10_22_150306-764bb6bc.jpg").read_bytes(),
                                   _Engine(), budget_s=0)
    d = _line(debug, "arrival", 0)
    assert d["fields"]["delay"]["norm"] in (65, None)
    assert d["fields"]["delay"]["norm"] != 465


def test_line_version_tags_delay_checks_and_retries():
    from app.observations import PROCESSING_VERSION, line_version, parse_line_version
    assert PROCESSING_VERSION == "ocr-tess-grid-5"  # Beta 1.31 (test_ocr_platform_cut)
    e = {"state": "ok", "fields": {"delay": {"check": "glare"}}}
    assert line_version("v", e) == "v+delay:glare"
    e = {"state": "ok", "fields": {"delay": {"retry": {"variant": "lvl+", "attempts": 1}}}}
    assert line_version("v", e) == "v+delay-retry:lvl+:1"
    assert parse_line_version("v+delay:glare+delay-retry:none:4")["state"] == "ok"


def test_delay_reread_takes_a_variant_only_when_the_rules_pass(monkeypatch):
    """A delay left unread by the first pass is re-read with other binarisations; the
    variant's reading is used only if it passes the same rules (here: it does on the
    second variant), and the row then carries the value as a reading."""
    calls = {"n": 0}
    real = reader._delay

    def fake(cell, tess, matcher):
        calls["n"] += 1
        text, conf, why = real(cell, tess, matcher)
        if why is not None and "reread" in calls:
            calls["reread"] += 1
            return ("+65", 70.0, None) if calls["reread"] >= 2 else (DELAY_UNREAD, None, "count")
        return text, conf, why

    monkeypatch.setattr(reader, "_delay", fake)
    orig = reader._reread_delays

    def wrap(*a, **k):
        calls["reread"] = 0
        return orig(*a, **k)
    monkeypatch.setattr(reader, "_reread_delays", wrap)
    _, debug = read_board_debug(capture(FIX / "2026_10_22_150306-764bb6bc.jpg").read_bytes())
    d = _line(debug, "arrival", 0)
    f = d["fields"]["delay"]
    assert "retry" in f  # the first pass left it unread (glare)
    assert f["norm"] == 65 and f["retry"]["variant"] == reader.DELAY_VARIANTS[1]
    assert d["row"].delay_read and d["row"].delay_min == 65 and "check" not in f


def test_line_version_parses_variant_names_with_plus():
    from app.observations import parse_line_version
    got = parse_line_version("ocr-tess-grid-3+retry:lvl+:2+delay-retry:lvl+:1")
    assert got["retry"] == {"variant": "lvl+", "attempts": 2}


def test_no_templates_still_refuses_three_digit_delays():
    assert _delay(CELL, ("+465", 80.0), None)[::2] == (DELAY_UNREAD, "three_digits")
