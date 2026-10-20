# © 2026 Andy217Ace
"""SQLite persistence: runs, services (one per train/day/board), events.

`ingest` diffs a validated board reading against the stored state and emits
`Event`s (appeared / delay / platform / gone). Readings that are too small or
miss a whole board are recorded as failed runs (`ok=0`) and touch nothing else.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import Event, Row

TZ = ZoneInfo("Europe/Bucharest")
MIN_ROWS = 4
GONE_AFTER_MISSES = 2
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
                if not self._valid(rows):
                    c.execute("INSERT INTO runs(ts, image_hash, ok, n_rows) VALUES (?,?,0,?)",
                              (ts_s, image_hash, len(rows)))
                    c.execute("COMMIT")
                    return []
                c.execute("INSERT INTO runs(ts, image_hash, ok, n_rows) VALUES (?,?,1,?)",
                          (ts_s, image_hash, len(rows)))
                events = self._diff(rows, local, ts_s)
                c.execute("COMMIT")
                return events
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def _diff(self, rows: list[Row], local: datetime, ts_s: str) -> list[Event]:
        c = self._conn
        events: list[Event] = []
        seen: set[int] = set()
        keys: set[tuple] = set()
        for r in rows:
            sd = service_date(r.sched_time, local).isoformat()
            key = (r.board, sd, r.train_no, r.sched_time)
            if key in keys:  # duplicate line in one reading: first wins
                continue
            keys.add(key)
            cur = c.execute(
                "SELECT id, last_delay, last_platform, status FROM services "
                "WHERE board=? AND service_date=? AND train_no=? AND sched_time=?",
                key,
            ).fetchone()
            if cur is None:
                sid = c.execute(
                    "INSERT INTO services(board, service_date, train_type, train_no, station,"
                    " operator, sched_time, first_seen, last_seen, last_delay, last_platform,"
                    " flagged, status, miss_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'listed',0)",
                    (r.board, sd, r.train_type, r.train_no, r.station, r.operator,
                     r.sched_time, ts_s, ts_s, r.delay_min, r.platform, int(r.flagged)),
                ).lastrowid
                self._insert_event(sid, ts_s, "appeared", None, None)
                events.append(Event("appeared", r, None, None))
                seen.add(sid)
                continue
            sid = cur["id"]
            seen.add(sid)
            if cur["status"] == "gone":
                self._insert_event(sid, ts_s, "appeared", None, None)
                events.append(Event("appeared", r, None, None))
            if cur["last_delay"] != r.delay_min:
                old, new = str(cur["last_delay"]), str(r.delay_min)
                self._insert_event(sid, ts_s, "delay", old, new)
                events.append(Event("delay", r, old, new))
            if cur["last_platform"] != r.platform:
                old, new = _plat(cur["last_platform"]), _plat(r.platform)
                self._insert_event(sid, ts_s, "platform", old, new)
                events.append(Event("platform", r, old, new))
            c.execute(
                "UPDATE services SET train_type=?, station=?, operator=?, last_seen=?,"
                " last_delay=?, last_platform=?, flagged=?, status='listed', miss_count=0"
                " WHERE id=?",
                (r.train_type, r.station, r.operator, ts_s, r.delay_min, r.platform,
                 int(r.flagged), sid),
            )

        for s in c.execute("SELECT * FROM services WHERE status='listed'").fetchall():
            if s["id"] in seen:
                continue
            misses = s["miss_count"] + 1
            if misses >= GONE_AFTER_MISSES:
                c.execute("UPDATE services SET status='gone', miss_count=? WHERE id=?",
                          (misses, s["id"]))
                self._insert_event(s["id"], ts_s, "gone", None, None)
                events.append(Event("gone", self._row_of(s), None, None))
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
                "platform": s["last_platform"], "flagged": s["flagged"],
                "status": s["status"],
            })
        return out

    def last_ok_age(self, now: datetime) -> float | None:
        with self._lock:
            ts = self._last_ok_ts()
        if ts is None:
            return None
        return (_local(now) - datetime.fromisoformat(ts)).total_seconds()
