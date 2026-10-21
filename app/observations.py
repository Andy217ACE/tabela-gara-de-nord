# © 2026 Andy217Ace
"""OCR captures, per-row observations and the train-number catalog (schema v5).

Three distinct things, never conflated:
- a *capture* is one board image as fetched (stored file + metadata);
- an *observation* is one OCR line of a capture, kept even when incomplete or
  low-confidence (``validation_state`` says which), with the raw text per field;
- a *journey* is a service (``services`` row: one train, one day, one board).

``trains`` is the catalog of every train number ever validated on the board:
``journeys`` counts services, ``observations`` counts usable OCR observations
(``ok`` / ``uncertain``). History from before v5 has journeys but 0 observations.

All timestamps written here are UTC ISO 8601.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

from app.models import Row
from app.store import JITTER_MIN, MIN_CONFIDENCE, TZ, service_date

log = logging.getLogger(__name__)

# below this much free space on CAPTURE_DIR's disk no image file is written (the DB and
# the live board share the disk; a full disk would stop the board). Env CAPTURE_MIN_FREE_MB.
MIN_FREE_MB_DEFAULT = 2048
PROCESSING_VERSION = "ocr-tess-digits-1"  # bump when OCR/parsing changes meaningfully
STATES = ("ok", "uncertain", "rejected_low_conf", "incomplete")
FIELDS = ("type", "no", "station", "operator", "time", "delay", "platform")

SCHEMA_V5 = (
    """CREATE TABLE IF NOT EXISTS captures (
        id INTEGER PRIMARY KEY,
        captured_at TEXT NOT NULL,
        last_seen_at TEXT,
        image_hash TEXT NOT NULL UNIQUE,
        path TEXT,
        width INTEGER,
        height INTEGER,
        bytes INTEGER,
        ok INTEGER NOT NULL,
        n_rows INTEGER NOT NULL DEFAULT 0,
        processing_version TEXT,
        duration_ms INTEGER,
        error TEXT,
        expires_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS ix_captures_at ON captures(captured_at)",
    """CREATE TABLE IF NOT EXISTS observations (
        id INTEGER PRIMARY KEY,
        capture_id INTEGER NOT NULL REFERENCES captures(id),
        service_id INTEGER REFERENCES services(id) ON DELETE SET NULL,
        board TEXT NOT NULL CHECK (board IN ('arrival', 'departure')),
        row_index INTEGER NOT NULL,
        observed_at TEXT NOT NULL,
        raw_text TEXT NOT NULL DEFAULT '',
        fields_json TEXT NOT NULL DEFAULT '{}',
        train_no INTEGER,
        sched_time TEXT,
        delay_min INTEGER,
        delay_read INTEGER NOT NULL DEFAULT 0,
        platform INTEGER,
        station TEXT,
        station_raw TEXT,
        operator TEXT,
        operator_raw TEXT,
        row_conf REAL,
        uncertain INTEGER NOT NULL DEFAULT 0,
        validation_state TEXT NOT NULL
            CHECK (validation_state IN ('ok', 'uncertain', 'rejected_low_conf', 'incomplete')),
        processing_version TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_observations_service ON observations(service_id)",
    "CREATE INDEX IF NOT EXISTS ix_observations_observed ON observations(observed_at)",
    "CREATE INDEX IF NOT EXISTS ix_observations_capture ON observations(capture_id)",
    "CREATE INDEX IF NOT EXISTS ix_observations_train ON observations(train_no, observed_at)",
    # covers refresh_trains' per-train count (runs for every capture)
    "CREATE INDEX IF NOT EXISTS ix_observations_train_state"
    " ON observations(train_no, validation_state, observed_at)",
    """CREATE TABLE IF NOT EXISTS trains (
        train_no INTEGER PRIMARY KEY,
        first_seen TEXT,
        last_seen TEXT,
        operators_json TEXT NOT NULL DEFAULT '[]',
        routes_json TEXT NOT NULL DEFAULT '[]',
        journeys INTEGER NOT NULL DEFAULT 0,
        observations INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS ix_trains_last_seen ON trains(last_seen)",
)


def _utc(value: datetime | str | float) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=TZ)
    return value.astimezone(timezone.utc)


def utc_iso(value: datetime | str | float) -> str:
    return _utc(value).isoformat(timespec="seconds")


# -- migration ---------------------------------------------------------------

def migrate_to_5(conn: sqlite3.Connection) -> None:
    """Create the v5 tables and backfill the catalog from `services`, atomically."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 5:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        for stmt in SCHEMA_V5:
            conn.execute(stmt)
        nos = [r[0] for r in conn.execute("SELECT DISTINCT train_no FROM services")]
        refresh_trains(conn, nos)
        conn.execute("PRAGMA user_version = 5")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def refresh_trains(conn: sqlite3.Connection, train_nos) -> None:
    """Recompute the catalog entries of `train_nos` from services + observations.

    Idempotent (pure function of the stored data). Operator/route counts are
    journeys (services). Train numbers with neither a service nor a usable
    observation are not catalogued (a misread number is not a train).
    """
    for no in sorted({int(n) for n in train_nos if n}):
        svc = conn.execute(
            "SELECT board, station, operator, first_seen, last_seen FROM services"
            " WHERE train_no=?", (no,)).fetchall()
        n_obs, o_first, o_last = conn.execute(
            "SELECT COUNT(*), MIN(observed_at), MAX(observed_at) FROM observations"
            " WHERE train_no=? AND validation_state IN ('ok', 'uncertain')", (no,)).fetchone()
        if not svc and not n_obs:
            continue
        stamps = [_utc(s[3]) for s in svc] + [_utc(s[4]) for s in svc]
        stamps += [_utc(x) for x in (o_first, o_last) if x]
        ops = Counter(s[2] for s in svc if s[2])
        routes = Counter((s[0], s[1]) for s in svc if s[1])
        conn.execute(
            "INSERT INTO trains(train_no, first_seen, last_seen, operators_json, routes_json,"
            " journeys, observations) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(train_no) DO UPDATE SET first_seen=excluded.first_seen,"
            " last_seen=excluded.last_seen, operators_json=excluded.operators_json,"
            " routes_json=excluded.routes_json, journeys=excluded.journeys,"
            " observations=excluded.observations",
            (no, min(stamps).isoformat(timespec="seconds"),
             max(stamps).isoformat(timespec="seconds"),
             json.dumps([{"operator": k, "journeys": v}
                         for k, v in sorted(ops.items(), key=lambda kv: (-kv[1], kv[0]))],
                        ensure_ascii=False),
             json.dumps([{"board": b, "station": st, "journeys": v}
                         for (b, st), v in sorted(routes.items(),
                                                  key=lambda kv: (-kv[1], kv[0]))],
                        ensure_ascii=False),
             len(svc), n_obs))


# -- recording ----------------------------------------------------------------

def validation_state(row: Row | None) -> str:
    if row is None or not row.train_no:
        return "incomplete"
    if row.confidence < MIN_CONFIDENCE:
        return "rejected_low_conf"
    if row.uncertain or not row.delay_read:
        return "uncertain"
    return "ok"


def _entries(rows: list[Row], debug: list[dict] | None) -> list[dict]:
    """Debug entries, or minimal ones built from the rows (no per-field data)."""
    if debug is not None:
        return debug
    out, per_board = [], Counter()
    for r in rows:
        out.append({"board": r.board, "row_index": per_board[r.board], "row": r,
                    "conf": r.confidence, "raw_text": "", "fields": {}})
        per_board[r.board] += 1
    return out


def _link(conn: sqlite3.Connection, row: Row, ingest_ts: str, local: datetime) -> int | None:
    """Service the Store matched to `row` in the ingest at `ingest_ts` (its last_seen)."""
    sd = service_date(row.sched_time, local)
    days = [(sd + timedelta(days=k)).isoformat() for k in (-1, 0, 1)]
    cands = conn.execute(
        "SELECT id, service_date, sched_time FROM services WHERE board=? AND train_no=?"
        " AND last_seen=? AND service_date IN (?,?,?)",
        (row.board, row.train_no, ingest_ts, *days)).fetchall()
    target = datetime.combine(sd, datetime.strptime(row.sched_time, "%H:%M").time())
    best = None
    for sid, sday, st in cands:
        at = datetime.combine(date.fromisoformat(sday), datetime.strptime(st, "%H:%M").time())
        diff = abs(at - target)
        if diff <= timedelta(minutes=JITTER_MIN) and (best is None or diff < best[0]):
            best = (diff, sid)
    return best[1] if best else None


def _image_size(data: bytes) -> tuple[int | None, int | None]:
    try:
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    except cv2.error:
        img = None
    if img is None:
        return None, None
    return int(img.shape[1]), int(img.shape[0])


def capture_relpath(when: datetime, image_hash: str) -> str:
    """`YYYY/MM/DD/HHMMSS-<hash8>.jpg` (UTC), always with forward slashes."""
    u = _utc(when)
    return f"{u:%Y/%m/%d}/{u:%H%M%S}-{image_hash[:8]}.jpg"


def min_free_bytes() -> int:
    try:
        mb = int(os.environ.get("CAPTURE_MIN_FREE_MB", MIN_FREE_MB_DEFAULT))
    except ValueError:
        mb = MIN_FREE_MB_DEFAULT
    return max(0, mb) * 1024 * 1024


def _disk_ok(root: Path, need: int) -> bool:
    """Enough free space for one more image while keeping the floor free."""
    try:
        probe = root if root.exists() else root.parent
        free = shutil.disk_usage(probe).free
    except OSError:
        return True  # cannot tell: the write itself will fail cleanly if needed
    if free - need < min_free_bytes():
        log.warning("capture image not saved: only %d MB free (floor %d MB)",
                    free // 2**20, min_free_bytes() // 2**20)
        return False
    return True


def _write_file(root: Path, rel: str, data: bytes) -> bool:
    tmp = None
    try:
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
        return True
    except OSError:
        log.warning("could not save capture image %s", rel, exc_info=True)
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        return False


def _remove_file(root: Path, rel: str) -> None:
    try:
        (root / rel).unlink(missing_ok=True)
    except OSError:
        log.warning("could not remove orphan capture image %s", rel, exc_info=True)


def record_capture(store, image_bytes: bytes, rows: list[Row] | None,
                   debug: list[dict] | None, ts, *, capture_dir: str | os.PathLike | None,
                   retention_days: int = 7, duration_ms: int | None = None,
                   error: str | None = None,
                   processing_version: str = PROCESSING_VERSION) -> int:
    """Store one fetched image (file saved unmodified) and one observation per OCR line.

    `ts` is the reading time (epoch seconds or datetime) — the same value handed to
    ``Store.ingest`` so the observations link to the services it matched.
    An image already recorded (same SHA-1) only bumps ``last_seen_at``.
    `capture_dir` None: metadata only, no file. Returns the capture id.
    """
    rows = rows or []
    h = hashlib.sha1(image_bytes).hexdigest()
    when = _utc(ts)
    now_s = when.isoformat(timespec="seconds")
    local = when.astimezone(TZ)
    ingest_ts = local.isoformat()  # exactly what Store.ingest wrote to last_seen
    conn = store._conn
    with store._lock:
        cur = conn.execute("SELECT id FROM captures WHERE image_hash=?", (h,)).fetchone()
        if cur is not None:
            conn.execute("UPDATE captures SET last_seen_at=? WHERE id=?", (now_s, cur[0]))
            return cur[0]

    rel = None
    # retention 0 keeps no image at all; a nearly full disk keeps metadata only
    if capture_dir is not None and retention_days > 0             and _disk_ok(Path(capture_dir), len(image_bytes)):
        rel = capture_relpath(when, h)
        if not _write_file(Path(capture_dir), rel, image_bytes):
            rel = None
    width, height = _image_size(image_bytes)
    expires = (when + timedelta(days=max(0, retention_days))).isoformat(timespec="seconds")

    with store._lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            cid = conn.execute(
                "INSERT INTO captures(captured_at, last_seen_at, image_hash, path, width,"
                " height, bytes, ok, n_rows, processing_version, duration_ms, error,"
                " expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (now_s, now_s, h, rel, width, height, len(image_bytes),
                 int(error is None), len(rows), processing_version, duration_ms,
                 (error or None) and error[:500], expires)).lastrowid
            nos = set()
            for e in _entries(rows, debug):
                r: Row | None = e.get("row")
                state = validation_state(r)
                fields = e.get("fields") or {}
                sid = _link(conn, r, ingest_ts, local) if state != "incomplete" else None
                f_no = (fields.get("no") or {}).get("norm")
                train_no = r.train_no if r is not None else f_no
                conn.execute(
                    "INSERT INTO observations(capture_id, service_id, board, row_index,"
                    " observed_at, raw_text, fields_json, train_no, sched_time, delay_min,"
                    " delay_read, platform, station, station_raw, operator, operator_raw,"
                    " row_conf, uncertain, validation_state, processing_version)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (cid, sid, e["board"], e["row_index"], now_s, e.get("raw_text") or "",
                     json.dumps(fields, ensure_ascii=False, default=str),
                     train_no or None,
                     r.sched_time if r else (fields.get("time") or {}).get("norm"),
                     (r.delay_min if r.delay_read else None) if r else None,
                     int(bool(r and r.delay_read)),
                     r.platform if r else (fields.get("platform") or {}).get("norm"),
                     r.station if r else (fields.get("station") or {}).get("norm"),
                     r.station_raw if r else (fields.get("station") or {}).get("raw"),
                     r.operator if r else (fields.get("operator") or {}).get("norm"),
                     r.operator_raw if r else (fields.get("operator") or {}).get("raw"),
                     (None if e.get("conf") is None else round(float(e["conf"]), 4)),
                     int(bool(r and r.uncertain)), state, processing_version))
                if state in ("ok", "uncertain"):
                    nos.add(train_no)
            refresh_trains(conn, nos)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            if rel is not None:  # no DB row will ever point at it: retention could not delete it
                _remove_file(Path(capture_dir), rel)
            raise
    return cid


def refresh_catalog(store, rows: list[Row]) -> None:
    """Keep `trains` current from the board ingest itself (independent of captures)."""
    nos = {r.train_no for r in rows if r.train_no and r.confidence >= MIN_CONFIDENCE}
    if not nos:
        return
    conn = store._conn
    with store._lock:
        conn.execute("BEGIN IMMEDIATE")
        try:
            refresh_trains(conn, nos)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


# -- public catalog reads --------------------------------------------------------

TRAINS_MAX = 200
JOURNEYS_MAX = 200


def _train_dict(r) -> dict:
    return {"train_no": r["train_no"], "first_seen": r["first_seen"],
            "last_seen": r["last_seen"], "operators": json.loads(r["operators_json"] or "[]"),
            "routes": json.loads(r["routes_json"] or "[]"),
            "journeys": r["journeys"], "observations": r["observations"]}


def list_trains(store, query: str | None = None, limit: int = 50) -> list[dict]:
    """Catalog entries, most recently seen first. `query`: train-number prefix
    (digits) or a case-insensitive substring of a station/operator name."""
    limit = max(1, min(int(limit), TRAINS_MAX))
    where, args = "", []
    if query:
        if query.isascii() and query.isdigit():
            where, args = " WHERE CAST(train_no AS TEXT) LIKE ? ESCAPE '!'", [query + "%"]
        else:
            esc = query.lower().replace("!", "!!").replace("%", "!%").replace("_", "!_")
            where = " WHERE lower(routes_json) LIKE ? ESCAPE '!' OR lower(operators_json) LIKE ? ESCAPE '!'"
            args = [f"%{esc}%", f"%{esc}%"]
    with store._lock:
        found = store._conn.execute(
            "SELECT * FROM trains" + where + " ORDER BY last_seen DESC, train_no LIMIT ?",
            (*args, limit)).fetchall()
    return [_train_dict(r) for r in found]


def train_detail(store, train_no: int) -> dict | None:
    """Catalog entry + its journeys (services), newest first, capped at JOURNEYS_MAX."""
    with store._lock:
        t = store._conn.execute("SELECT * FROM trains WHERE train_no=?",
                                (train_no,)).fetchone()
        if t is None:
            return None
        found = store._conn.execute(
            "SELECT s.id, s.board, s.service_date, s.train_type, s.sched_time, s.station,"
            " s.operator, s.first_seen, s.last_seen, s.status, s.last_delay,"
            " (SELECT COUNT(*) FROM observations o WHERE o.service_id = s.id) AS n_obs"
            " FROM services s WHERE s.train_no=?"
            " ORDER BY s.service_date DESC, s.sched_time DESC LIMIT ?",
            (train_no, JOURNEYS_MAX + 1)).fetchall()
    out = _train_dict(t)
    out["journeys_list"] = [{
        "board": r["board"], "service_date": r["service_date"], "train_type": r["train_type"],
        "sched_time": r["sched_time"], "station": r["station"], "operator": r["operator"],
        "first_seen": utc_iso(r["first_seen"]), "last_seen": utc_iso(r["last_seen"]),
        "status": r["status"], "observations": r["n_obs"],
    } for r in found[:JOURNEYS_MAX]]
    out["journeys_truncated"] = len(found) > JOURNEYS_MAX
    return out
