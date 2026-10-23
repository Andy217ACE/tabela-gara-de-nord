# © 2026 Andy217Ace
"""Field accuracy of the board reader against a hand-labelled truth set.

The truth set (``tests/fixtures/ocr_truth/truth.json``) holds, per real capture and
per board, the 12 lines as shown on the board, checked by eye on the image (never a
consensus of the database):

    {"frames": {"<capture>": {"arrival": [{"no": 3021, "time": "05:28", "type": "R",
                                           "delay": 0, "platform": 8,
                                           "station": "BRASOV", "operator": "CFR CALATORI"},
                                          ...12 lines], "departure": [...]}}}

A field labelled ``"?"`` (or missing) is not scored: it cannot be read on the image
either (glare, motion blur). ``None`` means the cell is blank on the board (no
platform yet); ``delay`` 0 means no delay shown.

Each scored cell is ``ok`` (the reader gives the label), ``unread`` (the reader gives
None where the board shows a value: a missing value, never a guess) or ``wrong`` (any
other value, including a value invented for a blank cell). ``wrong`` is the error that
matters: an unread value is honest, a wrong one is published.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

FIELDS = ("no", "time", "type", "platform", "delay", "station", "operator")
SKIP = "?"


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def lines_of(debug: list[dict]) -> dict[tuple[str, int], dict]:
    """{(board, line): {field: value as read}} from ``read_board_debug``'s debug list."""
    return {(d["board"], d["row_index"]): {f: d["fields"][f]["norm"] for f in FIELDS}
            for d in debug}


def score(truth: dict, predictions: dict[str, dict[tuple[str, int], dict]]) -> dict:
    """Per field: Counter(ok/unread/wrong) and the list of (frame, board, line, label, read)
    of the cells that are not ok. `predictions`: {frame: lines_of(debug)}; a frame or
    line missing from the predictions counts as unread on every field."""
    counts = {f: collections.Counter() for f in FIELDS}
    misses: dict[str, list] = {f: [] for f in FIELDS}
    for frame, boards in truth["frames"].items():
        got_frame = predictions.get(frame, {})
        for board, lines in boards.items():
            for i, label in enumerate(lines):
                got = got_frame.get((board, i), {})
                for f in FIELDS:
                    exp = label.get(f, SKIP)
                    if exp == SKIP:
                        continue
                    val = got.get(f)
                    if val == exp:
                        counts[f]["ok"] += 1
                        continue
                    kind = "unread" if val is None else "wrong"
                    counts[f][kind] += 1
                    misses[f].append((frame, board, i, exp, val))
    return {"counts": counts, "misses": misses}


def table(result: dict) -> list[str]:
    out = [f"{'camp':<9} {'n':>4} {'ok':>4} {'necitit':>7} {'gresit':>6} {'acuratete':>9}"]
    for f in FIELDS:
        c = result["counts"][f]
        n = c["ok"] + c["unread"] + c["wrong"]
        acc = f"{100 * c['ok'] / n:.1f}%" if n else "-"
        out.append(f"{f:<9} {n:>4} {c['ok']:>4} {c['unread']:>7} {c['wrong']:>6} {acc:>9}")
    return out
