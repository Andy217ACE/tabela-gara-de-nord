# © 2026 Andy217Ace
"""Beta 1.27 — reflexii / săgeata tabelei peste celule (live 27.10 07:46, capturile 8465-8467):
(A) întârziere cu „+” (și prima cifră) acoperit, (B) ora programată cu două puncte acoperite.

Regula: sub pată pixelii nu mai există, deci nu se „citește” nimic de acolo. Se completează doar
ce dovezile lasă neechivoc (cifre de încredere + ordinea cronologică a panoului + citirile
anterioare ale aceluiași tren), altfel celula rămâne necitită."""
from pathlib import Path

import pytest

from app.models import Row
from app.ocr import glare
from app.ocr.reader import (INFER_MAX_RUN, INFER_STABLE, INFERRED, TIME_KEEP, DelayVotes,
                            read_board_debug)

FIX = Path(__file__).parent / "fixtures" / "glare"
T, F = True, False


def G(*items):
    """glyphs: "7" trusted, "1?" untrusted."""
    return [(s[0], not s.endswith("?")) for s in items]


# -- B. ora programată: candidate din glifele de încredere ------------------------------------

def test_hidden_colon_leaves_one_time():
    # "7[blob]37": the colon slot holds a glyph the templates do not trust
    assert glare.time_candidates(G("7", "1?", "3", "7")) == {"07:37": 0}


def test_colon_slot_never_takes_a_trusted_digit_as_colon():
    # a trusted digit where the colon belongs: not "H:MM"; "73:37" is no time either
    assert glare.time_candidates(G("7", "3", "3", "7")) == {}
    # five glyphs: HH:MM, colon slot untrusted
    assert glare.time_candidates(G("1", "0", "1?", "3", "7")) == {"10:37": 0}
    assert glare.time_candidates(G("1", "0", "3", "3", "7")) == {}  # trusted digit as colon


def test_one_hidden_digit_is_a_wildcard_two_are_not():
    c = glare.time_candidates(G("7", ":", "3?", "7"))
    assert c["07:37"] == 1 and c["07:07"] == 1 and len(c) == 6  # 07:x7, x in 0..5
    assert glare.time_candidates(G("7", ":", "3?", "7?")) == {}
    assert len(glare.time_candidates(G("7?", "1?", "3", "7"))) == 10  # hidden hour digit
    assert glare.time_candidates(G("7?", "1?", "3?", "7")) == {}  # two hidden digits


def test_three_glyphs_colon_dropped_by_the_segmentation():
    assert glare.time_candidates(G("7", "3", "7")) == {"07:37": 0}
    assert glare.time_candidates(G("7", "3")) == {}  # not a time shape


@pytest.mark.parametrize("t,lo,hi,ok", [
    ("07:37", "07:31", "07:43", True),
    ("07:37", "07:40", "07:43", False),   # before the line above
    ("07:37", "07:31", "07:36", False),   # after the line below
    ("07:37", None, "07:43", True),
    ("00:05", "23:50", "00:10", True),    # midnight wrap
    ("12:00", "23:50", "00:10", False),
])
def test_neighbour_bounds(t, lo, hi, ok):
    assert glare.fits(t, lo, hi) is ok


def test_pick_needs_exactly_one_time_after_the_bounds():
    one = {"07:37": 0}
    assert glare.pick_time(one, "07:31", "07:43") == "07:37"
    assert glare.pick_time(one, "07:40", "07:43") is None  # the order excludes it
    # a wildcard digit is free only when BOTH neighbours bound it
    wild = {f"07:{m}7": 1 for m in ("0", "1", "2", "3", "4", "5")}
    assert glare.pick_time(wild, "07:31", "07:43") == "07:37"
    assert glare.pick_time(wild, "07:31", None) is None
    assert glare.pick_time(wild, None, "07:43") is None
    assert glare.pick_time(wild, "07:00", "07:59") is None  # several left


def test_pick_agrees_with_the_trains_earlier_time_or_says_nothing():
    one = {"07:37": 0}
    assert glare.pick_time(one, None, None, hint="07:37") == "07:37"
    assert glare.pick_time(one, None, None, hint="07:47") is None  # contradicts the history
    wild = {f"07:{m}7": 1 for m in ("0", "1", "2", "3", "4", "5")}
    assert glare.pick_time(wild, None, None, hint="07:37") == "07:37"  # history picks it
    assert glare.pick_time(wild, None, None, hint="08:37") is None     # not allowed by glyphs


# -- A. întârzierea: cifra unităților + citirile anterioare -------------------------------------

def raw(*items):
    return [(c, s, m, None, fused) for c, s, m, fused in items]


def test_tail_needs_a_trusted_units_digit_both_readers_agree_on():
    ok = raw(("+", 0.74, 0.106, True), ("4", 0.55, 0.065, True), ("5", 0.91, 0.139, False))
    assert glare.delay_tail(ok, "+45") == "5"
    assert glare.delay_tail(ok, "+4") is None             # Tesseract's last digit differs
    weak = raw(("+", 0.7, 0.1, False), ("5", 0.55, 0.02, False))
    assert glare.delay_tail(weak, "+5") is None            # not trusted
    fused = raw(("+", 0.7, 0.1, True), ("5", 0.75, 0.05, True))
    assert glare.delay_tail(fused, "+5") is None           # fused: a clear match only
    seven = raw(("+", 0.9, 0.2, False), ("7", 0.95, 0.3, False))
    assert glare.delay_tail(seven, "+7") is None           # the board counts in 5-minute steps
    assert glare.delay_tail(raw(("5", 0.9, 0.2, False)), "5") is None  # one glyph: no context


def _row(no, delay=0, read=True, t="07:31"):
    return Row(board="arrival", train_type="RE", train_no=no, station="BUZAU",
               operator="CFR Calatori", sched_time=t, delay_min=delay, delay_read=read,
               confidence=0.9)


def _entry(no, *, delay=None, check=None, seen=None, tail=None, t="07:31"):
    d = {"raw": "", "norm": delay, "conf": None}
    if check:
        d.update(check=check, seen=seen, raw="+?")
        if tail:
            d["tail"] = tail
    fields = {n: {"raw": "", "norm": None} for n in ("type", "no", "station", "operator",
                                                      "platform")}
    fields["time"] = {"raw": t, "norm": t}
    return {"board": "arrival", "row_index": 0, "raw_text": "", "fields": fields | {"delay": d},
            "row": _row(no, delay or 0, read=check is None, t=t)}


def _feed(votes, no, delays):
    """Frames of one train: an int is a real reading, a (check, seen, tail) a glared cell."""
    out = []
    for d in delays:
        e = _entry(no, delay=d) if isinstance(d, int) else _entry(
            no, check=d[0], seen=d[1], tail=d[2])
        votes.apply([e])
        out.append(e)
    return out


def test_glared_delay_keeps_the_value_the_train_had_before():
    v = DelayVotes()
    *_, e = _feed(v, 5002, [15, 15, 15, ("glare", "+45", "5")])  # live 27.10: "+15" under the blob
    f = e["fields"]["delay"]
    assert e["row"].delay_read and e["row"].delay_min == 15 and e["row"].uncertain
    assert f["norm"] == 15 and f["check"] == INFERRED == "glare_inferred" and f["conf"] == 55.0


def test_the_tens_digit_under_the_blob_is_never_read():
    v = DelayVotes()
    # Tesseract saw +465 / +75 for a hidden +15: the value is the one of the frames before
    *_, e = _feed(v, 5002, [15, 15, 15, ("glare", "+465", "5")])
    assert e["row"].delay_min == 15
    v = DelayVotes()
    *_, e = _feed(v, 5002, [25, 25, 25, ("no_plus", "+75", "5")])
    assert e["row"].delay_min == 25


def test_inference_needs_a_steady_history_and_a_matching_units_digit():
    # units digit differs: the delay changed under the blob -> unread
    *_, e = _feed(DelayVotes(), 1, [15, 15, 15, ("glare", "+20", "0")])
    assert not e["row"].delay_read and e["fields"]["delay"]["check"] == "glare"
    # not enough readings / readings not all alike
    *_, e = _feed(DelayVotes(), 1, [15, 15, ("glare", "+5", "5")])
    assert not e["row"].delay_read
    *_, e = _feed(DelayVotes(), 1, [10, 15, 15, ("glare", "+5", "5")])
    assert not e["row"].delay_read
    # no clear units digit
    *_, e = _feed(DelayVotes(), 1, [15, 15, 15, ("glare", "+5", None)])
    assert not e["row"].delay_read
    # never seen before the glare: nothing to keep
    *_, e = _feed(DelayVotes(), 1, [("glare", "+5", "5")] * 3)
    assert not e["row"].delay_read
    assert INFER_STABLE == 3


def test_other_unread_reasons_are_never_inferred():
    for why in ("three_digits", "count", "disagree", "not_step", "plus_twice", "digits"):
        *_, e = _feed(DelayVotes(), 1, [15, 15, 15, (why, "+5", "5")])
        assert not e["row"].delay_read, why


def test_a_long_run_is_not_inferred_forever_and_a_real_reading_restarts_it():
    v = DelayVotes()
    got = [e["row"].delay_read for e in _feed(v, 7, [15, 15, 15] + [("glare", "+5", "5")] * (
        INFER_MAX_RUN + 3))][3:]
    assert got == [True] * INFER_MAX_RUN + [False] * 3
    more = _feed(v, 7, [15, ("glare", "+5", "5")])  # a real reading: the count starts again
    assert more[-1]["row"].delay_read


def test_history_goes_with_the_train():
    v = DelayVotes()
    _feed(v, 5002, [15, 15, 15])
    v.apply([_entry(9999)])  # 5002 left the board: its readings go
    *_, e = _feed(v, 5002, [("glare", "+5", "5")])
    assert not e["row"].delay_read


def test_a_changed_reading_is_not_overridden_by_the_old_value():
    v = DelayVotes()
    es = _feed(v, 5002, [15, 15, 15, 20, ("glare", "+0", "0")])
    assert es[-1]["row"].delay_min == 0 and not es[-1]["row"].delay_read  # 15 x3 no more steady


def test_clean_times_are_remembered_per_train_filled_ones_are_not():
    v = DelayVotes()
    assert v.time_hint("arrival", 9202) is None
    for _ in range(3):
        v.apply([_entry(9202, t="07:37")])
    assert v.time_hint("arrival", 9202) == "07:37" and v.time_hint("departure", 9202) is None
    e = _entry(9202, t="07:47")  # a different reading breaks unanimity
    v.apply([e])
    assert v.time_hint("arrival", 9202) is None
    v2 = DelayVotes()
    for _ in range(4):
        e = _entry(9202, t="07:37")
        e["fields"]["time"]["check"] = glare.FILLED  # filled: no proof of its own
        v2.apply([e])
    assert v2.time_hint("arrival", 9202) is None
    v3 = DelayVotes()
    for _ in range(3):
        v3.apply([_entry(9202, t="07:37")])
    for _ in range(TIME_KEEP + 1):  # the train is gone for good
        v3.apply([_entry(1)])
    assert v3.time_hint("arrival", 9202) is None


# -- cadre reale (capturile live din 27.10, 07:3x-07:4x ora României) --------------------------

def _line(debug, board, row_index):
    return next(e for e in debug if e["board"] == board and e["row_index"] == row_index)


def _read(name, votes=None):
    return read_board_debug((FIX / f"{name}.jpg").read_bytes(), budget_s=60.0, votes=votes)[1]


def test_real_frame_hidden_colon_time_is_completed_from_the_panel_order():
    """Capture 8467: "RE 9202 PITESTI 7[blob]37" between 07:31 (line 0) and 07:43 (line 2):
    the line used to stay unread and the train was missing from the board."""
    line = _line(_read("c8467"), "arrival", 1)
    t = line["fields"]["time"]
    assert line["state"] == "ok" and line["row"].train_no == 9202
    assert t["norm"] == "07:37" and t["check"] == glare.FILLED and line["row"].sched_time == "07:37"
    assert line["row"].uncertain and line["row"].confidence < 0.7  # below a new service's bar
    assert t["seen"] != "07:37"  # what the cell gave is kept for the audit
    from app.observations import line_version
    assert "+time:glare_filled" in line_version("ocr-tess-grid-4", line)


def test_real_frame_alone_never_invents_the_glared_delay():
    """Capture 8467 on its own: "+15" is hidden under the blob and the train has no history:
    unread (the 45 / 75 / 465 of the cell are not the delay)."""
    line = _line(_read("c8467"), "arrival", 0)
    d = line["fields"]["delay"]
    assert line["row"].train_no == 5002 and d["norm"] is None and d["check"] == "glare"
    assert not line["row"].delay_read


def test_real_frames_glared_delay_follows_the_frames_before():
    """5002 read +15 three times (8454-8456), then the blob covers its "+" and the "1"
    (8458, 8467): the delay stays +15, marked."""
    votes = DelayVotes()
    for name in ("c8454", "c8455", "c8456"):
        _read(name, votes)
    for name in ("c8458", "c8467"):
        line = _line(_read(name, votes), "arrival", 0)
        d = line["fields"]["delay"]
        assert line["row"].train_no == 5002
        assert line["row"].delay_read and line["row"].delay_min == 15 and line["row"].uncertain
        assert d["norm"] == 15 and d["check"] == INFERRED
        from app.observations import line_version
        assert "+delay:glare_inferred" in line_version("ocr-tess-grid-4", line)


def test_clean_frame_is_untouched_by_the_glare_rules():
    debug = _read("c8449")
    assert all(e["fields"]["time"].get("check") != glare.FILLED for e in debug)
    assert all(e["fields"]["delay"].get("check") != INFERRED for e in debug)
    assert sum(e["row"] is not None for e in debug) >= 22
