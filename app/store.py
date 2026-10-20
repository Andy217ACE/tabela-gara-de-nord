# © 2026 Andy217Ace
"""SQLite persistence: runs, services (one per train/day/board), events.

`ingest` diffs a validated board reading against the stored state and emits
`Event`s (appeared / delay / platform / gone). Readings that are too small or
miss a whole board are recorded as failed runs (`ok=0`) and touch nothing else.
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import Event, Row

TZ = ZoneInfo("Europe/Bucharest")
MIN_ROWS = 4
GONE_AFTER_MISSES = 2
MIN_CONFIDENCE = 0.5  # rows below this never create/change services or emit events
JITTER_MIN = 10  # sched_time misread tolerance (minutes) for matching a listed service
STALE_MIN = 30  # listed services unseen this long are retired silently
SCHEMA_VERSION = 1

_BOARD_KEYS = {"arrival": "arrivals", "departure": "departures"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    image_hash TEXT NOT NULL DEFAULT '',
    ok INTEGER NOT NULL,
    n_rows INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_runs_ok_ts ON runs(ok, ts);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY,
    board TEXT NOT NULL CHECK (board IN ('arrival', 'departure')),
    service_date TEXT NOT NULL,
    train_type TEXT NOT NULL,
    train_no INTEGER NOT NULL,
    station TEXT NOT NULL,
    operator TEXT NOT NULL,
    sched_time TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_delay INTEGER NOT NULL DEFAULT 0,
    last_platform INTEGER,
    flagged INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'listed' CHECK (status IN ('listed', 'gone')),
    miss_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE (board, service_date, train_no, sched_time)
);
CREATE INDEX IF NOT EXISTS ix_services_date ON services(service_date);
CREATE INDEX IF NOT EXISTS ix_services_train ON services(train_no, service_date);
CREATE INDEX IF NOT EXISTS ix_services_status ON services(status);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('delay', 'platform', 'appeared', 'gone')),
    old TEXT,
    new TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_service ON events(service_id, ts);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS follows (
    subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    train_no INTEGER NOT NULL,
    service_date TEXT NOT NULL,
    PRIMARY KEY (subscription_id, train_no, service_date)
);
CREATE INDEX IF NOT EXISTS ix_follows_train ON follows(train_no, service_date);
"""


def _local(dt: datetime) -> datetime:
    """Aware datetime in Europe/Bucharest; naive input is taken as local time."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def _hm(sched_time: str) -> time:
    hh, mm = (int(p) for p in sched_time.split(":"))
    return time(hh, mm)


def service_date(sched_time: str, now: datetime) -> date:
    """Day a scheduled time belongs to, given the moment it was read.

    A time more than 12 h ahead of `now` belongs to the previous day, more than
    12 h behind to the next day (00:05 seen at 23:58 -> tomorrow).
    """
    local = _local(now)
    hh, mm = (int(p) for p in sched_time.split(":"))
    cand = datetime(local.year, local.month, local.day, hh, mm)
    naive_now = local.replace(tzinfo=None)
    diff = cand - naive_now
    if diff > timedelta(hours=12):
        return (cand - timedelta(days=1)).date()
    if diff < -timedelta(hours=12):
        return (cand + timedelta(days=1)).date()
    return cand.date()


def _plat(p: int | None) -> str | None:
    return None if p is None else str(p)


class Store:
    service_date = staticmethod(service_date)

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def migrate(self) -> None:
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version >= SCHEMA_VERSION:
                return
            self._conn.executescript("BEGIN;" + _SCHEMA + f"PRAGMA user_version = {SCHEMA_VERSION};COMMIT;")

    # -- ingest -----------------------------------------------------------

    @staticmethod
    def _split(rows: list[Row]) -> tuple[list[Row], list[Row]]:
        """Deduplicate by Row.key (confident rows win) and split by confidence."""
        good: dict[tuple, Row] = {}
        low: dict[tuple, Row] = {}
        for r in rows:
            if r.confidence >= MIN_CONFIDENCE:
                good.setdefault(r.key, r)
        for r in rows:
            if r.confidence < MIN_CONFIDENCE and r.key not in good:
                low.setdefault(r.key, r)
        return list(good.values()), list(low.values())

    @staticmethod
    def _valid(rows: list[Row]) -> bool:
        boards = {r.board for r in rows}
        return len(rows) >= MIN_ROWS and {"arrival", "departure"} <= boards

    def _insert_event(self, service_id: int, ts: str, kind: str,
                      old: str | None, new: str | None) -> None:
        self._conn.execute(
            "INSERT INTO events(service_id, ts, kind, old, new) VALUES (?,?,?,?,?)",
            (service_id, ts, kind, old, new),
        )

    def ingest(self, rows: list[Row], ts: datetime, image_hash: str = "") -> list[Event]:
        local = _local(ts)
        ts_s = local.isoformat()
        with self._lock:
            c = self._conn
            c.execute("BEGIN IMMEDIATE")
            try:
                good, low = self._split(rows)
                if not self._valid(good):
                    c.execute("INSERT INTO runs(ts, image_hash, ok, n_rows) VALUES (?,?,0,?)",
                              (ts_s, image_hash, len(rows)))
                    c.execute("COMMIT")
                    return []
                c.execute("INSERT INTO runs(ts, image_hash, ok, n_rows) VALUES (?,?,1,?)",
                          (ts_s, image_hash, len(rows)))
                events = self._diff(good, low, local, ts_s)
                c.execute("COMMIT")
                return events
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def _find_exact(self, r: Row, sd: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM services WHERE board=? AND service_date=? AND train_no=?"
            " AND sched_time=?", (r.board, sd, r.train_no, r.sched_time),
        ).fetchone()

    def _find_jitter(self, r: Row, sd: str, claimed: set[int]) -> sqlite3.Row | None:
        """Closest listed service of the same train/board within JITTER_MIN minutes.

        The scheduled time never changes legitimately, so a near miss is an OCR
        misread of the same service.
        """
        target = datetime.combine(date.fromisoformat(sd), _hm(r.sched_time))
        d = date.fromisoformat(sd)
        cands = self._conn.execute(
            "SELECT * FROM services WHERE status='listed' AND board=? AND train_no=?"
            " AND service_date IN (?,?,?)",
            (r.board, r.train_no, (d - timedelta(days=1)).isoformat(), sd,
             (d + timedelta(days=1)).isoformat()),
        ).fetchall()
        best, best_diff = None, None
        for s in cands:
            if s["id"] in claimed:
                continue
            at = datetime.combine(date.fromisoformat(s["service_date"]), _hm(s["sched_time"]))
            diff = abs(at - target)
            if diff <= timedelta(minutes=JITTER_MIN) and (best_diff is None or diff < best_diff):
                best, best_diff = s, diff
        return best

    def _diff(self, good: list[Row], low: list[Row], local: datetime,
              ts_s: str) -> list[Event]:
        c = self._conn
        events: list[Event] = []
        seen: set[int] = set()

        def emit(sid: int, kind: str, row: Row, sd: str, old=None, new=None) -> None:
            self._insert_event(sid, ts_s, kind, old, new)
            events.append(Event(kind, row, old, new, sd))

        # Pass 1: exact key matches (claim them so jitter can't steal them).
        dated = [(r, service_date(r.sched_time, local).isoformat()) for r in good]
        matches: list[tuple[Row, str, sqlite3.Row | None]] = []
        for r, sd in dated:
            cur = self._find_exact(r, sd)
            if cur is not None:
                seen.add(cur["id"])
            matches.append((r, sd, cur))
        # Pass 2: sched_time jitter for the unmatched rows.
        for i, (r, sd, cur) in enumerate(matches):
            if cur is None:
                cur = self._find_jitter(r, sd, seen)
                if cur is not None:
                    seen.add(cur["id"])
                    matches[i] = (r, sd, cur)

        for r, sd, cur in matches:
            if cur is None:
                sid = c.execute(
                    "INSERT INTO services(board, service_date, train_type, train_no, station,"
                    " operator, sched_time, first_seen, last_seen, last_delay, last_platform,"
                    " flagged, status, miss_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'listed',0)",
                    (r.board, sd, r.train_type, r.train_no, r.station, r.operator,
                     r.sched_time, ts_s, ts_s, r.delay_min, r.platform, int(r.flagged)),
                ).lastrowid
                seen.add(sid)
                emit(sid, "appeared", r, sd)
                continue
            sid, sd = cur["id"], cur["service_date"]
            row = replace(r, sched_time=cur["sched_time"])  # stored sched_time wins
            if cur["status"] == "gone":
                emit(sid, "appeared", row, sd)
            if cur["last_delay"] != r.delay_min:
                emit(sid, "delay", row, sd, str(cur["last_delay"]), str(r.delay_min))
            if cur["last_platform"] != r.platform:
                emit(sid, "platform", row, sd, _plat(cur["last_platform"]), _plat(r.platform))
            c.execute(
                "UPDATE services SET train_type=?, station=?, operator=?, last_seen=?,"
                " last_delay=?, last_platform=?, flagged=?, status='listed', miss_count=0"
                " WHERE id=?",
                (r.train_type, r.station, r.operator, ts_s, r.delay_min, r.platform,
                 int(r.flagged), sid),
            )

        # Low-confidence rows: only keep an exactly matching service alive.
        for r in low:
            cur = self._find_exact(r, service_date(r.sched_time, local).isoformat())
            if cur is not None and cur["id"] not in seen:
                seen.add(cur["id"])
                c.execute("UPDATE services SET last_seen=?, miss_count=0 WHERE id=?",
                          (ts_s, cur["id"]))

        stale_before = local - timedelta(minutes=STALE_MIN)
        for s in c.execute("SELECT * FROM services WHERE status='listed'").fetchall():
            if s["id"] in seen:
                continue
            misses = s["miss_count"] + 1
            if datetime.fromisoformat(s["last_seen"]) < stale_before:
                # Not seen for a long time (e.g. downtime): retire without an event.
                c.execute("UPDATE services SET status='gone', miss_count=? WHERE id=?",
                          (misses, s["id"]))
            elif misses >= GONE_AFTER_MISSES:
                c.execute("UPDATE services SET status='gone', miss_count=? WHERE id=?",
                          (misses, s["id"]))
                emit(s["id"], "gone", self._row_of(s), s["service_date"])
            else:
                c.execute("UPDATE services SET miss_count=? WHERE id=?", (misses, s["id"]))
        return events

    @staticmethod
    def _row_of(s: sqlite3.Row) -> Row:
        return Row(board=s["board"], train_type=s["train_type"], train_no=s["train_no"],
                   station=s["station"], operator=s["operator"], sched_time=s["sched_time"],
                   delay_min=s["last_delay"], platform=s["last_platform"],
                   flagged=bool(s["flagged"]))

    # -- reads ------------------------------------------------------------

    def _last_ok_ts(self) -> str | None:
        r = self._conn.execute("SELECT ts FROM runs WHERE ok=1 ORDER BY id DESC LIMIT 1").fetchone()
        return r[0] if r else None

    def current_board(self) -> dict:
        with self._lock:
            out: dict = {"updated_at": self._last_ok_ts(), "arrivals": [], "departures": []}
            rows = self._conn.execute(
                "SELECT board, train_type, train_no, station, operator, sched_time,"
                " last_delay, last_platform, flagged, status FROM services"
                " WHERE status='listed' ORDER BY service_date, sched_time, train_no"
            ).fetchall()
        for s in rows:
            out[_BOARD_KEYS[s["board"]]].append({
                "train_type": s["train_type"], "train_no": s["train_no"],
                "station": s["station"], "operator": s["operator"],
                "sched_time": s["sched_time"], "delay_min": s["last_delay"],
                "platform": s["last_platform"], "flagged": bool(s["flagged"]),
                "status": s["status"],
            })
        return out

    def last_ok_age(self, now: datetime) -> float | None:
        with self._lock:
            ts = self._last_ok_ts()
        if ts is None:
            return None
        return (_local(now) - datetime.fromisoformat(ts)).total_seconds()
