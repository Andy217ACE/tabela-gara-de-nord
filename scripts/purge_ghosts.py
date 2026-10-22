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

``--apply`` first writes a full online backup of the database (``sqlite3 backup``,
integrity-checked) into ``--backup-dir``; then, in ONE transaction, every row it
removes (the service, its events, its quality row, the links of its observations) is
archived as JSON in ``purged_rows`` with a batch id, the services are deleted (events
and quality rows go with them, observations keep their data and lose only the link)
and the train catalog is recomputed. ``--restore`` puts a batch back exactly.
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


def plan(conn: sqlite3.Connection, ids: list[int]) -> dict:
    def n(sql):
        total = 0
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            total += conn.execute(sql.format(",".join("?" * len(chunk))), chunk).fetchone()[0]
        return total
    out = {"services": len(ids),
           "events": n("SELECT COUNT(*) FROM events WHERE service_id IN ({})"),
           "service_quality": n("SELECT COUNT(*) FROM service_quality WHERE service_id IN ({})")}
    if _has(conn, "observations"):
        out["observation_links"] = n(
            "SELECT COUNT(*) FROM observations WHERE service_id IN ({})")
    return out


def _archive(conn, batch, table, rows, now):
    for r in rows:
        conn.execute("INSERT INTO purged_rows(batch, table_name, row_id, data_json, purged_at)"
                     " VALUES (?,?,?,?,?)", (batch, table, r[0], json.dumps(dict(r)), now))


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


def apply(conn: sqlite3.Connection, ids: list[int]) -> str:
    from app.observations import refresh_trains

    batch = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(ARCHIVE)
        nos = set()
        for sid in ids:
            svc = conn.execute("SELECT * FROM services WHERE id=?", (sid,)).fetchone()
            if svc is None:
                continue
            nos.add(svc["train_no"])
            _archive(conn, batch, "services", [svc], now)
            _archive(conn, batch, "events", conn.execute(
                "SELECT * FROM events WHERE service_id=?", (sid,)).fetchall(), now)
            _archive(conn, batch, "service_quality", conn.execute(
                "SELECT * FROM service_quality WHERE service_id=?", (sid,)).fetchall(), now)
            if _has(conn, "observations"):
                _archive(conn, batch, "observation_links", conn.execute(
                    "SELECT id, service_id FROM observations WHERE service_id=?",
                    (sid,)).fetchall(), now)
            conn.execute("DELETE FROM services WHERE id=?", (sid,))  # cascades / SET NULL
        if _has(conn, "trains"):
            refresh_trains(conn, nos)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return batch


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
        for table in ("services", "events", "service_quality", "observation_links"):
            for b in batches:
                for rid, data in conn.execute(
                        "SELECT id, data_json FROM purged_rows WHERE batch=? AND table_name=?"
                        " ORDER BY id", (b, table)).fetchall():
                    d = json.loads(data)
                    if table == "observation_links":
                        conn.execute("UPDATE observations SET service_id=? WHERE id=?",
                                     (d["service_id"], d["id"]))
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
        report = {"mode": "apply" if a.apply else "dry-run", "would_remove": plan(conn, ids),
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
        if a.apply and ids:
            report["backup"] = backup(a.db, a.backup_dir)
            report["batch"] = apply(conn, ids)
        print(json.dumps(report, ensure_ascii=False, indent=1))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
