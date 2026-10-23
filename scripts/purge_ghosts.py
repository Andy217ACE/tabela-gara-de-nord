# © 2026 Andy217Ace
"""Reversible removal of ghost services (misread duplicates / one-off sightings).

DEFAULT IS A DRY RUN: it only reads and prints what would be removed.

    python scripts/purge_ghosts.py --db /var/lib/tabela/tabela.db            # dry run
    python scripts/purge_ghosts.py --db ... --apply --backup-dir /root/x     # remove
    python scripts/purge_ghosts.py --db ... --restore [--batch ID]           # undo

Safe criteria (all required) — a service is purged only when:
- ``service_quality.ghost = 1`` (set by app.quality: lived < 2 min, or a one-character
  variant of a longer-lived service on the same panel/day with at most 1 observation);
- ``status = 'gone'`` (never a service on the board);
- last seen more than ``--min-age-min`` minutes ago (default 60: it cannot come back).

Never transitive: a ghost's real service (``ghost_of``) is its DIRECT partner (RM 7919
09:50 is a real train next to 7917/7921 and is never reached through a chain).

Also cleaned (all archived, all restorable):
- the observations of a purged ghost are moved to its real service (``ghost_of``,
  merge) when that one stays, otherwise only unlinked (never deleted);
- impossible delay events kept as suspect by app.quality (a value >= 100 that was a
  "+" read as a digit, and the return from it; e.g. 10 -> 410 -> 10);
- gone -> appeared pairs within FLAP_S seconds (marked ``flap`` by app.quality);
- ``last_delay`` of services whose stored final value was such a misread
  (R 10260: 945 -> 15), set to the confirmed value ``last_delay_clean``;
- catalog rows (``trains``) left without any journey (numbers only ever misread).

``--apply`` first writes a full online backup of the database (``sqlite3 backup``,
integrity-checked) into ``--backup-dir``; then, in ONE transaction, every row it
removes or changes is archived as JSON in ``purged_rows`` with a batch id.
``--restore`` puts a batch back exactly. The list is recomputed at the moment of
``--apply`` (live data changes); the dry run shows what that moment would remove.
Idempotent: a second ``--apply`` finds nothing; a second ``--restore`` finds nothing.
Stop the service (``systemctl stop tabela``) before ``--apply``/``--restore``.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ARCHIVE = """CREATE TABLE IF NOT EXISTS purged_rows (
    id INTEGER PRIMARY KEY,
    batch TEXT NOT NULL,
    table_name TEXT NOT NULL,
    row_id INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    purged_at TEXT NOT NULL
)"""
EXAMPLES = 20


def _ts(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _has(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def candidates(conn: sqlite3.Connection, min_age_min: int = 60,
               now: datetime | None = None) -> list[sqlite3.Row]:
    if not _has(conn, "service_quality"):
        return []
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(minutes=min_age_min)
    rows = conn.execute(
        "SELECT s.*, q.ghost_reason, q.ghost_of FROM services s"
        " JOIN service_quality q ON q.service_id = s.id"
        " WHERE q.ghost = 1 AND s.status = 'gone' ORDER BY s.id").fetchall()
    return [r for r in rows if _ts(r["last_seen"]) < cutoff]


def _in(ids) -> str:
    return ",".join(str(int(i)) for i in ids) or "NULL"


def bad_events(conn: sqlite3.Connection, ids: list[int]) -> list[int]:
    """Suspect events of the services that stay: impossible delays (and the return from
    them) and gone/appeared flapping."""
    if not _has(conn, "event_quality"):
        return []
    return [r[0] for r in conn.execute(
        "SELECT e.id FROM events e JOIN event_quality q ON q.event_id = e.id"
        f" WHERE q.suspect = 1 AND e.service_id NOT IN ({_in(ids)}) AND ("
        "  q.reason = 'flap' OR (e.kind = 'delay' AND q.reason IN"
        "  ('plus_misread', 'revert', 'unconfirmed') AND"
        "  (CAST(e.new AS INTEGER) >= 100 OR CAST(e.old AS INTEGER) >= 100)))"
        " ORDER BY e.id")]


def bad_last_delay(conn: sqlite3.Connection, ids: list[int]) -> list[tuple[int, int, int]]:
    """(service id, stored last_delay, confirmed value) for a stored misread final delay."""
    if not _has(conn, "service_quality"):
        return []
    return [tuple(r) for r in conn.execute(
        "SELECT s.id, s.last_delay, q.last_delay_clean FROM services s"
        " JOIN service_quality q ON q.service_id = s.id"
        f" WHERE s.id NOT IN ({_in(ids)}) AND s.status = 'gone' AND q.delay_checked = 1"
        " AND q.last_delay_clean IS NOT NULL AND s.last_delay >= 100"
        " AND s.last_delay != q.last_delay_clean ORDER BY s.id")]


def _merge_target(conn, row, ids: set[int]) -> int | None:
    g = row["ghost_of"]
    if g is None or g in ids:
        return None
    return g if conn.execute("SELECT 1 FROM services WHERE id=?", (g,)).fetchone() else None


def plan(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> dict:
    ids = [r["id"] for r in rows]
    idset = set(ids)
    q = _in(ids)
    out = {"services": len(ids),
           "events_of_services": conn.execute(
               f"SELECT COUNT(*) FROM events WHERE service_id IN ({q})").fetchone()[0],
           "service_quality": conn.execute(
               f"SELECT COUNT(*) FROM service_quality WHERE service_id IN ({q})").fetchone()[0]}
    if _has(conn, "observations"):
        merged = unlinked = 0
        for r in rows:
            n = conn.execute("SELECT COUNT(*) FROM observations WHERE service_id=?",
                             (r["id"],)).fetchone()[0]
            if _merge_target(conn, r, idset) is not None:
                merged += n
            else:
                unlinked += n
        out["observations_moved_to_real_service"] = merged
        out["observations_unlinked"] = unlinked
    bad = bad_events(conn, ids)
    kinds = dict(conn.execute(f"SELECT e.kind, COUNT(*) FROM events e WHERE e.id IN ({_in(bad)})"
                              " GROUP BY e.kind").fetchall())
    out["suspect_events"] = kinds
    out["last_delay_fixed"] = [{"service": a, "stored": b, "confirmed": c}
                               for a, b, c in bad_last_delay(conn, ids)]
    if _has(conn, "trains"):
        out["catalog_rows_without_journeys_now"] = conn.execute(
            "SELECT COUNT(*) FROM trains WHERE train_no NOT IN"
            f" (SELECT train_no FROM services WHERE id NOT IN ({q}))").fetchone()[0]
    return out


def _archive(conn, batch, table, rows, now):
    for r in rows:
        d = dict(r)
        conn.execute("INSERT INTO purged_rows(batch, table_name, row_id, data_json, purged_at)"
                     " VALUES (?,?,?,?,?)", (batch, table, next(iter(d.values())),
                                              json.dumps(d), now))


def backup(db: str, backup_dir: str) -> str:
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    dest = Path(backup_dir) / f"tabela-before-purge-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        src.close()
        dst.close()
    if ok != "ok":
        raise SystemExit(f"backup integrity check failed: {ok}")
    os.chmod(dest, 0o600)
    return str(dest)


def apply(conn: sqlite3.Connection, min_age_min: int = 60) -> tuple[str, dict]:
    """Recompute the list inside the write transaction and remove/merge (archived)."""
    from app.observations import refresh_trains

    batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(ARCHIVE)
        rows = candidates(conn, min_age_min)  # recomputed now, under the write lock
        ids = [r["id"] for r in rows]
        idset = set(ids)
        done = plan(conn, rows)
        nos = set()
        for eid in bad_events(conn, ids):
            ev = conn.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
            _archive(conn, batch, "events", [ev], now)
            _archive(conn, batch, "event_quality", conn.execute(
                "SELECT * FROM event_quality WHERE event_id=?", (eid,)).fetchall(), now)
            conn.execute("DELETE FROM events WHERE id=?", (eid,))
        for sid, stored, clean in bad_last_delay(conn, ids):
            _archive(conn, batch, "service_last_delay",
                     [{"id": sid, "last_delay": stored}], now)
            conn.execute("UPDATE services SET last_delay=? WHERE id=?", (clean, sid))
        for r in rows:
            sid = r["id"]
            svc = conn.execute("SELECT * FROM services WHERE id=?", (sid,)).fetchone()
            if svc is None:
                continue
            nos.add(svc["train_no"])
            if _has(conn, "observations"):
                _archive(conn, batch, "observation_links", conn.execute(
                    "SELECT id, service_id FROM observations WHERE service_id=?",
                    (sid,)).fetchall(), now)
                target = _merge_target(conn, r, idset)
                conn.execute("UPDATE observations SET service_id=? WHERE service_id=?",
                             (target, sid))
                if target is not None:
                    nos.add(conn.execute("SELECT train_no FROM services WHERE id=?",
                                         (target,)).fetchone()[0])
            _archive(conn, batch, "services", [svc], now)
            evs = conn.execute("SELECT * FROM events WHERE service_id=?", (sid,)).fetchall()
            _archive(conn, batch, "events", evs, now)
            _archive(conn, batch, "event_quality", conn.execute(
                "SELECT q.* FROM event_quality q JOIN events e ON e.id = q.event_id"
                " WHERE e.service_id=?", (sid,)).fetchall(), now)
            _archive(conn, batch, "service_quality", conn.execute(
                "SELECT * FROM service_quality WHERE service_id=?", (sid,)).fetchall(), now)
            # explicit (does not rely on ON DELETE CASCADE / foreign_keys)
            conn.execute("DELETE FROM event_quality WHERE event_id IN"
                         " (SELECT id FROM events WHERE service_id=?)", (sid,))
            conn.execute("DELETE FROM events WHERE service_id=?", (sid,))
            conn.execute("DELETE FROM service_quality WHERE service_id=?", (sid,))
            conn.execute("DELETE FROM services WHERE id=?", (sid,))
        if _has(conn, "trains"):
            refresh_trains(conn, nos)
            orphans = conn.execute("SELECT * FROM trains WHERE train_no NOT IN"
                                   " (SELECT train_no FROM services)").fetchall()
            _archive(conn, batch, "trains", orphans, now)
            conn.execute("DELETE FROM trains WHERE train_no NOT IN"
                         " (SELECT train_no FROM services)")
            done["catalog_rows_removed"] = len(orphans)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return batch, done


def restore(conn: sqlite3.Connection, batch: str | None = None) -> dict:
    from app.observations import refresh_trains

    if not _has(conn, "purged_rows"):
        return {}
    batches = [b for (b,) in conn.execute("SELECT DISTINCT batch FROM purged_rows")]
    if batch is not None:
        batches = [b for b in batches if b == batch]
    out: dict = {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        nos = set()
        for table in ("services", "events", "event_quality", "service_quality",
                      "observation_links", "service_last_delay", "trains"):
            for b in batches:
                for rid, data in conn.execute(
                        "SELECT id, data_json FROM purged_rows WHERE batch=? AND table_name=?"
                        " ORDER BY id", (b, table)).fetchall():
                    d = json.loads(data)
                    if table == "observation_links":
                        conn.execute("UPDATE observations SET service_id=? WHERE id=?",
                                     (d["service_id"], d["id"]))
                    elif table == "service_last_delay":
                        conn.execute("UPDATE services SET last_delay=? WHERE id=?",
                                     (d["last_delay"], d["id"]))
                    else:
                        if table == "services":
                            nos.add(d["train_no"])
                        cols = list(d)
                        conn.execute(f"INSERT OR IGNORE INTO {table}({', '.join(cols)})"
                                     f" VALUES ({', '.join('?' * len(cols))})",
                                     [d[c] for c in cols])
                    conn.execute("DELETE FROM purged_rows WHERE id=?", (rid,))
                    out[table] = out.get(table, 0) + 1
        if _has(conn, "trains"):
            refresh_trains(conn, nos)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--db", default=os.environ.get("DB_PATH", "tabela.db"))
    p.add_argument("--apply", action="store_true", help="remove (archived, reversible)")
    p.add_argument("--backup-dir", help="required with --apply: full DB backup goes here")
    p.add_argument("--restore", action="store_true", help="put purged rows back")
    p.add_argument("--batch", help="with --restore: only this batch")
    p.add_argument("--min-age-min", type=int, default=60)
    a = p.parse_args(argv)
    if a.apply and a.restore:
        p.error("--apply and --restore are exclusive")
    if a.apply and not a.backup_dir:
        p.error("--apply needs --backup-dir")
    if not Path(a.db).exists():
        p.error(f"no database at {a.db}")
    if a.apply or a.restore:
        conn = sqlite3.connect(a.db, isolation_level=None)
    else:  # dry run: read-only connection
        conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    try:
        if a.restore:
            print(json.dumps({"restored": restore(conn, a.batch)}))
            return 0
        rows = candidates(conn, a.min_age_min)
        ids = [r["id"] for r in rows]
        report = {"mode": "apply" if a.apply else "dry-run", "would_remove": plan(conn, rows),
                  "by_reason": {}, "examples": []}
        for r in rows:
            report["by_reason"][r["ghost_reason"]] = report["by_reason"].get(
                r["ghost_reason"], 0) + 1
        for r in rows[:EXAMPLES]:
            report["examples"].append({
                "id": r["id"], "board": r["board"], "date": r["service_date"],
                "train": f"{r['train_type']} {r['train_no']}", "sched": r["sched_time"],
                "station": r["station"], "first_seen": r["first_seen"],
                "last_seen": r["last_seen"], "reason": r["ghost_reason"],
                "ghost_of": r["ghost_of"]})
        if a.apply:
            report["backup"] = backup(a.db, a.backup_dir)
            report["batch"], report["applied"] = apply(conn, a.min_age_min)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
