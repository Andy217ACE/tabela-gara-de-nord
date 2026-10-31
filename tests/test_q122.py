# © 2026 Andy217Ace
"""Beta 1.22 — calitatea datelor, runda 3 (analiza istoricului live 21-26.10):
numere de tren cu cifre în plus/în minus pe același slot (stație + oră), nume de stații cu
spațiere diferită, ore programate cu cifre citite greșit, întârzieri care nu sunt multipli
de 5."""
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from app import canonical
from app.models import Row
from app.normalize import parse_delay
from app.ocr import digits, order
from app.ocr.reader import (DELAY_STEP, DELAY_UNREAD, _confirmed, _delay, read_board,
                            read_board_debug)
from app.store import Store, _fold_station, _near_dup, _same_station
from tests.ocr_truth_images import capture

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 10, 26, 11, 0, tzinfo=BUC)
FIX = Path(__file__).parent / "fixtures" / "q122"


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def at(m):
    return T0 + timedelta(minutes=m)


def R(no, t, station="PITESTI", board="departure", typ="RE", **kw):
    return Row(board=board, train_type=typ, train_no=no, station=station,
               operator="CFR Calatori", sched_time=t, station_raw=station, **kw)


def frame(extra=()):
    base = [R(1001, "11:40", "ARAD"), R(1002, "11:50", "ADJUD"), R(1003, "12:00", "BACAU"),
            R(2001, "11:45", "ARAD", board="arrival"),
            R(2002, "11:55", "ADJUD", board="arrival"),
            R(2003, "12:05", "BACAU", board="arrival")]
    return base + list(extra)


def svcs(store):
    return [tuple(r) for r in store._conn.execute(
        "SELECT train_no, sched_time, status FROM services WHERE station='PITESTI'"
        " ORDER BY id")]


# -- 1. numere: cifre în plus/în minus pe același slot --------------------------------------

@pytest.mark.parametrize("a,b", [
    (9209, 92011), (925, 92511), (7938, 79311), (7914, 79111), (1581, 45811),
    (157, 10157), (5019, 19), (8093, 93), (581, 1181), (4011, 401),
    (1584, 15811), (9201, 920), (7908, 73808)])
def test_variants_of_one_board_row_are_near_duplicates(a, b):
    ka = (a, "14:36", "PITESTI", "PITESTI")
    kb = (b, "14:36", "PITESTI", "PITESTI")
    assert _near_dup(ka, kb) and _near_dup(kb, ka)


@pytest.mark.parametrize("a,b,ta,tb,st_b", [
    (7914, 7938, "14:36", "14:36", "PITESTI"),     # two substitutions, same length: 2 trains
    (9209, 92011, "14:36", "14:37", "PITESTI"),    # another time
    (9209, 92011, "14:36", "14:36", "ARAD"),       # another station
    (9209, 9303, "14:36", "14:36", "PITESTI"),     # three edits
    (1234, 9, "14:36", "14:36", "PITESTI"),        # unrelated
])
def test_distinct_trains_are_not_near_duplicates(a, b, ta, tb, st_b):
    assert not _near_dup((a, ta, "PITESTI", "PITESTI"), (b, tb, st_b, st_b))


@pytest.mark.parametrize("t1,t2,dup", [
    ("01:10", "01:49", True), ("03:38", "08:58", True), ("03:00", "08:00", True),
    ("06:52", "05:52", True), ("01:10", "12:34", False), ("01:10", "23:45", False)])
def test_same_train_and_station_with_a_misread_time_digit_is_one_service(t1, t2, dup):
    a = (10101, t1, "AEROPORT H COANDA", "AEROPORT H COANDA")
    b = (10101, t2, "AEROPORT H COANDA", "AEROPORT H COANDA")
    assert _near_dup(a, b) is dup


def test_station_spacing_does_not_make_two_stations():
    assert _fold_station("KIEV - CHISINAU") == _fold_station("KIEV -CHISINAU")
    assert _same_station("KIEV - CHISINAU", "", "KIEV -CHISINAU", "")
    assert _near_dup((401, "06:38", "KIEV - CHISINAU", "KIEV - CHISINAU"),
                     (4011, "06:38", "KIEV -CHISINAU", "KIEV -CHISINAU"))
    assert not _same_station("", "", "", "")  # nothing read is no station


def test_a_second_misread_of_the_row_never_becomes_its_own_service(store):
    real = R(9209, "14:36")
    store.ingest(frame([real]), at(0))
    for m, no in enumerate((92011, 9209, 92011, 9209, 9209, 92011), 1):
        store.ingest(frame([R(no, "14:36")]), at(m))
    assert svcs(store) == [(9209, "14:36", "listed")]


def test_lost_leading_digits_go_to_the_majority_service(store):
    # RE 10157 read "0157"/"157" for five frames under a reflection (25.10)
    store.ingest(frame([R(10157, "19:00", "ROSIORI NORD")]), at(0))
    for m, no in enumerate((10157, 157, 157, 10157, 157, 10157), 1):
        store.ingest(frame([R(no, "19:00", "ROSIORI NORD")]), at(m))
    rows = store._conn.execute(
        "SELECT train_no, status FROM services WHERE station='ROSIORI NORD'").fetchall()
    assert [tuple(r) for r in rows] == [(10157, "listed")]


def test_two_variant_numbers_read_in_one_frame_stay_two_trains(store):
    a, b = R(9209, "14:36"), R(92011, "14:36")
    for m in range(5):
        store.ingest(frame([a, b] if m else [a]), at(m))
    assert {r[0] for r in svcs(store)} == {9209, 92011}


def test_time_misread_of_the_same_train_is_one_service(store):
    store.ingest(frame([R(10101, "01:10", "AEROPORT H COANDA")]), at(0))
    for m, t in enumerate(("01:49", "01:10", "01:49", "01:10"), 1):
        store.ingest(frame([R(10101, t, "AEROPORT H COANDA")]), at(m))
    rows = store._conn.execute(
        "SELECT sched_time FROM services WHERE train_no=10101").fetchall()
    assert [r[0] for r in rows] == ["01:10"]


def _no(store, sid):
    return store._conn.execute("SELECT train_no FROM services WHERE id=?", (sid,)).fetchone()[0]


def test_a_longer_stored_misread_is_replaced_by_an_overwhelming_vote(store):
    """92011 was read first, then 9209 in every frame: the shorter number wins once it
    is 9 of the last 10 readings (no rename to fewer digits on a weak majority)."""
    store.ingest(frame([R(92011, "14:36")]), at(0))
    sid = store._conn.execute("SELECT id FROM services WHERE train_no=92011").fetchone()[0]
    for m in range(1, 6):  # a 70% share is enough for MORE digits, not for fewer
        store.ingest(frame([R(9209, "14:36")]), at(m))
    assert _no(store, sid) == 92011
    for m in range(6, 12):
        store.ingest(frame([R(9209, "14:36")]), at(m))
    assert _no(store, sid) == 9209


# -- 2. stații ------------------------------------------------------------------------------

@pytest.mark.parametrize("read,want", [
    ("KIEV -CHISINAU", "KIEV - CHISINAU"), ("KIEV - CHISINAU", "KIEV - CHISINAU"),
    ("KIEV -CHISINAU ", "KIEV - CHISINAU"), ("CHISINAU -KIEV", "CHISINAU-KIEV"),
    ("CHISINAU-KIEV", "CHISINAU-KIEV"),
    ("VATRA DORNEI BA", "VATRA DORNEI BAI"), ("VATRA DORNEI BAI", "VATRA DORNEI BAI"),
    ("VATRA DORNEI", "VATRA DORNEI"),
])
def test_station_aliases(read, want):
    name, score = canonical.canonical_station(read, (), preferred=canonical.seed_stations())
    assert name == want and score >= canonical.DEFAULT_THRESHOLD


@pytest.mark.parametrize("read", ["CLUJ NAPOCA EST", "PITESTI SUD"])
def test_other_names_are_not_completed_into_a_known_station(read):
    name, score = canonical.canonical_station(read, (), preferred=canonical.seed_stations())
    assert name == read and score < canonical.DEFAULT_THRESHOLD


def test_a_one_word_name_is_never_completed():
    name, _ = canonical.canonical_station("IAS", (), preferred=canonical.seed_stations())
    assert name == "IAS"


# -- 3. ordinea orelor pe panou ---------------------------------------------------------------

def test_out_of_order_finds_only_the_lines_in_no_longest_run():
    assert order.out_of_order(["06:10", "06:17", "05:28", "06:30", "06:45"]) == [2]
    # a tie (either of two lines could be the wrong one) condemns neither
    assert order.out_of_order(["06:17", "05:28", "06:30"]) == []
    assert order.out_of_order(["06:17", "06:30", "06:45", "07:10"]) == []
    # a misread neighbour does not condemn the lines around it: only 07:52 is out
    assert order.out_of_order(["06:50", "07:52", "07:10", "07:20", "07:30"]) == [1]
    assert order.out_of_order(["06:50", "07:10"]) == []  # too short to tell


def test_order_check_wraps_at_midnight():
    assert order.out_of_order(["23:40", "23:55", "00:10", "00:30"]) == []


def _entry(board, j, no, t, conf=0.9):
    row = R(no, t, board=board, confidence=conf)
    return {"board": board, "row_index": j, "row": row,
            "fields": {"time": {"raw": t, "norm": t, "conf": 90.0}}}


def test_a_time_out_of_order_is_repaired_by_one_confusable_digit_when_unique():
    # "05:52" between 06:45 and 07:10: 5 -> 6 puts it back (06:52); no other single
    # confusable change fits
    es = [_entry("departure", j, 100 + j, t) for j, t in
          enumerate(["06:32", "06:45", "05:52", "07:10", "07:20"])]
    assert order.check_time_order(es) == 1
    e = es[2]
    assert e["row"].sched_time == "06:52" and e["row"].uncertain
    assert e["row"].confidence <= order.REPAIRED_CONFIDENCE
    assert e["fields"]["time"]["check"] == "order_fixed"
    assert e["fields"]["time"]["seen"] == "05:52" and e["fields"]["time"]["norm"] == "06:52"
    assert all(not x["row"].uncertain for k, x in enumerate(es) if k != 2)


def test_a_time_out_of_order_without_a_unique_repair_only_loses_confidence():
    es = [_entry("departure", j, 100 + j, t) for j, t in
          enumerate(["06:10", "06:45", "09:41", "06:50", "07:10"])]
    assert order.check_time_order(es) == 1
    e = es[2]
    assert e["row"].sched_time == "09:41"  # never a guess
    assert e["row"].confidence <= order.SUSPECT_CONFIDENCE and e["row"].uncertain
    assert e["fields"]["time"]["check"] == "order"


def test_panels_are_checked_separately_and_ordered_panels_are_untouched():
    es = [_entry("arrival", j, 100 + j, t) for j, t in enumerate(["06:10", "06:20", "06:30"])]
    es += [_entry("departure", j, 200 + j, t) for j, t in enumerate(["09:10", "09:15", "05:20", "09:30", "09:40"])]
    assert order.check_time_order(es) == 1
    assert not any(e["row"].uncertain for e in es[:3])
    assert es[5]["row"].uncertain and es[5]["fields"]["time"]["check"] == "order"


def test_low_confidence_time_does_not_start_a_service_alone(store):
    from app.store import CONFIRM_CONFIDENCE
    assert order.SUSPECT_CONFIDENCE < CONFIRM_CONFIDENCE
    assert order.REPAIRED_CONFIDENCE < CONFIRM_CONFIDENCE
    store.ingest(frame(), at(0))
    store.ingest(frame([R(9209, "05:52", confidence=order.SUSPECT_CONFIDENCE)]), at(1))
    assert svcs(store) == []  # waits for a second consecutive reading
    store.ingest(frame([R(9209, "05:52", confidence=order.SUSPECT_CONFIDENCE)]), at(2))
    assert len(svcs(store)) == 1


# -- 4. întârzieri multiplu de 5 ----------------------------------------------------------------

class _Fake:
    def __init__(self, glyphs):
        from tests.test_ocr13 import _cross
        self._g = [(c, s, mg, _cross() if c == "+" else np.ones((32, 32), np.float32), False)
                   for c, s, mg in glyphs]

    def glyphs(self, cell, allowed):
        return self._g


CELL = np.full((30, 90), 255, np.uint8)
GOOD = (0.9, 0.2)


@pytest.mark.parametrize("digs,text", [("46", "+46"), ("26", "+26"), ("6", "+6"),
                                       ("36", "+36"), ("23", "+23"), ("1", "+1")])
def test_delay_not_a_multiple_of_five_is_unread(digs, text):
    g = [("+", *GOOD)] + [(d, *GOOD) for d in digs]
    out, conf, why = _delay(CELL, (text, 90.0), _Fake(g))
    assert (out, conf, why) == (DELAY_UNREAD, None, "not_step")
    assert parse_delay(out) is None  # missing, never 0 and never a guess


@pytest.mark.parametrize("digs", ["5", "10", "45", "55", "65", "95"])
def test_delay_multiples_of_five_stay_read(digs):
    g = [("+", *GOOD)] + [(d, *GOOD) for d in digs]
    out, _, why = _delay(CELL, ("+" + digs, 90.0), _Fake(g))
    assert (out, why) == ("+" + digs, None) and int(digs) % DELAY_STEP == 0


def test_tesseract_only_reading_is_checked_too():
    assert _delay(CELL, ("+46", 88.0), None)[::2] == (DELAY_UNREAD, "not_step")
    assert _delay(CELL, ("+45", 88.0), None) == ("+45", 88.0, None)
    assert _delay(CELL, ("", None), _Fake([]))[0] == ""  # on time stays on time


# -- 1b. cauza în OCR: cifra tăiată de rost (fixture live) ----------------------------------------

def _rows(name):
    return read_board(capture(FIX / name).read_bytes())


def test_seam_cut_digit_with_a_gap_of_a_few_px_is_one_glyph():
    """9209 -> 92011: the joint's dark seam (3 px) cut the last "9" into a left part and
    a stem; two real digits never fit one pitch."""
    def ring(x):
        return [(x, 6, x + 24, 10), (x, 36, x + 24, 40), (x, 6, x + 5, 40),
                (x + 19, 6, x + 24, 40)]

    def cell(boxes, h=42, w=160):
        c = np.full((h, w), 255, np.uint8)
        for x0, y0, x1, y1 in boxes:
            c[y0:y1, x0:x1] = 0
        return c

    left = [(104, 8, 116, 29), (105, 32, 116, 41)]  # bowl + tail of the "9", seam below
    for gap in (2, 3, 4):
        right = (116 + gap, 8, 116 + gap + 9, 41)
        spans = [s for _, s, _ in digits.segment_spans(
            cell(ring(14) + ring(44) + ring(74) + left + [right]))]
        assert len(spans) == 4 and spans[-1][0] == 104, (gap, spans)
    # two real "1"s next to each other are never one glyph: a pitch apart
    ones = [(104, 6, 113, 40), (134, 6, 143, 40)]
    assert len(digits.segment_spans(cell(ring(14) + ring(44) + ones))) == 4


def test_the_live_frame_with_the_seam_cut_nine_reads_9209():
    rows = _rows("seam_9209.jpg")
    dep = [r for r in rows if r.board == "departure"]
    assert any(r.train_no == 9209 and r.station == "PITESTI" and r.sched_time == "14:36"
               for r in dep), [(r.train_no, r.sched_time) for r in dep]
    assert not any(r.train_no in (92011, 209) for r in dep)


def test_the_live_frames_of_the_other_seam_cuts_read_the_real_numbers():
    arr = {(r.train_no, r.station) for r in _rows("seam_7938.jpg") if r.board == "arrival"}
    assert (7938, "AEROPORT H COANDA") in arr and not any(n == 79311 for n, _ in arr)
    dep = {r.train_no for r in _rows("seam_5019.jpg") if r.board == "departure"}
    assert 5019 in dep and not dep & {50111, 50191}


def test_confirmed_accepts_a_reading_that_dropped_one_trusted_glyph():
    class M:
        def __init__(self, g):
            self._g = g

        def glyphs(self, cell, allowed):
            return [(c, s, mg, None, False) for c, s, mg in self._g]
    good, weak = (0.85, 0.2), (0.75, 0.02)
    m = M([("9", *good), ("2", *good), ("0", *good), ("9", *weak)])
    cell = np.zeros((4, 4), np.uint8)
    assert _confirmed(m, cell, "no", "209")      # Tesseract dropped the first, trusted "9"
    assert not _confirmed(m, cell, "no", "208")  # ...and read the doubtful one differently
    assert not _confirmed(m, cell, "no", "29")   # two glyphs short: no
    last_one = M([("7", *good), ("9", *good), ("1", *good), ("1", *good)])
    assert _confirmed(last_one, cell, "no", "791")  # the old rule (last "1" cut) still holds
    shifted = M([("7", *good), ("9", *good), ("1", *weak), ("1", *weak), ("1", *weak)])
    assert not _confirmed(shifted, cell, "no", "7919")  # never a shifted alignment


# -- Beta 1.22b: întârziere recuperată din textul văzut, ora repetată (DST) ------------------------

def _dentry(no, check=None, seen=None, norm=None, t="12:00"):
    f = {"raw": "", "norm": norm, "conf": None}
    if check:
        f.update(check=check, seen=seen)
    fields = {n: {"raw": ""} for n in ("type", "no", "station", "operator", "time", "platform")}
    return {"board": "arrival", "row_index": 0, "fields": {**fields, "delay": f},
            "raw_text": "", "row": R(no, t, board="arrival", delay_min=0, delay_read=check is None)}


def test_hidden_plus_is_recovered_from_the_text_seen_over_enough_frames():
    from app.ocr.reader import SEEN_MIN, DelayVotes
    v, got = DelayVotes(), []
    for k in range(SEEN_MIN + 2):
        e = _dentry(11500, "no_plus", "15")
        v.apply([e])
        got.append(e["row"].delay_min if e["row"].delay_read else None)
    assert got[:SEEN_MIN - 1] == [None] * (SEEN_MIN - 1)  # not before SEEN_MIN agree
    assert got[SEEN_MIN - 1:] == [15] * 3
    assert e["fields"]["delay"]["norm"] == 15 and "check" not in e["fields"]["delay"]


def test_recovery_needs_a_multiple_of_five_and_not_below_the_last_read_delay():
    from app.ocr.reader import SEEN_MIN, DelayVotes
    v = DelayVotes()
    for _ in range(SEEN_MIN + 2):  # "46" is no delay of this board
        e = _dentry(1650, "no_plus", "46")
        v.apply([e])
    assert not e["row"].delay_read
    v = DelayVotes()
    v.apply([_dentry(1094, norm=25)])  # last real reading: +25
    for _ in range(SEEN_MIN + 2):  # a hidden "+" showing 15 cannot lower it
        e = _dentry(1094, "no_plus", "15")
        v.apply([e])
    assert not e["row"].delay_read
    v = DelayVotes()
    for k in range(SEEN_MIN + 2):  # mixed readings never reach SEEN_MIN
        e = _dentry(1628, "glare", "15" if k % 2 else "25")
        v.apply([e])
    assert not e["row"].delay_read
    v = DelayVotes()
    for _ in range(SEEN_MIN + 2):  # glare: both readers may agree on a wrong digit: no vote
        e = _dentry(1628, "glare", "15")
        v.apply([e])
    assert not e["row"].delay_read


def test_sched_at_in_the_repeated_hour_follows_the_observed_moment():
    from app import journeys
    ref = datetime(2026, 10, 25, 3, 20, tzinfo=ZoneInfo("Europe/Bucharest")).replace(fold=1)
    s = journeys.sched_at("2026-10-25", "03:10", ref)
    assert s.utcoffset() == timedelta(hours=2) and s <= ref  # the second 03:10 (+02:00)
    assert journeys.sched_at("2026-10-25", "03:10").utcoffset() == timedelta(hours=3)
    early = datetime(2026, 10, 25, 0, 5, tzinfo=ZoneInfo("UTC"))  # 03:05 +03:00
    assert journeys.sched_at("2026-10-25", "03:10", early).utcoffset() == timedelta(hours=3)
    assert journeys.sched_at("2026-10-26", "03:10", ref).utcoffset() == timedelta(hours=2)
    # a journey of 03:10 read at 03:20 on the second pass is not "gone before estimated"
    row = {"service_date": "2026-10-25", "sched_time": "03:10", "status": "gone",
           "last_delay": 0, "delay_read_at": "2026-10-25T03:19:00+02:00",
           "gone_at": "2026-10-25T03:20:00+02:00", "appeared_at": None}
    assert journeys.result(row)["state"] == "confirmed"
