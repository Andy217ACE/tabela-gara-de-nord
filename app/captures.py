# © 2026 Andy217Ace
"""Capture images on disk: settings, safe paths, retention, stats, admin reads, overlay.

Only image FILES expire (after CAPTURE_RETENTION_DAYS, default 7); the `captures`
and `observations` rows are kept forever, with `path` set to NULL once the file is
gone. Nothing outside CAPTURE_DIR is ever read or deleted: every stored path is
re-validated (relative, no "..", resolved inside the root) before use.

Raw CFR images are private (admin only) and never redistributed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import cv2
import numpy as np

from app.observations import parse_line_version

log = logging.getLogger(__name__)

SERVER_DATA_DIR = "/var/lib/tabela"
RETENTION_INTERVAL_S = 24 * 3600
RETENTION_FIRST_DELAY_S = 60
LIST_MAX = 200


@dataclass(frozen=True)
class CaptureSettings:
    enabled: bool
    dir: str
    retention_days: int


def _default_dir() -> str:
    return (os.path.join(SERVER_DATA_DIR, "captures") if os.path.isdir(SERVER_DATA_DIR)
            else os.path.join("data", "captures"))


def capture_settings() -> CaptureSettings:
    """CAPTURE_ENABLED (1), CAPTURE_DIR (/var/lib/tabela/captures on the server,
    data/captures elsewhere), CAPTURE_RETENTION_DAYS (7; 0 keeps no image)."""
    enabled = os.environ.get("CAPTURE_ENABLED", "1").strip().lower() not in (
        "0", "false", "no", "off")
    try:
        days = int(os.environ.get("CAPTURE_RETENTION_DAYS", "7"))
    except ValueError:
        days = 7
    return CaptureSettings(enabled, os.environ.get("CAPTURE_DIR") or _default_dir(),
                           max(0, min(days, 3650)))


def safe_path(root: str | os.PathLike, rel: str | None) -> Path | None:
    """Absolute path of `rel` under `root`, or None if it could escape the root."""
    if not rel or not isinstance(rel, str) or "\x00" in rel or "\\" in rel:
        return None
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or (p.parts and ":" in p.parts[0]):
        return None
    base = Path(root).resolve()
    full = (base / Path(*p.parts)).resolve()
    if full == base or not full.is_relative_to(base):
        return None
    return full


def _now() -> datetime:
    return datetime.now(timezone.utc)


# -- retention --------------------------------------------------------------------

def run_retention(store, root: str | os.PathLike, retention_days: int, *,
                  now: datetime | None = None, dry_run: bool = False) -> dict:
    """Delete image files of captures older than `retention_days`; keep the rows.

    Returns {"candidates", "removed", "missing", "skipped", "bytes"}. Idempotent;
    `dry_run` only counts. Unsafe stored paths are never followed (their DB
    reference is cleared, the filesystem is not touched).
    """
    cutoff = ((now or _now()) - timedelta(days=retention_days)).isoformat(timespec="seconds")
    with store._lock:
        found = store._conn.execute(
            "SELECT id, path FROM captures WHERE path IS NOT NULL AND captured_at < ?"
            " ORDER BY id", (cutoff,)).fetchall()
    out = {"candidates": len(found), "removed": 0, "missing": 0, "skipped": 0, "bytes": 0}
    if dry_run:
        return out
    base = Path(root).resolve()
    for cid, rel in found:
        full = safe_path(root, rel)
        if full is None:
            out["skipped"] += 1
            log.warning("capture %s: unsafe stored path ignored", cid)
        else:
            try:
                size = full.stat().st_size
                full.unlink()
                out["removed"] += 1
                out["bytes"] += size
                _prune_dirs(full.parent, base)
            except FileNotFoundError:
                out["missing"] += 1
            except OSError:
                log.warning("capture %s: could not delete image", cid, exc_info=True)
                continue  # keep the reference; retried next run
        with store._lock:
            store._conn.execute("UPDATE captures SET path=NULL WHERE id=?", (cid,))
    return out


def _prune_dirs(d: Path, base: Path) -> None:
    """Remove now-empty day/month/year directories, never `base` or above."""
    while d != base and d.is_relative_to(base):
        try:
            d.rmdir()
        except OSError:
            return
        d = d.parent


async def retention_loop(store, settings: CaptureSettings, stop: asyncio.Event, *,
                         first_delay: float = RETENTION_FIRST_DELAY_S,
                         interval: float = RETENTION_INTERVAL_S) -> None:
    """Daily retention; errors are logged and never end the loop."""
    delay = first_delay
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
            return
        except asyncio.TimeoutError:
            pass
        delay = interval
        try:
            res = await asyncio.to_thread(run_retention, store, settings.dir,
                                          settings.retention_days)
            if res["candidates"]:
                log.info("capture retention: %s", res)
        except Exception:
            log.exception("capture retention failed")


def capture_stats(store) -> dict:
    """Images still on disk (per the DB): count, bytes, oldest capture time."""
    with store._lock:
        n, size, oldest = store._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(bytes), 0), MIN(captured_at) FROM captures"
            " WHERE path IS NOT NULL").fetchone()
        total = store._conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
    return {"count": n, "bytes": size, "oldest": oldest, "captures_total": total}


# -- admin reads ----------------------------------------------------------------------

_CAP_COLS = ("id, captured_at, last_seen_at, image_hash, path, width, height, bytes, ok,"
             " n_rows, processing_version, duration_ms, error, expires_at")


def _cap(r) -> dict:
    return {"id": r["id"], "captured_at": r["captured_at"], "last_seen_at": r["last_seen_at"],
            "hash8": (r["image_hash"] or "")[:8], "has_image": r["path"] is not None,
            "width": r["width"], "height": r["height"], "bytes": r["bytes"],
            "ok": bool(r["ok"]), "n_rows": r["n_rows"],
            "processing_version": r["processing_version"],
            "duration_ms": r["duration_ms"], "error": r["error"],
            "expires_at": r["expires_at"]}


_BOARD_KEYS = (("arrival", "arrivals"), ("departure", "departures"))


def _board_counts(conn, ids: list[int]) -> dict[int, dict]:
    """Per capture and panel: OCR lines, rows read (a train), empty/unread lines and
    re-read lines (recovered = re-read with success). From the observations."""
    out: dict[int, dict] = {i: {k: {"lines": 0, "rows": 0, "empty": 0, "unread": 0,
                                   "retried": 0, "recovered": 0} for _, k in _BOARD_KEYS}
                            for i in ids}
    if not ids:
        return out
    marks = ",".join("?" * len(ids))
    for cid, board, state, pv in conn.execute(
            f"SELECT capture_id, board, validation_state, processing_version"
            f" FROM observations WHERE capture_id IN ({marks})", ids):
        key = dict(_BOARD_KEYS).get(board)
        if key is None:
            continue
        b = out[cid][key]
        line = parse_line_version(pv)
        b["lines"] += 1
        if line["state"] == "empty":
            b["empty"] += 1
        elif state == "incomplete":  # text but no train (also pre-grid captures)
            b["unread"] += 1
        else:
            b["rows"] += 1
        if line["retry"]:
            b["retried"] += 1
            b["recovered"] += bool(line["retry"]["variant"])
    return out


def list_captures(store, limit: int = 50, before: int | None = None) -> list[dict]:
    limit = max(1, min(int(limit), LIST_MAX))
    where, args = ("WHERE id < ?", [before]) if before else ("", [])
    with store._lock:
        found = store._conn.execute(
            f"SELECT {_CAP_COLS} FROM captures {where} ORDER BY id DESC LIMIT ?",
            (*args, limit)).fetchall()
        counts = _board_counts(store._conn, [r["id"] for r in found])
    return [{**_cap(r), "boards": counts[r["id"]]} for r in found]


def capture_detail(store, cid: int) -> dict | None:
    with store._lock:
        c = store._conn.execute(f"SELECT {_CAP_COLS} FROM captures WHERE id=?",
                                (cid,)).fetchone()
        if c is None:
            return None
        obs = store._conn.execute(
            "SELECT * FROM observations WHERE capture_id=? ORDER BY board, row_index, id",
            (cid,)).fetchall()
    out = _cap(c)
    with store._lock:
        out["boards"] = _board_counts(store._conn, [cid])[cid]
    out["observations"] = [{
        "id": o["id"], "board": o["board"], "row_index": o["row_index"],
        "service_id": o["service_id"], "raw_text": o["raw_text"],
        "fields": json.loads(o["fields_json"] or "{}"),
        "train_no": o["train_no"], "sched_time": o["sched_time"],
        "delay_min": o["delay_min"], "delay_read": bool(o["delay_read"]),
        "platform": o["platform"], "station": o["station"], "station_raw": o["station_raw"],
        "operator": o["operator"], "operator_raw": o["operator_raw"],
        "row_conf": o["row_conf"], "uncertain": bool(o["uncertain"]),
        "validation_state": o["validation_state"],
        "processing_version": o["processing_version"],
        "line": parse_line_version(o["processing_version"]),
    } for o in obs]
    return out


def image_path(store, root, cid: int) -> Path | None:
    with store._lock:
        r = store._conn.execute("SELECT path FROM captures WHERE id=?", (cid,)).fetchone()
    if r is None or r[0] is None:
        return None
    p = safe_path(root, r[0])
    return p if p is not None and p.is_file() else None


# -- overlay ----------------------------------------------------------------------------

GREEN, AMBER, RED = (60, 170, 40), (0, 170, 245), (40, 40, 220)  # BGR


def conf_colour(conf: float | None) -> tuple[int, int, int]:
    if conf is None:
        return RED
    return GREEN if conf >= 80 else AMBER if conf >= 50 else RED


def overlay_png(image_bytes: bytes, observations: list[dict]) -> bytes | None:
    """PNG of the image with one rectangle per OCR cell (colour by confidence) and the
    line index per row. Same size as the original. None if the image is undecodable."""
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    for o in observations:
        boxes = []
        for f in (o.get("fields") or {}).values():
            bb = f.get("bbox") if isinstance(f, dict) else None
            if not (isinstance(bb, list) and len(bb) == 4):
                continue
            x, y, bw, bh = (int(v) for v in bb)
            x, y = max(0, min(x, w - 1)), max(0, min(y, h - 1))
            cv2.rectangle(img, (x, y), (min(w - 1, x + bw - 1), min(h - 1, y + bh - 1)),
                          conf_colour(f.get("conf")), 1)
            boxes.append((x, y, bh))
        if boxes:
            x, y, bh = min(boxes)
            label = str(o.get("row_index", ""))
            scale = max(0.3, min(1.0, bh / 30))
            cv2.putText(img, label, (x + 2, y + max(8, int(bh * 0.8))),
                        cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(img, label, (x + 2, y + max(8, int(bh * 0.8))),
                        cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes() if ok else None


# -- system stats ----------------------------------------------------------------------

def _p95(values: list[int]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return float(s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))])


def capture_system_stats(store, db_path: str, now: datetime | None = None) -> dict:
    now = now or _now()
    day_ago = (now - timedelta(hours=24)).isoformat(timespec="seconds")
    c = store._conn
    with store._lock:
        last_any = c.execute("SELECT MAX(COALESCE(last_seen_at, captured_at)) FROM captures"
                             ).fetchone()[0]
        last_ok = c.execute("SELECT MAX(captured_at) FROM captures WHERE ok=1").fetchone()[0]
        last_run = c.execute("SELECT MAX(ts) FROM runs").fetchone()[0]
        durs = [r[0] for r in c.execute(
            "SELECT duration_ms FROM captures WHERE duration_ms IS NOT NULL"
            " ORDER BY id DESC LIMIT 100")]
        errors = c.execute("SELECT COUNT(*) FROM captures WHERE ok=0 AND captured_at >= ?",
                           (day_ago,)).fetchone()[0]
        rows_total, rows_bad = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(validation_state IN"
            " ('rejected_low_conf', 'incomplete')), 0) FROM observations"
            " WHERE observed_at >= ?", (day_ago,)).fetchone()
    disk_free = None
    if db_path and db_path != ":memory:":
        try:
            disk_free = shutil.disk_usage(os.path.dirname(os.path.abspath(db_path))).free
        except OSError:
            pass
    db_bytes = 0
    if db_path and db_path != ":memory:":
        for suffix in ("", "-wal", "-shm"):
            try:
                db_bytes += os.path.getsize(db_path + suffix)
            except OSError:
                pass
    return {
        "disk_free_bytes": disk_free,
        "last_capture_attempt": last_any, "last_capture_ok": last_ok,
        "last_ocr_run": last_run,
        "duration_ms": {"n": len(durs),
                        "avg": round(statistics.fmean(durs), 1) if durs else None,
                        "p95": _p95(durs)},
        "errors_24h": errors, "rows_24h": rows_total, "rows_with_errors_24h": rows_bad,
        "db_bytes": db_bytes, "images": capture_stats(store),
    }


def make_on_capture(store, settings: CaptureSettings):
    """Poller hook recording each new image; a failure here never reaches the poller."""
    from app import observations

    async def on_capture(image: bytes, rows, debug, ts: float, duration_ms: int | None,
                         error: str | None) -> None:
        if not settings.enabled:
            return
        try:
            await asyncio.to_thread(
                observations.record_capture, store, image, rows, debug, ts,
                capture_dir=settings.dir, retention_days=settings.retention_days,
                duration_ms=duration_ms, error=error)
        except Exception:
            log.exception("capture recording failed (board ingest unaffected)")

    return on_capture
