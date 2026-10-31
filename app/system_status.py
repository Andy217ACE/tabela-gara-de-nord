# © 2026 Andy217Ace
"""„Sistem” page data: is the panel alive, when was the last good reading, OCR health, disk
and database size. `collect_status` feeds GET /api/system (public, minimal fields) and
GET /api/admin/system (same fields plus details). Nothing here exposes file paths, tokens,
environment variables or tracebacks: an error is a short code only.

A missing value is reported as None ("necunoscut" on the page), never as 0.
"""
from __future__ import annotations

import os
import shutil
import time
from datetime import datetime

from app.ocr import stats as ocr_stats
from app.store import SCHEMA_VERSION
from app.version import __version__

STALE_PANEL_S = 600  # no good reading for this long: the panel is "Date vechi"
OCR_MIN_FRAMES = 10  # fewer frames in the last hour: the unread rate is not meaningful yet
ERROR_CODES = ("fetch", "ocr", "store")  # what the poller reports; anything else -> "other"

_STARTED = time.time()
_last_error: tuple[str, float] | None = None  # (code, unix time) of the latest failure


def record_error(code: str, ts: float) -> None:
    """Remember the latest poller failure (unix time `ts`) as a short code: no message,
    no traceback."""
    global _last_error
    _last_error = (code if code in ERROR_CODES else "other", ts)


def last_error() -> tuple[str, float] | None:
    return _last_error


def panel_state(age_s: float | None) -> str:
    """"live", "date_vechi" (older than STALE_PANEL_S) or "necunoscut" (never read)."""
    if age_s is None:
        return "necunoscut"
    return "live" if age_s <= STALE_PANEL_S else "date_vechi"


def _disk(db_path: str) -> dict:
    try:
        usage = shutil.disk_usage(os.path.dirname(os.path.abspath(db_path)))
    except OSError:
        return {"free_gb": None, "total_gb": None}
    return {"free_gb": round(usage.free / 1024 ** 3, 1), "total_gb": round(usage.total / 1024 ** 3, 1)}


def _mb(path: str) -> float | None:
    try:
        return round(os.path.getsize(path) / 1024 ** 2, 1)
    except OSError:
        return None


def _db(db_path: str) -> dict:
    # no -wal file is the normal state after a checkpoint: that is 0 MB, not a missing value
    wal = _mb(db_path + "-wal")
    return {"size_mb": _mb(db_path), "wal_mb": 0.0 if wal is None else wal}


def collect_status(store, settings, now: datetime, *, admin: bool = False) -> dict:
    """The status payload (see module doc). `admin=True` adds the details."""
    age = store.last_ok_age(now)
    rate, frames = ocr_stats.unread_rate_1h()
    err = last_error()
    db_path = str(settings.db_path)
    disk = _disk(db_path)
    out = {
        "version": __version__,
        "schema": SCHEMA_VERSION,
        "uptime_s": int(time.time() - _STARTED),
        "stare": panel_state(age),
        "stale_after_s": STALE_PANEL_S,
        "poller": {
            "last_ok_age_s": None if age is None else round(age),
            "last_error": err[0] if err else None,
        },
        "ocr": {
            "unread_rate_1h": None if rate is None else round(rate, 3),
            "n": frames,
            "insufficient": frames < OCR_MIN_FRAMES,
        },
        "disk": {"free_gb": disk["free_gb"]},
        "db": _db(db_path),
    }
    if admin:
        snap = ocr_stats.snapshot()
        out["poller"]["last_error_age_s"] = None if err is None else round(now.timestamp() - err[1])
        out["ocr"]["expected_rows"] = snap["expected_rows"]
        out["ocr_window"] = snap["window"]
        out["disk"]["total_gb"] = disk["total_gb"]
    return out
