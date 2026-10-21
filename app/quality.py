# © 2026 Andy217Ace
"""Data-quality layer: validation rules for OCR readings and quality flags.

Nothing here deletes or rewrites what was read. Raw services/events stay as they
were stored; the quality verdicts live in side tables (created idempotently,
independent of ``PRAGMA user_version`` so they never collide with the schema
ladder of other branches):

- ``service_quality``: per service — ``ghost`` (a misread duplicate or a one-off
  sighting, excluded from the board, the catalog and the statistics),
  ``low_quality`` (seen in a period marked "calitate redusă (beta)"), the delay
  recomputed from confirmed values only (``max_delay_clean``/``last_delay_clean``,
  NULL = unknown, never 0) and canonical station/operator names (raw kept).
- ``event_quality``: per event — ``suspect`` with a reason (e.g. a "+" read as a
  digit: "+25" stored as 425). Suspect events are ignored in calculations.
- ``quality_periods``: time ranges whose data is of reduced quality.
- ``dq_meta``: version of this layer and the moment live validation started.

Every rule below is backed by cases measured on the live database
(``.superpowers/sdd/2026-10-21-master-plan/data-quality-report.md``).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime

log = logging.getLogger(__name__)

DQ_VERSION = "1"

# --- delay validation --------------------------------------------------------
DELAY_CONFIRM = 2  # a delay change is applied after this many consecutive identical readings
DELAY_BIG = 100  # a reading at least this large...
DELAY_BIG_JUMP = 60  # ...this far from the confirmed value...
DELAY_BIG_CONFIRM = 3  # ...needs this many consecutive readings

# --- platform validation -----------------------------------------------------
PLATFORM_CONFIRM = 2
PLATFORM_CONFUSED_CONFIRM = 3
# digit pairs the OCR swaps on this board (5/6; 1/4/11/14; 3/8): measured flapping
PLATFORM_CONFUSION = (frozenset({5, 6}), frozenset({1, 4, 11, 14}), frozenset({3, 8}))

# --- ghosts ------------------------------------------------------------------
GHOST_MIN_LIFE_S = 120  # a service seen for less than 2 minutes is not a reliable train
GHOST_MAX_OBS = 1  # a near-duplicate with at most this many observations is a misread

# --- reduced-quality period (Beta, before captures/observations existed) -------------
# First run 2026-10-21 00:32 local; first capture (v5, current pipeline) at 11:31:51 local.
LOW_QUALITY_PERIODS = (
    ("2026-10-21T00:00:00+03:00", "2026-10-21T11:31:51+03:00", "beta",
     "Beta 1.00: pipeline vechi, înainte de capturi/observații (calitate redusă)"),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dq_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS service_quality (
    service_id INTEGER PRIMARY KEY REFERENCES services(id) ON DELETE CASCADE,
    ghost INTEGER NOT NULL DEFAULT 0,
    ghost_reason TEXT,
    ghost_of INTEGER,
    low_quality INTEGER NOT NULL DEFAULT 0,
    delay_checked INTEGER NOT NULL DEFAULT 0,
    max_delay_clean INTEGER,
    last_delay_clean INTEGER,
    station_canonical TEXT,
    operator_canonical TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_service_quality_ghost ON service_quality(ghost);
CREATE TABLE IF NOT EXISTS event_quality (
    event_id INTEGER PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
    suspect INTEGER NOT NULL DEFAULT 1,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quality_periods (
    id INTEGER PRIMARY KEY,
    start_ts TEXT NOT NULL,
    end_ts TEXT NOT NULL,
    label TEXT NOT NULL,
    note TEXT,
    UNIQUE (start_ts, end_ts)
);
"""

# SQL fragments for readers (alias of the services table: s).
GHOST_SQL = "(s.id IN (SELECT service_id FROM service_quality WHERE ghost=1))"
LOW_QUALITY_SQL = "(s.id IN (SELECT service_id FROM service_quality WHERE low_quality=1))"
SUSPECT_EVENT_SQL = "(e.id IN (SELECT event_id FROM event_quality WHERE suspect=1))"


def include_low_quality() -> bool:
    """STATS_INCLUDE_LOW_QUALITY=1 keeps the reduced-quality period in public statistics
    (default: excluded)."""
    return os.environ.get("STATS_INCLUDE_LOW_QUALITY", "0").strip().lower() in (
        "1", "true", "yes", "on")


def public_services_where(alias: str = "s") -> str:
    """WHERE fragment selecting the services public statistics may use: never ghosts,
    and not the reduced-quality period unless STATS_INCLUDE_LOW_QUALITY=1."""
    parts = [f"{alias}.id NOT IN (SELECT service_id FROM service_quality WHERE ghost=1)"]
    if not include_low_quality():
        parts.append(
            f"{alias}.id NOT IN (SELECT service_id FROM service_quality WHERE low_quality=1)")
    return " AND ".join(parts)


def ensure_schema(conn: sqlite3.Connection, now_iso: str | None = None) -> None:
    """Create the quality tables (idempotent, additive, atomic). Records when live
    validation started (``live_since``) the first time only."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        for stmt in _SCHEMA.split(";"):
            if stmt.strip():
                conn.execute(stmt)
        conn.execute("INSERT INTO dq_meta(key, value) VALUES ('version', ?)"
                     " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (DQ_VERSION,))
        conn.execute("INSERT OR IGNORE INTO dq_meta(key, value) VALUES ('live_since', ?)",
                     (now_iso or datetime.now().astimezone().isoformat(),))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


# --- pure rules ----------------------------------------------------------------

def digit_dropped(value: int, ref: int | None) -> bool:
    """Is `value` (3+ digits) `ref` with one extra digit — the board's "+" read as a
    digit or a stray glyph? 25->425, 10->410, 10->190, 20->240, 45->435."""
    if ref is None or value < DELAY_BIG:
        return False
    s = str(value)
    return any(int(s[:i] + s[i + 1:]) == ref for i in range(len(s)))


def delay_needs(value: int, confirmed: int | None) -> int | None:
    """Consecutive identical readings needed before `value` replaces `confirmed`;
    None: never (a misread "+")."""
    if digit_dropped(value, confirmed):
        return None
    if confirmed is not None and value >= DELAY_BIG and abs(value - confirmed) >= DELAY_BIG_JUMP:
        return DELAY_BIG_CONFIRM
    return DELAY_CONFIRM


def platform_needs(old: int | None, new: int | None) -> int:
    """Consecutive identical readings needed for a platform change. The first platform
    shown (none -> x) is immediate; a pair the OCR confuses (5/6, 1/4/11/14, 3/8)
    needs PLATFORM_CONFUSED_CONFIRM; anything else, clearing included, PLATFORM_CONFIRM."""
    if old is None:
        return 1
    if new is not None and any(old in g and new in g for g in PLATFORM_CONFUSION):
        return PLATFORM_CONFUSED_CONFIRM
    return PLATFORM_CONFIRM


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def run_times(conn: sqlite3.Connection) -> list[float]:
    """Sorted epoch seconds of the successful readings (robust across DST changes)."""
    return sorted(_ts(r[0]).timestamp() for r in conn.execute("SELECT ts FROM runs WHERE ok=1"))


def classify_delays(first_seen: str, last_seen: str, last_delay: int,
                    events: list[tuple[int, str, str | None, str | None]],
                    run_ts: list[str]) -> dict:
    """Retroactive delay check of one service.

    `events`: its delay events (id, ts, old, new), chronological. `run_ts`: sorted
    epoch seconds of the successful readings (see `run_times`). Each value
    lasts from its event until the next one (the last until `last_seen`); its frame
    count is the number of successful readings in that span. A value is confirmed when
    it lasted `delay_needs` frames and is not a misread "+" of its neighbours.

    Returns {"suspect": {event id: reason}, "max": int|None, "last": int|None}
    (None = no confirmed value: unknown, never 0).
    """
    def num(x, default=None):
        try:
            return int(x)
        except (TypeError, ValueError):
            return default

    segs = [(first_seen, num(events[0][2], 0) if events else last_delay, None)]
    segs += [(ts, num(new), eid) for eid, ts, _old, new in events]
    suspect: dict[int, str] = {}
    confirmed_vals: list[int] = []
    prev: int | None = None
    for i, (start, value, eid) in enumerate(segs):
        if value is None:
            continue
        last = i == len(segs) - 1
        end = _ts(last_seen if last else segs[i + 1][0]).timestamp()
        hi = bisect_right(run_ts, end) if last else bisect_left(run_ts, end)
        frames = max(0, hi - bisect_left(run_ts, _ts(start).timestamp()))
        nxt = None if last else segs[i + 1][1]
        need = delay_needs(value, prev) if prev is not None else DELAY_CONFIRM
        plus = digit_dropped(value, prev) or digit_dropped(value, nxt)
        if not plus and need is not None and frames >= need:
            prev = value
            confirmed_vals.append(value)
            continue
        if eid is not None:
            suspect[eid] = "plus_misread" if plus else "unconfirmed"
        if nxt is not None and nxt == prev and segs[i + 1][2] is not None:
            suspect.setdefault(segs[i + 1][2], "revert")
    return {"suspect": suspect, "max": max(confirmed_vals) if confirmed_vals else None,
            "last": prev}


def ghost_verdict(svc: dict, partners: list[dict], n_obs: int) -> tuple[str, int | None] | None:
    """(reason, real service id) if `svc` is a ghost, else None.

    `svc`/`partners`: dicts with id, train_no, sched_time, station, station_raw,
    first_seen, last_seen, status (partners: same board and service date).
    A service still listed is never judged. Ghost when it lived < GHOST_MIN_LIFE_S
    ("short"), or when it has at most GHOST_MAX_OBS observations and a partner that
    lived longer is a one-character variant of it ("near_dup": R 5011 + 5014/50141/501...).
    """
    from app.store import _near_dup  # local: store imports this module

    if svc["status"] == "listed":
        return None
    life = (_ts(svc["last_seen"]) - _ts(svc["first_seen"])).total_seconds()
    me = (svc["train_no"], svc["sched_time"], svc["station"], svc["station_raw"])
    best = None
    if n_obs <= GHOST_MAX_OBS:
        for p in partners:
            if p["id"] == svc["id"] or (p["train_no"], p["sched_time"]) == me[:2]:
                continue
            p_life = (_ts(p["last_seen"]) - _ts(p["first_seen"])).total_seconds()
            if p_life > life and _near_dup(
                    (p["train_no"], p["sched_time"], p["station"], p["station_raw"]), me):
                if best is None or p_life > best[0]:
                    best = (p_life, p["id"])
    if best is not None:
        return "near_dup", best[1]
    if life < GHOST_MIN_LIFE_S:
        return "short", None
    return None


# --- persistence helpers --------------------------------------------------------

def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def upsert_service(conn: sqlite3.Connection, service_id: int, **fields) -> None:
    """Set some service_quality columns of one service (other columns kept)."""
    cols = list(fields)
    conn.execute(
        f"INSERT INTO service_quality(service_id, {', '.join(cols)}, updated_at)"
        f" VALUES (?, {', '.join('?' * len(cols))}, ?)"
        f" ON CONFLICT(service_id) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in cols) + ", updated_at=excluded.updated_at",
        (service_id, *fields.values(), _now()))


def judge_ghost(conn: sqlite3.Connection, service_id: int) -> tuple[str, int | None] | None:
    """Evaluate one service (live: when it leaves the board) and store the verdict."""
    s = conn.execute("SELECT * FROM services WHERE id=?", (service_id,)).fetchone()
    if s is None:
        return None
    partners = conn.execute(
        "SELECT id, train_no, sched_time, station, station_raw, first_seen, last_seen, status"
        " FROM services WHERE board=? AND service_date=? AND id != ?",
        (s["board"], s["service_date"], service_id)).fetchall()
    n_obs = _obs_count(conn, [service_id]).get(service_id, 0)
    verdict = ghost_verdict(dict(s), [dict(p) for p in partners], n_obs)
    if verdict is not None:
        upsert_service(conn, service_id, ghost=1, ghost_reason=verdict[0], ghost_of=verdict[1])
    elif (conn.execute("SELECT ghost FROM service_quality WHERE service_id=?",
                       (service_id,)).fetchone() or (0,))[0]:
        upsert_service(conn, service_id, ghost=0, ghost_reason=None, ghost_of=None)
    return verdict


def clear_ghost(conn: sqlite3.Connection, service_id: int) -> None:
    """A ghost read again (back on the board) is judged anew when it leaves."""
    conn.execute("UPDATE service_quality SET ghost=0, ghost_reason=NULL, ghost_of=NULL"
                 " WHERE service_id=? AND ghost=1", (service_id,))


def _obs_count(conn: sqlite3.Connection, ids: list[int] | None = None) -> dict[int, int]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'"
                        " AND name='observations'").fetchone():
        return {}
    sql = ("SELECT service_id, COUNT(*) FROM observations WHERE service_id IS NOT NULL"
           " AND validation_state IN ('ok', 'uncertain')")
    args: list = []
    if ids is not None:
        sql += f" AND service_id IN ({','.join('?' * len(ids))})"
        args = list(ids)
    return dict(conn.execute(sql + " GROUP BY service_id", args).fetchall())


# --- retroactive backfill (idempotent) ---------------------------------------------------

def _canonical_names(row) -> tuple[str | None, str | None]:
    """(station, operator) canonical forms when they differ from the stored ones."""
    from app import canonical

    st_src = row["station_raw"] or row["station"]
    st, st_score = canonical.canonical_station(st_src, (), preferred=canonical.seed_stations())
    st_out = st if st and st != row["station"] and st_score >= canonical.DEFAULT_THRESHOLD \
        and st in canonical.seed_stations() else None
    op_src = row["operator_raw"] or row["operator"]
    op, op_score = canonical.canonical_operator(op_src)
    op_out = op if op and op != row["operator"] and op_score >= canonical.DEFAULT_THRESHOLD \
        and op in canonical.known_operators() else None
    return st_out, op_out


def summary(conn: sqlite3.Connection) -> dict:
    """Headline numbers (read-only) used to compare before/after a backfill."""
    def one(sql, *a):
        return conn.execute(sql, a).fetchone()[0]
    has = bool(one("SELECT COUNT(*) FROM sqlite_master WHERE name='service_quality'"))
    out = {
        "services": one("SELECT COUNT(*) FROM services"),
        "events": one("SELECT COUNT(*) FROM events"),
        "delay_events_ge_190": one("SELECT COUNT(*) FROM events WHERE kind='delay'"
                                   " AND CAST(new AS INTEGER) >= 190"),
        "last_delay_ge_190": one("SELECT COUNT(*) FROM services WHERE last_delay >= 190"),
    }
    if has:
        out.update({
            "ghosts": one("SELECT COUNT(*) FROM service_quality WHERE ghost=1"),
            "low_quality": one("SELECT COUNT(*) FROM service_quality WHERE low_quality=1"),
            "suspect_events": one("SELECT COUNT(*) FROM event_quality WHERE suspect=1"),
            "max_delay_clean_ge_190": one("SELECT COUNT(*) FROM service_quality"
                                          " WHERE max_delay_clean >= 190"),
            "last_delay_clean_ge_190": one("SELECT COUNT(*) FROM service_quality"
                                           " WHERE last_delay_clean >= 190"),
            "station_canonical": one("SELECT COUNT(*) FROM service_quality"
                                     " WHERE station_canonical IS NOT NULL"),
            "operator_canonical": one("SELECT COUNT(*) FROM service_quality"
                                      " WHERE operator_canonical IS NOT NULL"),
        })
    if one("SELECT COUNT(*) FROM sqlite_master WHERE name='trains'"):
        out["catalog_trains"] = one("SELECT COUNT(*) FROM trains")
        out["catalog_trains_visible"] = one("SELECT COUNT(*) FROM trains WHERE journeys > 0")
    return out


def backfill(conn: sqlite3.Connection, *, dry_run: bool = False) -> dict:
    """Recompute every quality verdict from the stored data. Idempotent: the result is
    a pure function of services/events/runs/observations; nothing is deleted and no
    raw column is modified. Delay verdicts cover services first seen before live
    validation started (``dq_meta.live_since``); later ones were validated live.
    Returns {"before": summary, "after": summary, "changed": {...}}."""
    ensure_schema(conn)
    before = summary(conn)
    live_since = conn.execute("SELECT value FROM dq_meta WHERE key='live_since'").fetchone()[0]
    conn.execute("BEGIN IMMEDIATE")
    try:
        for start, end, label, note in LOW_QUALITY_PERIODS:
            conn.execute("INSERT INTO quality_periods(start_ts, end_ts, label, note)"
                         " VALUES (?,?,?,?) ON CONFLICT(start_ts, end_ts) DO UPDATE SET"
                         " label=excluded.label, note=excluded.note", (start, end, label, note))
        periods = [(_ts(a), _ts(b)) for a, b in conn.execute(
            "SELECT start_ts, end_ts FROM quality_periods").fetchall()]
        run_ts = run_times(conn)
        events = defaultdict(list)
        for sid, eid, ts, old, new in conn.execute(
                "SELECT service_id, id, ts, old, new FROM events WHERE kind='delay'"
                " ORDER BY service_id, ts, id"):
            events[sid].append((eid, ts, old, new))
        n_obs = _obs_count(conn)
        services = [dict(r) for r in conn.execute("SELECT * FROM services ORDER BY id")]
        by_day = defaultdict(list)
        for s in services:
            by_day[(s["board"], s["service_date"])].append(s)
        changed = defaultdict(int)
        live_dt = _ts(live_since)
        for s in services:
            sid = s["id"]
            verdict = ghost_verdict(s, by_day[(s["board"], s["service_date"])],
                                    n_obs.get(sid, 0))
            fs = _ts(s["first_seen"])
            low = int(any(a <= fs < b for a, b in periods))
            st_c, op_c = _canonical_names(s)
            fields = {"ghost": int(verdict is not None),
                      "ghost_reason": verdict[0] if verdict else None,
                      "ghost_of": verdict[1] if verdict else None,
                      "low_quality": low, "station_canonical": st_c,
                      "operator_canonical": op_c}
            if fs < live_dt:
                res = classify_delays(s["first_seen"], s["last_seen"], s["last_delay"],
                                      events.get(sid, []), run_ts)
                fields.update(delay_checked=1, max_delay_clean=res["max"],
                              last_delay_clean=res["last"])
                for eid, why in res["suspect"].items():
                    cur = conn.execute("SELECT reason FROM event_quality WHERE event_id=?",
                                       (eid,)).fetchone()
                    if cur is None or cur[0] != why:
                        changed["suspect_events"] += 1
                        conn.execute("INSERT INTO event_quality(event_id, suspect, reason)"
                                     " VALUES (?,1,?) ON CONFLICT(event_id) DO UPDATE SET"
                                     " suspect=1, reason=excluded.reason", (eid, why))
            old = conn.execute("SELECT * FROM service_quality WHERE service_id=?",
                               (sid,)).fetchone()
            if old is None or any(old[k] != v for k, v in fields.items()):
                changed["services"] += 1
                upsert_service(conn, sid, **fields)
        from app.observations import refresh_trains  # local: observations imports store
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='trains'").fetchone():
            refresh_trains(conn, [s["train_no"] for s in services]
                           + [r[0] for r in conn.execute("SELECT train_no FROM trains")])
        if dry_run:
            after = summary(conn)
            conn.execute("ROLLBACK")
        else:
            conn.execute("COMMIT")
            after = summary(conn)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return {"before": before, "after": after, "changed": dict(changed), "dry_run": dry_run}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Recalculează marcajele de calitate (idempotent;"
                                " nu șterge și nu modifică date brute).")
    p.add_argument("--db", default=os.environ.get("DB_PATH", "tabela.db"))
    p.add_argument("--dry-run", action="store_true", help="calculează și anulează")
    a = p.parse_args(argv)
    conn = sqlite3.connect(a.db, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    try:
        print(json.dumps(backfill(conn, dry_run=a.dry_run), ensure_ascii=False, indent=1))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
