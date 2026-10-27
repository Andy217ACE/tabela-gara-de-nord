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
