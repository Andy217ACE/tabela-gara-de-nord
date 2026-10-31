# © 2026 Andy217Ace
"""SQLite persistence: runs, services (one per train/day/board), events.

`ingest` diffs a validated board reading against the stored state and emits
`Event`s (appeared / delay / platform / gone). Each panel (arrivals/departures)
is judged on its own: a panel with too few rows, or a partial read (suddenly
under half of its last good row count), is rejected for that frame and keeps
its last good state (nothing on it goes GONE); the other panel is still
ingested. A frame where no panel is usable is a failed run (`ok=0`).
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
from collections import deque
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from time import monotonic
from zoneinfo import ZoneInfo

from app import consensus, quality
from app.canonical import _lev, near_name, seed_stations
from app.endpoints import MAX_ENDPOINT_LEN, check_push_endpoint  # noqa: F401
from app.models import Event, Row
from app.normalize import clean_station
from app.weather import utc_iso

log = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Bucharest")
MIN_ROWS = 4  # a frame needs at least this many confident rows on its accepted panels
MIN_BOARD_ROWS = 2  # ...and each accepted panel at least this many
PARTIAL_BASE = 6  # the partial-read guard applies once a panel had this many rows
PARTIAL_FRAC = 0.5  # a panel suddenly under this share of its last good count is partial
PARTIAL_ACCEPT_AFTER = 10  # ...unless it stays that small this many frames (it really shrank)
CONFIRM_CONFIDENCE = 0.7  # a NEW service read below this needs a second consecutive reading
RENAME_AFTER = 3  # a stored misread is renamed after at least this many readings of the other key
RENAME_WINDOW = 10  # ...that are also RENAME_SHARE of the last RENAME_WINDOW readings of it
RENAME_SHARE = 0.7  # (a vote, not "3 in a row": 7917->7914->791->7914 ping-pong stops)
# ...to a number with FEWER digits (a glare-truncated read: 1571 -> 157) only on an
# overwhelming vote; a longer stored number can itself be the misread (9209 -> 92011)
RENAME_FEWER_AFTER = 8
RENAME_FEWER_SHARE = 0.9
BOARDS = ("arrival", "departure")
GONE_AFTER_MISSES = 3  # OCR alternating between variants made 2 flap (data-quality report)
PANEL_ROWS = 12  # the physical CFR panel always shows this many rows; a frame with all of
# them read is complete, and LIVE then shows only the services read in it (see current_board)
REAPPEAR_QUIET_MIN = 10  # back on the board within this many minutes: no new 'appeared'
MIN_CONFIDENCE = 0.5  # rows below this never create/change services or emit events
JITTER_MIN = 10  # sched_time misread tolerance (minutes) for matching a listed service
STALE_MIN = 30  # listed services unseen this long are retired silently
SCHEMA_VERSION = 9
KNOWN_STATIONS_MAX = 2000  # cap on stations learned from the history
COEXIST_RECHECK_S = 600  # a cached "never read together" (see Store._coexist) is re-queried after this many seconds
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
    operator_raw TEXT NOT NULL DEFAULT '',
    station_raw TEXT NOT NULL DEFAULT '',
    uncertain INTEGER NOT NULL DEFAULT 0,
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

# Columns added after v1, in order: (column, definition). Old databases get the
# missing ones via ALTER TABLE (guarded by PRAGMA table_info, so re-runnable).
_ADDED_COLUMNS = (
    ("last_read", "TEXT"),                              # v2
    ("operator_raw", "TEXT NOT NULL DEFAULT ''"),       # v3: OCR text as read
    ("station_raw", "TEXT NOT NULL DEFAULT ''"),        # v3
    ("uncertain", "INTEGER NOT NULL DEFAULT 0"),        # v3: name not matched
)

# v4: Open-Meteo `current` values (app/weather.py), one row per observation time (UTC).
# NULL = value missing (never 0). History is permanent (~96 rows/day).
_WEATHER_SCHEMA = """
CREATE TABLE IF NOT EXISTS weather_observations (
    id INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL UNIQUE,
    fetched_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'open-meteo',
    kind TEXT NOT NULL DEFAULT 'model_current',
    latitude REAL,
    longitude REAL,
    temperature_c REAL,
    apparent_temperature_c REAL,
    precipitation_mm REAL,
    weather_code INTEGER,
    wind_speed_kmh REAL,
    wind_direction_deg REAL,
    units_json TEXT,
    raw_json TEXT
);
"""
# v8: the richer Open-Meteo request (additive ALTER TABLE ADD COLUMN, all nullable, no
# defaults: old rows read NULL = "not recorded", never 0). `hourly_json` = the next-24 h
# temperature series, kept only on the newest observation (see add_weather).
_WEATHER_V8_COLUMNS = (
    ("relative_humidity_pct", "REAL"),
    ("is_day", "INTEGER"),
    ("rain_mm", "REAL"),
    ("showers_mm", "REAL"),
    ("snowfall_cm", "REAL"),
    ("surface_pressure_hpa", "REAL"),
    ("wind_gusts_kmh", "REAL"),
    ("hourly_json", "TEXT"),
)
_WEATHER_COLS = ("observed_at", "fetched_at", "source", "kind", "latitude", "longitude",
                 "temperature_c", "apparent_temperature_c", "precipitation_mm", "weather_code",
                 "wind_speed_kmh", "wind_direction_deg", "units_json", "raw_json",
                 ) + tuple(c for c, _ in _WEATHER_V8_COLUMNS)


# An unreadable delay cell shows the last safe reading of the train only this long
# (trains move up the board; the reading may be out of date). Beyond it: "necitit".
DELAY_LAST_READ_MAX_S = 15 * 60


def _last_read_age(stamp: str | None, now: datetime) -> float | None:
    """Seconds since the stored delay reading, when it is at most DELAY_LAST_READ_MAX_S old."""
    if not stamp:
        return None
    try:
        at = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    age = (now - at).total_seconds()
    return round(age) if 0 <= age <= DELAY_LAST_READ_MAX_S else None


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


def _fold_station(s: str | None) -> str:
    """Station name reduced to letters and digits: "KIEV - CHISINAU" == "KIEV -CHISINAU"."""
    return re.sub(r"[^A-Z0-9]+", "", (s or "").upper())


def _same_station(st_a: str, raw_a: str, st_b: str, raw_b: str) -> bool:
    """Same station, canonical or as read, ignoring spaces/hyphens placement."""
    return bool((st_a and st_a == st_b) or (raw_a and raw_a == raw_b)
                or (_fold_station(st_a) and _fold_station(st_a) == _fold_station(st_b))
                or (_fold_station(raw_a) and _fold_station(raw_a) == _fold_station(raw_b)))


def _near_dup(a: tuple, b: tuple) -> bool:
    """Are (train_no, sched_time, station, station_raw) `a` and `b` one service read
    twice, one of them with a misread number or time?

    Same key, or: same station (canonical or as read; spacing of spaces/hyphens
    ignored) and either
    - the same scheduled time and a train number one edit apart, or two edits apart
      when the lengths differ (a lost or added glyph on top of another one: 9209 /
      92011, 925 / 92511, 10157 / 157, 5019 / 19 — measured on the live history, always
      one board row read twice); two substitutions of the same length stay distinct
      (7914 / 7938 are two real trains), or
    - the same train number and a scheduled time one or two characters apart
      (06:52 / 05:52, 01:10 / 01:49): a train is listed once per panel and day.
    More differences, or another station: distinct (two rows read in the same frame
    are told apart by the callers anyway).
    """
    (no_a, t_a, st_a, raw_a), (no_b, t_b, st_b, raw_b) = a, b
    if no_a == no_b and t_a == t_b:
        return True
    if not _same_station(st_a, raw_a, st_b, raw_b):
        return False
    sa, sb = str(no_a), str(no_b)
    if no_a == no_b:
        return 1 <= _lev(t_a, t_b) <= 2
    if t_a != t_b:
        return False
    d_no = _lev(sa, sb)
    return d_no == 1 or (d_no == 2 and len(sa) != len(sb))


def _protect_learned(names: list[str]) -> list[str]:
    """Learned station names (most frequent first) minus probable misreads: anything
    but letters/digits/spaces/hyphens ("PLOIEST! SUD", "TIMISOA.RA NORD"), and any name
    one or two characters away from a seed station or from a more frequent learned name
    ("AD JUD" next to ADJUD, "LASI" next to IASI)."""
    seed = seed_stations()
    kept: list[str] = []
    for n in names:
        if not _LEARNABLE.fullmatch(n):
            continue
        if any(near_name(n, k) for k in (*seed, *kept) if k != n):
            continue
        kept.append(n)
    return kept


def _dedup(rows: list) -> list:
    """Listed services with near-duplicates (see `_near_dup`) on the same panel
    collapsed: the most recently seen one stays, at the first one's position.
    Two services read in the same frame (equal last_seen) are distinct trains."""
    kept: list = []
    for s in rows:
        me = (s["train_no"], s["sched_time"], s["station"], s["station_raw"])
        for i, k in enumerate(kept):
            if (k["board"], k["service_date"]) == (s["board"], s["service_date"]) and (
                    k["last_seen"] != s["last_seen"]) and _near_dup(
                    (k["train_no"], k["sched_time"], k["station"], k["station_raw"]), me):
                if s["last_seen"] > k["last_seen"]:
                    kept[i] = s
                break
        else:
            kept.append(s)
    return kept


_LEARNABLE = re.compile(r"[A-Z0-9]+(?:[ -][A-Z0-9]+)*")
MAX_KEY_LEN = 256
MAX_FOLLOWS = 20


@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: str
    auth: str


def _iso(d: date | str) -> str:
    return d if isinstance(d, str) else d.isoformat()


def _backfill_delay_read_at(c: sqlite3.Connection) -> None:
    """Set delay_read_at for services stored before v6 from observations with
    delay_read=1 only (v5+, both 0 and non-zero readings). Older evidence (delay
    events, non-zero last_delay) exists only for DELAYED trains: using it would bias
    the statistics towards delays, so those services keep NULL (delay unknown)."""
    has_obs = c.execute("SELECT 1 FROM sqlite_master WHERE type='table'"
                        " AND name='observations'").fetchone()
    if not has_obs:
        return
    upd = []
    # only readings the store applied: confident rows whose value is the stored one
    for sid, at in c.execute("SELECT o.service_id, MAX(o.observed_at) FROM observations o"
                             " JOIN services s ON s.id = o.service_id"
                             " WHERE o.delay_read=1 AND o.validation_state IN ('ok','uncertain')"
                             " AND o.delay_min = s.last_delay"
                             " GROUP BY o.service_id").fetchall():
        try:
            t = _local(datetime.fromisoformat(at.replace("Z", "+00:00")))
        except (ValueError, AttributeError):
            continue
        upd.append((t.isoformat(), sid))
    c.executemany("UPDATE services SET delay_read_at=? WHERE id=? AND delay_read_at IS NULL", upd)


def _today() -> date:
    """Today in Europe/Bucharest (patched in tests)."""
    return datetime.now(TZ).date()


def _clean_delays(s: sqlite3.Row) -> dict:
    """max_delay / final_delay of one history row: the confirmed values of a service
    checked retroactively (when any was confirmed), else the stored ones without the
    suspect events."""
    if s["delay_checked"]:
        if s["last_delay_clean"] is None:  # no value confirmed: unknown, never 0
            return {"max_delay": None, "final_delay": None, "delay_seen": False}
        return {"max_delay": max(s["max_delay_clean"] or 0, s["last_delay_clean"]),
                "final_delay": s["last_delay_clean"]}
    return {"max_delay": max(s["last_delay"] or 0, s["ev_max"] or 0),
            "final_delay": s["last_delay"] or 0}


class Store:
    service_date = staticmethod(service_date)

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._known_cache: tuple | None = None  # ((day, min_services, min_days), names)
        # service id -> was the delay readable in the latest confident reading of it?
        # In memory only (no schema change): a missing id means the stored last_delay
        # came from a real reading. After a restart the first poll refreshes it.
        self._delay_read: dict[int, bool] = {}
        self._pending_read: dict[int, bool] = {}
        # Per panel, in memory (no schema change; after a restart they are rebuilt
        # from the listed services / the last ok run): last accepted row count,
        # time of the last accepted reading, consecutive partial-read frames.
        self._good_count: dict[str, int] = {}
        self._board_ok: dict[str, str] = {}
        self._partial_streak: dict[str, int] = {}
        # panel -> was its last frame accepted with all PANEL_ROWS rows read? (in memory;
        # empty after a restart: nothing is hidden until a complete frame is read again)
        self._complete: dict[str, bool] = {}
        # (board, service_date, train_no, sched_time) -> first ts of a low-confidence
        # reading of a new service, awaiting a second consecutive reading.
        self._pending_new: dict[tuple, str] = {}
        self._pending_new_next: dict[tuple, str] = {}
        # service id -> ((train_no, sched_time) read instead of the stored one, frames in
        # a row): a stored misread is renamed once the other reading persists.
        # service id -> last RENAME_WINDOW (train_no, sched_time) keys read for it (vote)
        self._votes: dict[int, deque] = {}
        # service id -> confident readings matched to it (seeded from its observations)
        self._nreads: dict[int, int] = {}
        # (kind, service id) -> (board, value read, consecutive frames): a delay/platform
        # change is applied (and its event emitted) only once confirmed (app.quality).
        self._cand: dict[tuple[str, int], tuple[str, object, int]] = {}
        self._cand_next: dict[tuple[str, int], tuple[str, object, int]] = {}
        # slot coexistence of two train numbers (app.quality.coexisting_numbers with a
        # sched_time), per (low, high, sched_time): True is permanent (coexistence never
        # ends); "never together" expires after COEXIST_RECHECK_S, or at once when a frame
        # reads both on one board at that time
        self._together: set[tuple[int, int, str]] = set()
        self._apart: dict[tuple[int, int, str], float] = {}  # key -> monotonic expiry
        # (board, sched_time) -> numbers read there in this frame
        self._frame_nos: dict[tuple[str, str], set[int]] = {}
        self.last_ghost_numbers: set[int] = set()  # train numbers flagged ghost by the last ingest
        self.last_rejected: dict[str, str] = {}  # panel -> reason, from the last ingest()
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
        """Version ladder: each step is additive and atomic together with its version bump
        (a failure leaves the previous version in place), so re-running is safe.
        Never renumber a step."""
        with self._lock:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if 0 < version < SCHEMA_VERSION:  # backup-aware: a copy exists before any change
                from app import dbbackup
                dbbackup.ensure(self.path, version)
            if version < 3:
                self._migrate_to_3(version)
            if version < 4:
                self._migrate_to_4()
            if version < 5:
                from app.observations import migrate_to_5  # v5: captures/observations/trains
                migrate_to_5(self._conn)
            if version < 6:
                self._migrate_to_6()
            if version < 7:  # v7: data-quality tables (app.quality)
                quality.migrate_to_7(self._conn)
            if version < 8:  # v8: rich weather columns
                self._migrate_to_8()
            if version < 9:  # v9: manual corrections (app.corrections)
                from app import corrections
                corrections.migrate_to_9(self._conn)

    def _script(self, sql: str) -> None:
        try:
            self._conn.executescript(sql)
        except BaseException:
            if self._conn.in_transaction:
                self._conn.execute("ROLLBACK")
            raise

    def _migrate_to_3(self, version: int) -> None:
        if version == 0:  # fresh database: full v3 schema
            self._script("BEGIN;" + _SCHEMA + "PRAGMA user_version = 3;COMMIT;")
            return
        # v1/v2 -> v3: add the missing services columns, then bump the version,
        # all in one transaction (a failure leaves the old version in place).
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(services)")}
        add = "".join(f"ALTER TABLE services ADD COLUMN {name} {decl};"
                      for name, decl in _ADDED_COLUMNS if name not in cols)
        self._script("BEGIN;" + _SCHEMA + add + "PRAGMA user_version = 3;COMMIT;")

    def _migrate_to_4(self) -> None:
        """v3 -> v4: weather_observations (additive)."""
        self._script("BEGIN;" + _WEATHER_SCHEMA + "PRAGMA user_version = 4;COMMIT;")

    def _migrate_to_8(self) -> None:
        """v7 -> v8: the rich Open-Meteo columns on weather_observations (additive, nullable;
        existing rows keep every value and read NULL for the new ones), in one transaction
        with the version bump (a failure leaves v7 in place). Re-runnable."""
        c = self._conn
        c.execute("BEGIN IMMEDIATE")
        try:
            have = {r[1] for r in c.execute("PRAGMA table_info(weather_observations)")}
            for name, decl in _WEATHER_V8_COLUMNS:
                if name not in have:
                    c.execute(f"ALTER TABLE weather_observations ADD COLUMN {name} {decl}")
            c.execute("PRAGMA user_version = 8")
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise

    def _migrate_to_6(self) -> None:
        """v5 -> v6: services.delay_read_at (proof that the delay cell was read), backfilled
        only from real evidence, in one transaction with the version bump."""
        c = self._conn
        c.execute("BEGIN IMMEDIATE")
        try:
            cols = {r[1] for r in c.execute("PRAGMA table_info(services)")}
            if "delay_read_at" not in cols:
                c.execute("ALTER TABLE services ADD COLUMN delay_read_at TEXT")
            c.execute("CREATE INDEX IF NOT EXISTS ix_events_kind_service ON events(kind, service_id)")
            _backfill_delay_read_at(c)
            c.execute("PRAGMA user_version = 6")
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise

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

    def _last_count(self, board: str) -> int:
        if board not in self._good_count:  # after a restart: the listed services
            self._good_count[board] = self._conn.execute(
                "SELECT COUNT(*) FROM services WHERE status='listed' AND board=?",
                (board,)).fetchone()[0]
        return self._good_count[board]

    def _judge(self, good: list[Row]) -> tuple[dict[str, int], dict[str, str]]:
        """({accepted panel: confident rows}, {rejected panel: reason}) for one frame."""
        counts = {b: 0 for b in BOARDS}
        for r in good:
            counts[r.board] = counts.get(r.board, 0) + 1
        accepted: dict[str, int] = {}
        rejected: dict[str, str] = {}
        for b in BOARDS:
            n, base = counts[b], self._last_count(b)
            if n < MIN_BOARD_ROWS:
                rejected[b] = f"too few rows ({n})"
            elif (base >= PARTIAL_BASE and n < PARTIAL_FRAC * base
                  and self._partial_streak.get(b, 0) + 1 < PARTIAL_ACCEPT_AFTER):
                rejected[b] = f"partial read ({n} of {base} rows)"
            else:
                accepted[b] = n
        if accepted and sum(accepted.values()) < MIN_ROWS:
            total = sum(accepted.values())
            for b in accepted:
                rejected[b] = f"frame too small ({total} rows)"
            accepted = {}
        return accepted, rejected

    def _after_judge(self, accepted: dict[str, int], rejected: dict[str, str],
                     ts_s: str, read: dict[str, int] | None = None) -> None:
        """Panel bookkeeping, once the frame's transaction committed."""
        self.last_rejected = rejected
        read = read or {}
        for b in BOARDS:
            self._complete[b] = b in accepted and read.get(b, 0) >= PANEL_ROWS
        for b, n in accepted.items():
            self._good_count[b] = n
            self._board_ok[b] = ts_s
            self._partial_streak[b] = 0
        for b, why in rejected.items():
            if why.startswith("partial"):
                self._partial_streak[b] = self._partial_streak.get(b, 0) + 1
                log.warning("panel %s rejected: %s; keeping its last good state", b, why)

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
                self._note_frame(rows)
                good, low = self._split(rows)
                accepted, rejected = self._judge(good)
                read = {b: sum(1 for r in good + low if r.board == b) for b in BOARDS}
                if not accepted:
                    c.execute("INSERT INTO runs(ts, image_hash, ok, n_rows) VALUES (?,?,0,?)",
                              (ts_s, image_hash, len(rows)))
                    c.execute("COMMIT")
                    self._after_judge(accepted, rejected, ts_s, read)
                    return []
                c.execute("INSERT INTO runs(ts, image_hash, ok, n_rows) VALUES (?,?,1,?)",
                          (ts_s, image_hash, len(rows)))
                self._pending_read = {}
                good = [r for r in good if r.board in accepted]
                low = [r for r in low if r.board in accepted]
                events = self._diff(good, low, local, ts_s, tuple(accepted))
                c.execute("COMMIT")
                self._after_judge(accepted, rejected, ts_s, read)
                # pending new services of a rejected panel wait for its next reading
                self._pending_new = {**{k: v for k, v in self._pending_new.items()
                                        if k[0] not in accepted}, **self._pending_new_next}
                # a candidate waits while its panel is rejected; otherwise consecutive only
                self._cand = {**{k: v for k, v in self._cand.items() if v[0] not in accepted},
                              **self._cand_next}
                self._delay_read.update(self._pending_read)
                if len(self._delay_read) > 4000:  # bounded: old services drop out
                    self._delay_read = dict(self._pending_read)
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

    def _fuzzy_match(self, r: Row, sd: str, seen: set[int]) -> sqlite3.Row | None:
        """The listed service `r` is a one-character misread of, if exactly one fits.

        Same panel and service day, same station (canonical or as read), and either the train number
        differs by one edit at the same scheduled time, or the same number with the
        scheduled time differing by one character (06:52 read 05:52). Services
        already matched in this frame are real, distinct trains and never claimed.
        """
        cands = self._conn.execute(
            "SELECT * FROM services WHERE status='listed' AND board=? AND service_date=?"
            " ORDER BY id", (r.board, sd),
        ).fetchall()
        hits = [s for s in cands if s["id"] not in seen and _near_dup(
            (s["train_no"], s["sched_time"], s["station"], s["station_raw"]),
            (r.train_no, r.sched_time, r.station, r.station_raw))]
        if len(hits) != 1 or self._coexist(r.train_no, hits[0]["train_no"], r.sched_time):
            return None  # (a train once read beside r's number, same time, is another train)
        return hits[0]

    def _in_frame(self, k: tuple) -> bool:
        return any(k[0] in s and k[1] in s
                   for (_b, t), s in self._frame_nos.items() if t == k[2])

    def _note_frame(self, rows: list[Row]) -> None:
        """The numbers read per (board, sched_time) slot in this frame (all rows, as recorded
        in observations): a cached "never together" pair read in one slot here becomes
        coexisting at once."""
        self._frame_nos = {}
        for r in rows:
            if r.train_no is not None:
                self._frame_nos.setdefault((r.board, r.sched_time), set()).add(int(r.train_no))
        for k in [k for k in self._apart if self._in_frame(k)]:
            del self._apart[k]
            self._together.add(k)

    def _coexist(self, a: int, b: int, sched_time: str) -> bool:
        """Were train numbers `a` and `b` ever read in one capture on one board, both at
        `sched_time` (two real trains in one slot, 5011/5014 04:47;
        app.quality.coexisting_numbers), this frame included? Slot level on purpose: two
        neighbouring trains at different times are on the board together all the time, and
        a misread of one into the other's number must still match. Cached per (pair, time);
        queried only for a cross-number candidate, at most once per COEXIST_RECHECK_S."""
        if a is None or b is None or int(a) == int(b):
            return False
        k = (min(int(a), int(b)), max(int(a), int(b)), sched_time)
        if k in self._together:
            return True
        if self._in_frame(k):
            self._apart.pop(k, None)
            self._together.add(k)
            return True
        now = monotonic()
        if self._apart.get(k, 0.0) > now:
            return False
        if len(self._apart) > 4000 or len(self._together) > 4000:  # bounded
            self._apart, self._together = {}, set()
        if quality.coexisting_numbers(self._conn, k[0], [k[1]], sched_time=sched_time):
            self._apart.pop(k, None)
            self._together.add(k)
            return True
        self._apart[k] = now + COEXIST_RECHECK_S
        return False

    def _vote(self, sid: int, key: tuple) -> None:
        if len(self._votes) > 4000:  # bounded: old services drop out
            self._votes = {}
        self._votes.setdefault(sid, deque(maxlen=RENAME_WINDOW)).append(key)
        self._nreads[sid] = self._reads(sid) + 1

    def _reads(self, sid: int) -> int:
        if sid not in self._nreads:
            if len(self._nreads) > 4000:
                self._nreads = {}
            self._nreads[sid] = quality._obs_count(self._conn, [sid]).get(sid, 0)
        return self._nreads[sid]

    def _maybe_rename(self, r: Row, s: sqlite3.Row) -> sqlite3.Row:
        """Service `s` (matched to a reading of another key), renamed to `r`'s
        (train_no, sched_time) once that key is the clear majority of its recent
        readings: at least RENAME_AFTER of them and RENAME_SHARE of the last
        RENAME_WINDOW. The FIRST reading of a train may itself have been the misread,
        and follows/notifications go by the train number. To a number with fewer
        digits (a truncated read: 1571 -> 157) only on an overwhelming vote
        (RENAME_FEWER_*), never onto an existing key."""
        var, cur = (r.train_no, r.sched_time), (s["train_no"], s["sched_time"])
        votes = self._votes.get(s["id"], ())
        n = sum(1 for v in votes if v == var)
        fewer = len(str(var[0])) < len(str(cur[0]))
        if (var == cur or n < RENAME_AFTER or n < RENAME_SHARE * len(votes)
                or r.confidence < CONFIRM_CONFIDENCE
                or (fewer and (n < RENAME_FEWER_AFTER or n < RENAME_FEWER_SHARE * len(votes)))
                or self._conn.execute(
                    "SELECT 1 FROM services WHERE board=? AND service_date=? AND train_no=?"
                    " AND sched_time=?", (s["board"], s["service_date"], *var)).fetchone()):
            return s
        self._conn.execute("UPDATE services SET train_no=?, sched_time=? WHERE id=?",
                           (*var, s["id"]))
        log.warning("service %d renamed %s %s -> %s %s (%d of the last %d readings)",
                    s["id"], s["train_no"], s["sched_time"], *var, n, len(votes))
        return self._conn.execute("SELECT * FROM services WHERE id=?", (s["id"],)).fetchone()

    def _majority_partner(self, cur: sqlite3.Row, seen: set[int],
                          listed: list[sqlite3.Row]) -> sqlite3.Row | None:
        """A listed one-character variant of `cur` (same panel/day, see `_near_dup`), not
        read in this frame, with more readings than `cur`: the same board row, which the
        OCR alternates between two keys (R 9209 / R 92011 for hours at night), unless the
        two numbers were ever read together in that slot (`_coexist`). The
        reading goes to the majority; the minority one then leaves the board as a ghost."""
        me = (cur["train_no"], cur["sched_time"], cur["station"], cur["station_raw"])
        best = None
        for p in listed:
            if (p["id"] == cur["id"] or p["id"] in seen or p["board"] != cur["board"]
                    or p["service_date"] != cur["service_date"]):
                continue
            if not _near_dup((p["train_no"], p["sched_time"], p["station"], p["station_raw"]),
                             me):
                continue
            if self._reads(p["id"]) > self._reads(cur["id"]) and (
                    best is None or self._reads(p["id"]) > self._reads(best["id"])) and (
                    not self._coexist(cur["train_no"], p["train_no"], cur["sched_time"])):
                best = p
        return best

    def _diff(self, good: list[Row], low: list[Row], local: datetime,
              ts_s: str, boards: tuple[str, ...] = BOARDS) -> list[Event]:
        c = self._conn
        events: list[Event] = []
        seen: set[int] = set()
        self._cand_next = {}
        self.last_ghost_numbers = set()

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
        # Pass 1b: an exact match on the minority key of a row the OCR alternates
        # between two listed services goes to the majority one.
        listed = c.execute("SELECT * FROM services WHERE status='listed'").fetchall()
        for i, (r, sd, cur) in enumerate(matches):
            if cur is None:  # (a minority service already gone is not revived either)
                continue
            p = self._majority_partner(cur, seen, listed)
            if p is not None:
                seen.discard(cur["id"])
                seen.add(p["id"])
                matches[i] = (r, sd, p)
                log.info("reading %s %s %s given to majority service %s %s (id %d, %d vs %d"
                         " readings)", r.board, r.train_no, r.sched_time, p["train_no"],
                         p["sched_time"], p["id"], self._reads(p["id"]), self._reads(cur["id"]))
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
        # Pass 3: one-character misreads of a listed service (train number or time).
        for i, (r, sd, cur) in enumerate(matches):
            if cur is None:
                s = self._fuzzy_match(r, sd, seen)
                if s is not None:
                    seen.add(s["id"])
                    matches[i] = (r, sd, s)
                    log.info("misread %s %s %s matched to listed service %s %s (id %d)",
                             r.board, r.train_no, r.sched_time, s["train_no"],
                             s["sched_time"], s["id"])
        # Vote: every matched reading counts for its service; a key that becomes the clear
        # majority of the recent readings renames it (see _maybe_rename).
        for i, (r, sd, cur) in enumerate(matches):
            if cur is not None:
                self._vote(cur["id"], (r.train_no, r.sched_time))
                matches[i] = (r, sd, self._maybe_rename(r, cur))

        self._pending_new_next = {}
        for r, sd, cur in matches:
            if cur is None:
                first = ts_s
                if r.confidence < CONFIRM_CONFIDENCE:
                    k = (r.board, sd, r.train_no, r.sched_time)
                    if k not in self._pending_new:  # wait for a second consecutive reading
                        self._pending_new_next[k] = ts_s
                        continue
                    first = self._pending_new[k]
                sid = c.execute(
                    "INSERT INTO services(board, service_date, train_type, train_no, station,"
                    " operator, sched_time, first_seen, last_seen, last_delay, last_platform,"
                    " flagged, status, miss_count, last_read, operator_raw, station_raw,"
                    " uncertain, delay_read_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'listed',0,?,?,?,?,?)",
                    (r.board, sd, r.train_type, r.train_no, r.station, r.operator,
                     r.sched_time, first, ts_s, r.delay_min, r.platform, int(r.flagged), ts_s,
                     r.operator_raw, r.station_raw, int(r.uncertain),
                     ts_s if r.delay_read else None),
                ).lastrowid
                seen.add(sid)
                self._vote(sid, (r.train_no, r.sched_time))
                self._pending_read[sid] = r.delay_read
                emit(sid, "appeared", r, sd)
                continue
            sid, sd = cur["id"], cur["service_date"]
            # the stored train number and sched_time win (a one-frame misread never
            # renames; only a reading that persists does, in _maybe_rename)
            row = replace(r, sched_time=cur["sched_time"], train_no=cur["train_no"])
            if cur["status"] == "gone":
                quality.clear_ghost(c, sid)
                away = local - datetime.fromisoformat(cur["last_seen"])
                if away > timedelta(minutes=REAPPEAR_QUIET_MIN):
                    emit(sid, "appeared", row, sd)
                else:  # a short absence (OCR flapping): same listing, no new event
                    log.info("service %d back on the board after %ds: no 'appeared'",
                             sid, away.total_seconds())
            # unreadable delay: keep the last real reading, no event, no overwrite;
            # a changed reading is applied only once confirmed (quality.delay_needs)
            delay = cur["last_delay"]
            self._pending_read[sid] = r.delay_read
            if r.delay_read and r.delay_min != delay:
                need = quality.delay_needs(r.delay_min, delay)
                if need == quality.DELAY_PLUS_CONFIRM:
                    log.info("delay %d of service %d looks like '+' read as a digit of %d:"
                             " waiting for %d readings", r.delay_min, sid, delay, need)
                if self._confirmed("delay", sid, cur["board"], r.delay_min, need):
                    emit(sid, "delay", row, sd, str(delay), str(r.delay_min))
                    delay = r.delay_min
            elif not r.delay_read and ("delay", sid) in self._cand:
                self._cand_next[("delay", sid)] = self._cand[("delay", sid)]  # held
            platform = cur["last_platform"]
            if r.platform != platform and self._confirmed(
                    "platform", sid, cur["board"], r.platform,
                    quality.platform_needs(platform, r.platform)):
                emit(sid, "platform", row, sd, _plat(platform), _plat(r.platform))
                platform = r.platform
            # proof of a reading (delay_read_at, v6) only from a value actually applied:
            # the stored one read again, or a change just confirmed (not a pending one)
            applied = r.delay_read and r.delay_min == delay
            names = (r.station, r.operator, r.station_raw, r.operator_raw, int(r.uncertain))
            if r.uncertain and not cur["uncertain"]:
                # Never replace names matched to a known value by unmatched OCR text.
                names = (cur["station"], cur["operator"], cur["station_raw"],
                         cur["operator_raw"], 0)
            c.execute(
                "UPDATE services SET train_type=?, station=?, operator=?, station_raw=?,"
                " operator_raw=?, uncertain=?, last_seen=?, last_delay=?, last_platform=?,"
                " flagged=?, status='listed', miss_count=0, last_read=?,"
                " delay_read_at=CASE WHEN ? THEN ? ELSE delay_read_at END WHERE id=?",
                (r.train_type, *names, ts_s, delay, platform,
                 int(r.flagged), ts_s, int(applied), ts_s, sid),
            )

        # Low-confidence rows: only keep an exactly matching service alive.
        for r in low:
            cur = self._find_exact(r, service_date(r.sched_time, local).isoformat())
            if cur is not None and cur["status"] == "listed" and cur["id"] not in seen:
                seen.add(cur["id"])
                c.execute("UPDATE services SET last_seen=?, miss_count=0 WHERE id=?",
                          (ts_s, cur["id"]))

        stale_before = local - timedelta(minutes=STALE_MIN)
        marks = ",".join("?" * len(boards))
        for s in c.execute(f"SELECT * FROM services WHERE status='listed' AND board IN ({marks})",
                           boards).fetchall():
            if s["id"] in seen:
                continue
            misses = s["miss_count"] + 1
            if datetime.fromisoformat(s["last_seen"]) < stale_before:
                # Not seen for a long time (e.g. downtime): retire without an event.
                c.execute("UPDATE services SET status='gone', miss_count=? WHERE id=?",
                          (misses, s["id"]))
                self._judge_ghost(s)
            elif misses >= GONE_AFTER_MISSES:
                c.execute("UPDATE services SET status='gone', miss_count=? WHERE id=?",
                          (misses, s["id"]))
                if not self._judge_ghost(s):  # a ghost leaving is no event, no push
                    emit(s["id"], "gone", self._row_of(s), s["service_date"])
            else:
                c.execute("UPDATE services SET miss_count=? WHERE id=?", (misses, s["id"]))
        return events

    def _confirmed(self, kind: str, sid: int, board: str, value, need: int) -> bool:
        """Count one more consecutive reading of `value` for (kind, sid); True once it
        reached `need` (the candidate is then cleared). A different value restarts."""
        prev = self._cand.get((kind, sid))
        n = prev[2] + 1 if prev and prev[1] == value else 1
        if n >= need:
            return True
        self._cand_next[(kind, sid)] = (board, value, n)
        return False

    def _judge_ghost(self, s: sqlite3.Row) -> bool:
        """A service leaving the board: flag it if it was a misread duplicate or a
        one-off sighting (app.quality.ghost_verdict). Never deletes anything."""
        verdict = quality.judge_ghost(self._conn, s["id"])
        if verdict is not None:
            self.last_ghost_numbers.add(s["train_no"])
            log.info("service %d (%s %s) flagged ghost: %s", s["id"], s["train_no"],
                     s["sched_time"], verdict[0])
        return verdict is not None

    @staticmethod
    def _row_of(s: sqlite3.Row) -> Row:
        return Row(board=s["board"], train_type=s["train_type"], train_no=s["train_no"],
                   station=s["station"], operator=s["operator"], sched_time=s["sched_time"],
                   delay_min=s["last_delay"], platform=s["last_platform"],
                   flagged=bool(s["flagged"]), operator_raw=s["operator_raw"],
                   station_raw=s["station_raw"], uncertain=bool(s["uncertain"]))

    # -- reads ------------------------------------------------------------

    def _last_ok_ts(self) -> str | None:
        r = self._conn.execute("SELECT ts FROM runs WHERE ok=1 ORDER BY id DESC LIMIT 1").fetchone()
        return r[0] if r else None

    def _trimmed_boards(self, now: datetime | None, stale_s: float | None) -> set[str]:
        """Panels whose LIVE list is cut to the services read in their last frame: that
        frame was accepted with all PANEL_ROWS rows read and is still fresh (with `now`
        and `stale_s`). A rejected, incomplete or stale panel keeps every listed service."""
        ages = self.board_ages(now) if now is not None and stale_s is not None else {}
        return {b for b in BOARDS if self._complete.get(b) and b not in self.last_rejected
                and (not ages or (ages[b] is not None and ages[b] <= stale_s))}

    def current_board(self, now: datetime | None = None, stale_s: float | None = None) -> dict:
        """The LIVE board. A service no longer read waits GONE_AFTER_MISSES frames before
        it is 'gone' (it stays listed in the database and the history meanwhile), but
        after a complete frame of its panel (see _trimmed_boards) it is not shown: the
        physical panel never has more than PANEL_ROWS rows."""
        with self._lock:
            out: dict = {"updated_at": self._last_ok_ts(), "arrivals": [], "departures": []}
            trimmed = self._trimmed_boards(now, stale_s)
            rows = self._conn.execute(
                "SELECT id, board, train_type, train_no, station, operator, sched_time,"
                " last_delay, last_platform, flagged, status, service_date, uncertain,"
                " station_raw, last_seen, miss_count, delay_read_at"
                " FROM services s"
                " WHERE status='listed' AND NOT " + quality.GHOST_SQL +
                " ORDER BY service_date, sched_time, train_no"
            ).fetchall()
            cons = consensus.service_consensus(self._conn, [s["id"] for s in rows])
        rows = [s for s in rows if not (s["board"] in trimmed and s["miss_count"] > 0)]
        now_local = _local(now or datetime.now(TZ))
        for s in _dedup(rows):
            # last safe reading of an unreadable delay: services are per train, so the
            # value follows the train when its row moves; shown only while recent
            c = cons.get(s["id"], {})  # the frames' vote; the stored value without one
            out[_BOARD_KEYS[s["board"]]].append({
                "delay_last_read_age_s": _last_read_age(s["delay_read_at"], now_local),
                "train_type": s["train_type"], "train_no": s["train_no"],
                "station": s["station"], "operator": s["operator"],
                "sched_time": s["sched_time"], "delay_min": c.get("delay", s["last_delay"]),
                "platform": c.get("platform", s["last_platform"]), "flagged": bool(s["flagged"]),
                "status": s["status"], "service_date": s["service_date"],
                "uncertain": bool(s["uncertain"]),
                "delay_read": self._delay_read.get(s["id"], True),
            })
        return out

    def board_ages(self, now: datetime) -> dict[str, float | None]:
        """Seconds since each panel's last accepted reading (None: never read).

        Kept in memory; until a panel is read after a restart, the last ok run stands in.
        """
        with self._lock:
            fallback = self._last_ok_ts()
            stamps = {b: self._board_ok.get(b, fallback) for b in BOARDS}
        loc = _local(now)
        return {b: None if ts is None else (loc - datetime.fromisoformat(ts)).total_seconds()
                for b, ts in stamps.items()}

    def last_ok_age(self, now: datetime) -> float | None:
        with self._lock:
            ts = self._last_ok_ts()
        if ts is None:
            return None
        return (_local(now) - datetime.fromisoformat(ts)).total_seconds()

    def known_stations(self, min_services: int = 2, min_days: int = 2) -> set[str]:
        """Station names learned from the history for canonicalisation.

        Only names stored exactly as OCR read them (``station = station_raw``, so
        never a corrected value and never a pre-v3 row without raw text), seen on at
        least `min_services` distinct trains on at least `min_days` distinct days:
        a one-off or one-day misread stays out. The curated seed is matched first by
        the reader, so it always wins. At most KNOWN_STATIONS_MAX names; computed
        once per (Bucharest) day — the poller asks before every image.
        """
        today = (_today(), datetime.now(TZ).hour)  # recomputed every hour, not once a day
        cached = self._known_cache
        if cached and cached[0] == (today, min_services, min_days):
            return set(cached[1])
        with self._lock:
            found = self._conn.execute(
                "SELECT station FROM services"
                " WHERE station != '' AND station_raw != '' AND station = station_raw"
                " GROUP BY station"
                " HAVING COUNT(DISTINCT train_no) >= ? AND COUNT(DISTINCT service_date) >= ?"
                " ORDER BY COUNT(*) DESC, station LIMIT ?",
                (min_services, min_days, KNOWN_STATIONS_MAX)).fetchall()
        names = frozenset(_protect_learned([r[0] for r in found]))
        self._known_cache = ((today, min_services, min_days), names)
        return set(names)

    # -- weather (schema v4) ----------------------------------------------

    def add_weather(self, obs: dict) -> bool:
        """Store one observation; False if that observed_at is already stored (kept as is)."""
        if not isinstance(obs.get("observed_at"), str) or not obs["observed_at"]:
            raise ValueError("observed_at lipsește")
        vals = [obs.get(c) for c in _WEATHER_COLS]
        vals[2] = vals[2] or "open-meteo"
        vals[3] = vals[3] or "model_current"
        with self._lock:
            cur = self._conn.execute(
                f"INSERT INTO weather_observations({', '.join(_WEATHER_COLS)})"
                f" VALUES ({', '.join('?' * len(_WEATHER_COLS))})"
                " ON CONFLICT(observed_at) DO NOTHING", vals)
            if cur.rowcount == 1 and obs.get("hourly_json"):
                # the next-24 h series is a forecast, not history: keep it on the newest
                # observation only (the table keeps ~96 rows/day for the statistics)
                self._conn.execute(
                    "UPDATE weather_observations SET hourly_json = NULL WHERE hourly_json"
                    " IS NOT NULL AND observed_at < (SELECT MAX(observed_at)"
                    " FROM weather_observations)")
            return cur.rowcount == 1

    def latest_weather(self) -> dict | None:
        """Newest observation (by observed_at), or None."""
        with self._lock:
            r = self._conn.execute("SELECT * FROM weather_observations"
                                   " ORDER BY observed_at DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    def weather_between(self, t0: datetime | str, t1: datetime | str) -> list[dict]:
        """Observations with t0 <= observed_at <= t1 (UTC), oldest first."""
        a = t0 if isinstance(t0, str) else utc_iso(t0)
        b = t1 if isinstance(t1, str) else utc_iso(t1)
        with self._lock:
            found = self._conn.execute(
                "SELECT * FROM weather_observations WHERE observed_at BETWEEN ? AND ?"
                " ORDER BY observed_at", (a, b)).fetchall()
        return [dict(r) for r in found]

    # -- history ----------------------------------------------------------

    def history(self, day: date, train: int | None = None, station: str | None = None,
                board: str | None = None, time_from: str | None = None,
                time_to: str | None = None) -> list[dict]:
        """One dict per service of `day`, ordered by sched_time then board.

        `station` is a case/diacritics-insensitive substring (LIKE wildcards are
        matched literally). `time_from`/`time_to` are inclusive "HH:MM" bounds,
        compared as strings (zero-padded HH:MM sorts chronologically; a malformed
        bound simply compares lexicographically). `max_delay` covers every confirmed
        delay: the current one plus the values of the delay events not marked suspect
        (app.quality); for services checked retroactively, the confirmed values only.
        Ghost services (misread duplicates, one-off sightings) are left out; station
        and operator are the canonical forms when a corrected one exists (raw kept).
        `low_quality` marks the reduced-quality (beta) period.
        """
        where, args = ["s.service_date = ?", "NOT " + quality.GHOST_SQL], [day.isoformat()]
        if train is not None:
            where.append("s.train_no = ?")
            args.append(train)
        if board is not None:
            where.append("s.board = ?")
            args.append(board)
        if station is not None:
            q = clean_station(station) or station.strip().upper()
            esc = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            where.append("COALESCE(q.station_canonical, s.station) LIKE ? ESCAPE '!'")
            args.append(f"%{esc}%")
        if time_from is not None:
            where.append("s.sched_time >= ?")
            args.append(time_from)
        if time_to is not None:
            where.append("s.sched_time <= ?")
            args.append(time_to)
        sql = (
            "SELECT s.id, s.board, s.train_type, s.train_no,"
            " COALESCE(q.station_canonical, s.station) AS station,"
            " COALESCE(q.operator_canonical, s.operator) AS operator, s.sched_time,"
            " s.last_delay, s.last_platform, s.status, s.first_seen, s.last_seen, s.uncertain,"
            " s.delay_read_at, q.delay_checked, q.max_delay_clean, q.last_delay_clean,"
            " q.low_quality,"
            " (SELECT MAX(MAX(COALESCE(CAST(e.old AS INTEGER), 0),"
            "                 COALESCE(CAST(e.new AS INTEGER), 0)))"
            "    FROM events e WHERE e.service_id = s.id AND e.kind = 'delay'"
            "    AND NOT " + quality.SUSPECT_EVENT_SQL + ") AS ev_max"
            " FROM services s LEFT JOIN service_quality q ON q.service_id = s.id"
            " WHERE " + " AND ".join(where) +
            " ORDER BY s.sched_time, s.board, s.train_no LIMIT " + str(HISTORY_MAX + 1)
        )
        with self._lock:
            found = self._conn.execute(sql, args).fetchall()
            cons = consensus.service_consensus(self._conn, [s["id"] for s in found])
        out = []
        for s in found:
            c = cons.get(s["id"], {})  # per-field vote over the train's frames (app.consensus)
            delays = _clean_delays(s)
            if "delay" in c and not s["delay_checked"]:
                delays = {"max_delay": max(s["ev_max"] or 0, c["delay"]),
                          "final_delay": c["delay"]}
            out.append({
                "id": s["id"], "delay_known": s["delay_read_at"] is not None,
                # display only: a delay was read at some point (pre-v6 delay events count);
                # statistics use delay_known (proof stored per journey)
                "delay_seen": s["delay_read_at"] is not None or (s["ev_max"] or 0) > 0
                or (s["last_delay"] or 0) > 0 or "delay" in c,
                "board": s["board"], "train_type": s["train_type"], "train_no": s["train_no"],
                "station": s["station"], "operator": s["operator"],
                "sched_time": s["sched_time"],
                **delays, "platform": c.get("platform", s["last_platform"]),
                "status": s["status"], "first_seen": s["first_seen"],
                "last_seen": s["last_seen"],
                "uncertain": bool(s["uncertain"]), "low_quality": bool(s["low_quality"]),
            })
        return out

    def train_events(self, train_no: int, day: date) -> list[dict]:
        """Events of every service of `train_no` on `day`, chronological. Events marked
        suspect (e.g. "+25" read as 425) and ghost services are left out (kept in the DB)."""
        with self._lock:
            found = self._conn.execute(
                "SELECT e.ts, e.kind, e.old, e.new, s.board, s.sched_time,"
                " COALESCE(q.station_canonical, s.station) AS station"
                " FROM events e JOIN services s ON s.id = e.service_id"
                " LEFT JOIN service_quality q ON q.service_id = s.id"
                " WHERE s.train_no = ? AND s.service_date = ?"
                " AND NOT " + quality.SUSPECT_EVENT_SQL + " AND NOT " + quality.GHOST_SQL +
                " ORDER BY e.ts, e.id",
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
        """Current {status, delay, platform, last_read, last_seen, delay_read} of one
        service, or None.

        `last_read` is the ts of the last ok run that matched the service with a
        confident row (low-confidence sightings do not update it). `delay_read` says
        whether the delay cell was readable in that run: when it was not, `delay` is the
        previous reading kept, so it must not confirm a pending delay change.
        """
        with self._lock:
            s = self._conn.execute(
                "SELECT id, status, last_delay, last_platform, last_read, last_seen FROM services"
                " WHERE board=?"
                " AND service_date=? AND train_no=? AND sched_time=?",
                (board, service_date, train_no, sched_time),
            ).fetchone()
        if s is None:
            return None
        return {"status": s["status"], "delay": s["last_delay"],
                "platform": s["last_platform"], "last_read": s["last_read"],
                "last_seen": s["last_seen"], "delay_read": self._delay_read.get(s["id"], True)}

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
        """Followed trains with their current board state: `on_board`, and when listed
        `delay_min` + `delay_read` (False = the delay cell is unreadable right now)."""
        with self._lock:
            found = self._conn.execute(
                "SELECT f.train_no, f.service_date,"
                " (SELECT v.id FROM services v WHERE v.train_no = f.train_no"
                "  AND v.service_date = f.service_date AND v.status = 'listed'"
                "  ORDER BY v.id LIMIT 1) AS sid,"
                " (SELECT v.last_delay FROM services v WHERE v.train_no = f.train_no"
                "  AND v.service_date = f.service_date AND v.status = 'listed'"
                "  ORDER BY v.id LIMIT 1) AS delay"
                " FROM follows f JOIN subscriptions s ON s.id = f.subscription_id"
                " WHERE s.endpoint=? ORDER BY f.rowid", (endpoint,)).fetchall()
        out = []
        for r in found:
            item = {"train_no": r["train_no"], "date": r["service_date"],
                    "on_board": r["sid"] is not None}
            if item["on_board"]:
                item["delay_min"] = r["delay"]
                item["delay_read"] = self._delay_read.get(r["sid"], True)
            out.append(item)
        return out
