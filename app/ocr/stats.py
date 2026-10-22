# © 2026 Andy217Ace
"""In-memory OCR statistics: rows per panel and re-reads of the recent frames.

``reader.read_board_debug`` records one summary per frame; ``/api/health`` and the
admin page show `snapshot()`. Kept in memory only (reset on restart): the per-line
detail is stored with every capture (observations).
"""
from __future__ import annotations

import threading
from collections import deque

from app.ocr.preprocess import EXPECTED_ROWS

WINDOW = 60  # frames (about one hour: one new image per minute)

_lock = threading.Lock()
_frames: deque[dict] = deque(maxlen=WINDOW)


def record(summary: dict) -> None:
    with _lock:
        _frames.append(summary)


def reset() -> None:
    with _lock:
        _frames.clear()


def _full(f: dict) -> bool:
    boards = f.get("boards") or {}
    return bool(boards) and all(b["rows"] == EXPECTED_ROWS for b in boards.values())


def snapshot() -> dict:
    """{expected_rows, last: last frame summary or None, window: aggregates}."""
    with _lock:
        frames = list(_frames)
    n = len(frames)
    durs = sorted(f["duration_ms"] for f in frames)
    return {
        "expected_rows": EXPECTED_ROWS,
        "last": frames[-1] if frames else None,
        "window": {
            "frames": n,
            "full_frames": sum(_full(f) for f in frames),
            "frames_retried": sum(f["retried"] > 0 for f in frames),
            "lines_retried": sum(f["retried"] for f in frames),
            "lines_recovered": sum(f["recovered"] for f in frames),
            "duration_ms_max": durs[-1] if durs else None,
            "duration_ms_p50": durs[n // 2] if durs else None,
            "retry_ms_max": max((f["retry_ms"] for f in frames), default=None),
        },
    }
