# © 2026 Andy217Ace
"""„Sistem” page data: is the panel alive, when was the last good reading, OCR health, disk
and database size. `collect_status` feeds GET /api/system (public, minimal fields) and
GET /api/admin/system (same fields plus details). Nothing here exposes file paths, tokens,
environment variables or tracebacks: an error is a short code only.

A missing value is reported as None ("necunoscut" on the page), never as 0.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone

from app import perf
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


_tess_info: dict | None = None  # cached on first call: the installed binary does not change while running
_UPDATES_FILE = "/var/lib/update-notifier/updates-available"  # written by Ubuntu's update-notifier


def tesseract_info(cmd: str) -> dict:
    """Tesseract version and loaded traineddata languages, from `tesseract --version` and
    `--list-langs` (one call each, cached). Unavailable -> None / []."""
    global _tess_info
    if _tess_info is None:
        exe = cmd if os.path.isabs(cmd) else (shutil.which(cmd) or cmd)

        def run(arg):
            try:
                p = subprocess.run([exe, arg], capture_output=True, text=True, timeout=5)
                return (p.stdout or p.stderr) if p.returncode == 0 else ""
            except (OSError, subprocess.SubprocessError):
                return ""

        m = re.search(r"tesseract\s+v?(\d[\w.\-]*)", run("--version"))
        langs = [x.strip() for x in run("--list-langs").splitlines()[1:] if x.strip()]
        info = {"version": m.group(1) if m else None, "langs": langs}
        if not info["version"]:
            return info   # failed probe (missing binary, timeout): not cached, retried on the next call
        _tess_info = info
    return _tess_info


def pending_security_updates() -> int | None:
    """Security updates waiting, from update-notifier's text file ("N updates can be applied
    immediately" / "N of these updates are security updates"); None if the file is missing
    or unparseable. No apt call, no sudo."""
    try:
        with open(_UPDATES_FILE, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    m = re.search(r"(\d+) of these updates are (?:standard )?security", text)
    if m:
        return int(m.group(1))
    return 0 if "updates can be applied" in text or "updates can be installed" in text else None


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


QUALITY_TTL_S = 300  # the 7-day scan is cached: the page may be reloaded often
_quality_cache: tuple[object, float, dict] | None = None  # (store, monotonic time, result)


def _pct(part: int, whole: int) -> float | None:
    return round(100.0 * part / whole, 1) if whole else None


def ocr_quality(store, now: datetime) -> dict:
    """Aggregate reading quality over the last 24 h and 7 days: distinct frames (captures)
    and the share read without error; read rows (observations) and the share validated
    `ok`. Counts only, nothing per train or per row. Cached QUALITY_TTL_S seconds."""
    global _quality_cache
    c = _quality_cache
    if c and c[0] is store and time.monotonic() - c[1] < QUALITY_TTL_S:
        return c[2]
    out = {}
    for key, delta in (("h24", timedelta(hours=24)), ("d7", timedelta(days=7))):
        # timestamps are stored as UTC ISO strings: a string comparison is a time comparison
        since = (now - delta).astimezone(timezone.utc).isoformat(timespec="seconds")
        with store._lock:
            frames, frames_ok = store._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(ok != 0), 0) FROM captures WHERE captured_at >= ?",
                (since,)).fetchone()
            rows, rows_ok = store._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(validation_state = 'ok'), 0) FROM observations"
                " WHERE observed_at >= ?", (since,)).fetchone()
        out[key] = {"frames": frames, "frames_ok_pct": _pct(frames_ok, frames),
                    "rows": rows, "rows_ok_pct": _pct(rows_ok, rows)}
    _quality_cache = (store, time.monotonic(), out)
    return out


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
        "ocr_quality": ocr_quality(store, now),
        "perf": {"window_s": perf.WINDOW_S, "routes": perf.routes_summary(include_admin=admin),
                 "ocr_cycle": perf.ocr_summary()},
    }
    if admin:  # versions and pending updates stay admin-only: public, they'd be a target list
        out["tesseract"] = tesseract_info(getattr(settings, "tesseract_cmd", "tesseract"))
        out["security_updates"] = pending_security_updates()
        snap = ocr_stats.snapshot()
        out["poller"]["last_error_age_s"] = None if err is None else round(now.timestamp() - err[1])
        out["ocr"]["expected_rows"] = snap["expected_rows"]
        out["ocr_window"] = snap["window"]
        out["disk"]["total_gb"] = disk["total_gb"]
    return out
