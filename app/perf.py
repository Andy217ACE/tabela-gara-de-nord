# © 2026 Andy217Ace
"""In-process timings for the „Sistem” page: latency per /api route and duration of each
OCR cycle. In memory only (one uvicorn worker), reset on restart.

Routes are keyed by their template (``/api/trains/{train_no}``), never by the raw path,
so no IDs or query strings are kept and the number of keys is bounded by the app's routes.
Each key keeps at most MAX_SAMPLES samples and only the last WINDOW_S seconds count.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque

MAX_SAMPLES = 1000  # per route template: bounded memory whatever the traffic
OCR_SAMPLES = 500   # OCR cycles (about 8 h at one new image per minute)
WINDOW_S = 86400    # only the last 24 h count

_lock = threading.Lock()
_routes: dict[str, deque] = {}
_ocr: deque = deque(maxlen=OCR_SAMPLES)


def percentile(sorted_vals: list[float], q: float) -> float | None:
    """Nearest-rank percentile of an already sorted list (q in 0..1); None when empty."""
    if not sorted_vals:
        return None
    return sorted_vals[max(0, math.ceil(q * len(sorted_vals)) - 1)]


def record_route(template: str, ms: float, now: float | None = None) -> None:
    sample = (time.time() if now is None else now, ms)
    with _lock:
        dq = _routes.get(template)
        if dq is None:
            dq = _routes[template] = deque(maxlen=MAX_SAMPLES)
        dq.append(sample)


def record_ocr_cycle(ms: float, now: float | None = None) -> None:
    with _lock:
        _ocr.append((time.time() if now is None else now, ms))


def reset() -> None:
    with _lock:
        _routes.clear()
        _ocr.clear()


def _summary(samples: list[tuple[float, float]], now: float) -> dict:
    vals = sorted(ms for ts, ms in samples if now - ts <= WINDOW_S)
    r = lambda v: None if v is None else round(v, 1)  # noqa: E731
    return {"n": len(vals), "p50_ms": r(percentile(vals, .5)), "p95_ms": r(percentile(vals, .95))}


PRIVATE_ROUTES = ("/api/admin", "/api/push", "/api/follow")


def routes_summary(*, include_admin: bool = False, now: float | None = None) -> list[dict]:
    """[{route, n, p50_ms, p95_ms}], busiest first. Admin routes, and push/follow ones (their
    counts would reveal usage volumes), only with `include_admin`."""
    now = time.time() if now is None else now
    with _lock:
        items = [(k, list(v)) for k, v in _routes.items()
                 if include_admin or not k.startswith(PRIVATE_ROUTES)]
    out = [{"route": k} | _summary(v, now) for k, v in items]
    return sorted((x for x in out if x["n"]), key=lambda x: -x["n"])


def ocr_summary(now: float | None = None) -> dict:
    """{n, p50_ms, p95_ms, last_ms} of the OCR cycles in the window."""
    now = time.time() if now is None else now
    with _lock:
        samples = list(_ocr)
    out = _summary(samples, now)
    out["last_ms"] = round(samples[-1][1], 1) if samples else None
    return out
