# © 2026 Andy217Ace
"""SQLite persistence: runs, services (one per train/day/board), events.

`ingest` diffs a validated board reading against the stored state and emits
`Event`s (appeared / delay / platform / gone). Readings that are too small or
miss a whole board are recorded as failed runs (`ok=0`) and touch nothing else.
"""
from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.endpoints import MAX_ENDPOINT_LEN, check_push_endpoint  # noqa: F401
from app.models import Event, Row
from app.normalize import clean_station

TZ = ZoneInfo("Europe/Bucharest")
MIN_ROWS = 4
GONE_AFTER_MISSES = 2
MIN_CONFIDENCE = 0.5  # rows below this never create/change services or emit events
JITTER_MIN = 10  # sched_time misread tolerance (minutes) for matching a listed service
STALE_MIN = 30  # listed services unseen this long are retired silently
SCHEMA_VERSION = 2
HISTORY_MAX = 500  # history() returns at most HISTORY_MAX + 1 rows (the extra one flags truncation)

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
    last_read TEXT,
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


MAX_KEY_LEN = 256
MAX_FOLLOWS = 20


@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: str
    auth: str


def _iso(d: date | str) -> str:
    return d if isinstance(d, str) else d.isoformat()


def _today() -> date:
    """Today in Europe/Bucharest (patched in tests)."""
    return datetime.now(TZ).date()


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
            if version == 0:  # fresh database: full current schema
                self._conn.executescript(
                    "BEGIN;" + _SCHEMA + f"PRAGMA user_version = {SCHEMA_VERSION};COMMIT;")
                return
            # v1 -> v2: services.last_read (ts of the last confident reading).
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(services)")}
            add = "" if "last_read" in cols else "ALTER TABLE services ADD COLUMN last_read TEXT;"
            self._conn.executescript(
                "BEGIN;" + _SCHEMA + add + f"PRAGMA user_version = {SCHEMA_VERSION};COMMIT;")

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

    def _jitter_candidates(self, r: Row, sd: str) -> list[tuple[timedelta, sqlite3.Row]]:
        """Listed services of the same train/board within JITTER_MIN minutes of `r`.

        The scheduled time never changes legitimately, so a near miss is an OCR
        misread of the same service.
        """
        target = datetime.combine(date.fromisoformat(sd), _hm(r.sched_time))
        d = date.fromisoformat(sd)
        cands = self._conn.execute(
            "SELECT * FROM services WHERE status='listed' AND board=? AND train_no=?"
            " AND service_date IN (?,?,?) ORDER BY id",
            (r.board, r.train_no, (d - timedelta(days=1)).isoformat(), sd,
             (d + timedelta(days=1)).isoformat()),
        ).fetchall()
        out = []
        for s in cands:
            at = datetime.combine(date.fromisoformat(s["service_date"]), _hm(s["sched_time"]))
            diff = abs(at - target)
            if diff <= timedelta(minutes=JITTER_MIN):
                out.append((diff, s))
        return out

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
        # Pass 2: sched_time jitter for the unmatched rows. Claim globally by
        # smallest |delta sched_time| (ties: row order, then service id) so the
        # outcome does not depend on the order of the incoming rows.
        pairs = []
        for i, (r, sd, cur) in enumerate(matches):
            if cur is None:
                for diff, s in self._jitter_candidates(r, sd):
                    pairs.append((diff, i, s["id"], s))
        pairs.sort(key=lambda p: p[:3])
        done: set[int] = set()
        for _diff_, i, sid_, s in pairs:
            if i in done or sid_ in seen:
                continue
            done.add(i)
            seen.add(sid_)
            matches[i] = (matches[i][0], matches[i][1], s)

        for r, sd, cur in matches:
            if cur is None:
                sid = c.execute(
                    "INSERT INTO services(board, service_date, train_type, train_no, station,"
                    " operator, sched_time, first_seen, last_seen, last_delay, last_platform,"
                    " flagged, status, miss_count, last_read)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'listed',0,?)",
                    (r.board, sd, r.train_type, r.train_no, r.station, r.operator,
                     r.sched_time, ts_s, ts_s, r.delay_min, r.platform, int(r.flagged), ts_s),
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
                " last_delay=?, last_platform=?, flagged=?, status='listed', miss_count=0,"
                " last_read=? WHERE id=?",
                (r.train_type, r.station, r.operator, ts_s, r.delay_min, r.platform,
                 int(r.flagged), ts_s, sid),
            )

        # Low-confidence rows: only keep an exactly matching service alive.
        for r in low:
            cur = self._find_exact(r, service_date(r.sched_time, local).isoformat())
            if cur is not None and cur["status"] == "listed" and cur["id"] not in seen:
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
                " last_delay, last_platform, flagged, status, service_date FROM services"
                " WHERE status='listed' ORDER BY service_date, sched_time, train_no"
            ).fetchall()
        for s in rows:
            out[_BOARD_KEYS[s["board"]]].append({
                "train_type": s["train_type"], "train_no": s["train_no"],
                "station": s["station"], "operator": s["operator"],
                "sched_time": s["sched_time"], "delay_min": s["last_delay"],
                "platform": s["last_platform"], "flagged": bool(s["flagged"]),
                "status": s["status"], "service_date": s["service_date"],
            })
        return out

    def last_ok_age(self, now: datetime) -> float | None:
        with self._lock:
            ts = self._last_ok_ts()
        if ts is None:
            return None
        return (_local(now) - datetime.fromisoformat(ts)).total_seconds()

    # -- history ----------------------------------------------------------

    def history(self, day: date, train: int | None = None, station: str | None = None,
                board: str | None = None, time_from: str | None = None,
                time_to: str | None = None) -> list[dict]:
        """One dict per service of `day`, ordered by sched_time then board.

        `station` is a case/diacritics-insensitive substring (LIKE wildcards are
        matched literally). `time_from`/`time_to` are inclusive "HH:MM" bounds,
        compared as strings (zero-padded HH:MM sorts chronologically; a malformed
        bound simply compares lexicographically). `max_delay` covers every delay
        seen: the current one plus the old/new values of all delay events.
        """
        where, args = ["s.service_date = ?"], [day.isoformat()]
        if train is not None:
            where.append("s.train_no = ?")
            args.append(train)
        if board is not None:
            where.append("s.board = ?")
            args.append(board)
        if station is not None:
            q = clean_station(station) or station.strip().upper()
            esc = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            where.append("s.station LIKE ? ESCAPE '!'")
            args.append(f"%{esc}%")
        if time_from is not None:
            where.append("s.sched_time >= ?")
            args.append(time_from)
        if time_to is not None:
            where.append("s.sched_time <= ?")
            args.append(time_to)
        sql = (
            "SELECT s.board, s.train_type, s.train_no, s.station, s.operator, s.sched_time,"
            " s.last_delay, s.last_platform, s.status, s.first_seen, s.last_seen,"
            " (SELECT MAX(MAX(COALESCE(CAST(e.old AS INTEGER), 0),"
            "                 COALESCE(CAST(e.new AS INTEGER), 0)))"
            "    FROM events e WHERE e.service_id = s.id AND e.kind = 'delay') AS ev_max"
            " FROM services s WHERE " + " AND ".join(where) +
            " ORDER BY s.sched_time, s.board, s.train_no LIMIT " + str(HISTORY_MAX + 1)
        )
        with self._lock:
            found = self._conn.execute(sql, args).fetchall()
        return [{
            "board": s["board"], "train_type": s["train_type"], "train_no": s["train_no"],
            "station": s["station"], "operator": s["operator"], "sched_time": s["sched_time"],
            "max_delay": max(s["last_delay"] or 0, s["ev_max"] or 0),
            "final_delay": s["last_delay"] or 0, "platform": s["last_platform"],
            "status": s["status"], "first_seen": s["first_seen"], "last_seen": s["last_seen"],
        } for s in found]

    def train_events(self, train_no: int, day: date) -> list[dict]:
        """Events of every service of `train_no` on `day`, chronological."""
        with self._lock:
            found = self._conn.execute(
                "SELECT e.ts, e.kind, e.old, e.new, s.board, s.sched_time, s.station"
                " FROM events e JOIN services s ON s.id = e.service_id"
                " WHERE s.train_no = ? AND s.service_date = ? ORDER BY e.ts, e.id",
                (train_no, day.isoformat()),
            ).fetchall()
        return [dict(r) for r in found]

    # -- notifier support -------------------------------------------------

    def last_ok_run_id(self) -> int | None:
        """Id of the latest successful reading (advances once per ok ingest)."""
        with self._lock:
            r = self._conn.execute("SELECT MAX(id) FROM runs WHERE ok=1").fetchone()
        return r[0]

    def last_ok_run(self) -> tuple[int, str] | None:
        """(id, ts) of the latest successful reading."""
        with self._lock:
            r = self._conn.execute(
                "SELECT id, ts FROM runs WHERE ok=1 ORDER BY id DESC LIMIT 1").fetchone()
        return (r[0], r[1]) if r else None

    def service_state(self, board: str, service_date: str, train_no: int,
                      sched_time: str) -> dict | None:
        """Current {status, delay, platform, last_read, last_seen} of one service, or None.

        `last_read` is the ts of the last ok run that matched the service with a
        confident row (low-confidence sightings do not update it).
        """
        with self._lock:
            s = self._conn.execute(
                "SELECT status, last_delay, last_platform, last_read, last_seen FROM services"
                " WHERE board=?"
                " AND service_date=? AND train_no=? AND sched_time=?",
                (board, service_date, train_no, sched_time),
            ).fetchone()
        if s is None:
            return None
        return {"status": s["status"], "delay": s["last_delay"],
                "platform": s["last_platform"], "last_read": s["last_read"],
                "last_seen": s["last_seen"]}

    # -- subscriptions & follows -----------------------------------------

    def subscribe(self, endpoint: str, p256dh: str, auth: str) -> int:
        check_push_endpoint(endpoint)
        for k in (p256dh, auth):
            if not isinstance(k, str) or not k or len(k) > MAX_KEY_LEN:
                raise ValueError("cheie invalidă")
        with self._lock:
            self._conn.execute(
                "INSERT INTO subscriptions(endpoint, p256dh, auth, created_at) VALUES (?,?,?,?)"
                " ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh, auth=excluded.auth",
                (endpoint, p256dh, auth, datetime.now(TZ).isoformat()),
            )
            return self._conn.execute("SELECT id FROM subscriptions WHERE endpoint=?",
                                      (endpoint,)).fetchone()[0]

    def unsubscribe(self, endpoint: str) -> None:
        with self._lock:  # follows go via ON DELETE CASCADE
            self._conn.execute("DELETE FROM subscriptions WHERE endpoint=?", (endpoint,))

    def _sub_id(self, endpoint: str) -> int | None:
        r = self._conn.execute("SELECT id FROM subscriptions WHERE endpoint=?",
                               (endpoint,)).fetchone()
        return r[0] if r else None

    def follow(self, endpoint: str, train_no: int, date: date | str, *,
               today: date | None = None) -> None:
        """Follow a train for one service date.

        Only follows dated `today - 1` or later count towards MAX_FOLLOWS; older
        ones of this subscription are deleted here (lazy cleanup). `today`
        defaults to the current date in Europe/Bucharest.
        """
        day = _iso(date)
        cutoff = ((today or _today()) - timedelta(days=1)).isoformat()
        with self._lock:
            c = self._conn
            c.execute("BEGIN IMMEDIATE")
            try:
                sid = self._sub_id(endpoint)
                if sid is None:
                    raise ValueError("abonare necunoscută")
                c.execute("DELETE FROM follows WHERE subscription_id=? AND service_date < ?",
                          (sid, cutoff))
                exists = c.execute(
                    "SELECT 1 FROM follows WHERE subscription_id=? AND train_no=?"
                    " AND service_date=?", (sid, train_no, day)).fetchone()
                if not exists:
                    n = c.execute("SELECT COUNT(*) FROM follows WHERE subscription_id=?",
                                  (sid,)).fetchone()[0]
                    if n >= MAX_FOLLOWS:
                        raise ValueError(f"limită de {MAX_FOLLOWS} de trenuri")
                    c.execute("INSERT INTO follows(subscription_id, train_no, service_date)"
                              " VALUES (?,?,?)", (sid, train_no, day))
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def unfollow(self, endpoint: str, train_no: int, date: date | str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM follows WHERE train_no=? AND service_date=? AND subscription_id ="
                " (SELECT id FROM subscriptions WHERE endpoint=?)",
                (train_no, _iso(date), endpoint))

    def followers(self, train_no: int, date: date | str) -> list[Subscription]:
        with self._lock:
            found = self._conn.execute(
                "SELECT s.endpoint, s.p256dh, s.auth FROM follows f"
                " JOIN subscriptions s ON s.id = f.subscription_id"
                " WHERE f.train_no=? AND f.service_date=? ORDER BY s.id",
                (train_no, _iso(date))).fetchall()
        return [Subscription(r["endpoint"], r["p256dh"], r["auth"]) for r in found]

    def list_follows(self, endpoint: str) -> list[dict]:
        with self._lock:
            found = self._conn.execute(
                "SELECT f.train_no, f.service_date FROM follows f"
                " JOIN subscriptions s ON s.id = f.subscription_id"
                " WHERE s.endpoint=? ORDER BY f.rowid", (endpoint,)).fetchall()
        return [{"train_no": r["train_no"], "date": r["service_date"]} for r in found]
