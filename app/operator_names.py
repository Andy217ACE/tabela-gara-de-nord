# © 2026 Andy217Ace
"""Schema v9 -> v10: operators stored under their official names instead of the
truncated, diacritic-less board text ("CFR Calatori" -> "CFR Călători").

One pass per table through a TEMP mapping table (never one UPDATE per value). The
``*_raw`` columns (the text as read) are never touched. Atomic with the version bump.
"""
from __future__ import annotations

import json
import sqlite3

from app.canonical import operator_match


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,)).fetchone() is not None


def _official(value) -> str | None:
    """The official name when `value` is an accepted match (by the live rule), else None."""
    if not value:
        return None
    name, _, ok = operator_match(value)
    return name if ok else None


def _remap_values(conn: sqlite3.Connection) -> None:
    """services.operator, service_quality.operator_canonical, operator corrections."""
    old: set[str] = set()
    sources = [("services", "operator"), ("service_quality", "operator_canonical")]
    for t, c in sources:
        if _has(conn, t):
            old.update(r[0] for r in conn.execute(f"SELECT DISTINCT {c} FROM {t}") if r[0])
    has_corr = _has(conn, "corrections")
    if has_corr:
        for c in ("wrong_value", "correct_value"):
            old.update(r[0] for r in conn.execute(
                f"SELECT DISTINCT {c} FROM corrections WHERE field='operator'") if r[0])
    conn.execute("CREATE TEMP TABLE op_map(old TEXT PRIMARY KEY, new TEXT NOT NULL) WITHOUT ROWID")
    pairs = [(o, n) for o in old if (n := _official(o)) and n != o]
    conn.executemany("INSERT INTO op_map VALUES (?, ?)", pairs)
    try:
        if not pairs:
            return
        for t, c in sources:
            if _has(conn, t):
                conn.execute(f"UPDATE {t} SET {c} = (SELECT new FROM op_map WHERE old = {t}.{c})"
                             f" WHERE {c} IN (SELECT old FROM op_map)")
        if has_corr:
            for c in ("wrong_value", "correct_value"):
                conn.execute(f"UPDATE corrections SET {c} = (SELECT new FROM op_map"
                             f" WHERE old = corrections.{c}) WHERE field='operator'"
                             f" AND {c} IN (SELECT old FROM op_map)")
    finally:
        conn.execute("DROP TABLE op_map")


def _remap_observations(conn: sqlite3.Connection) -> None:
    """operator by (operator, operator_raw): the accepted operator, else the accepted raw."""
    if not _has(conn, "observations"):
        return
    conn.execute("CREATE TEMP TABLE obs_map(op TEXT NOT NULL, raw TEXT NOT NULL, new TEXT NOT NULL,"
                 " PRIMARY KEY (op, raw)) WITHOUT ROWID")
    try:
        rows = []
        for op, raw in conn.execute("SELECT DISTINCT COALESCE(operator, ''),"
                                    " COALESCE(operator_raw, '') FROM observations"):
            new = _official(op) or _official(raw)
            if new and new != op:
                rows.append((op, raw, new))
        if not rows:
            return
        conn.executemany("INSERT INTO obs_map VALUES (?, ?, ?)", rows)
        key = "COALESCE(observations.operator, ''), COALESCE(observations.operator_raw, '')"
        conn.execute(
            f"UPDATE observations SET operator = (SELECT new FROM obs_map WHERE op ="
            f" COALESCE(observations.operator, '') AND raw = COALESCE(observations.operator_raw, ''))"
            f" WHERE ({key}) IN (SELECT op, raw FROM obs_map)")
    finally:
        conn.execute("DROP TABLE obs_map")


def _remap_trains(conn: sqlite3.Connection) -> None:
    """trains.operators_json: rename, merge duplicates (sum journeys), re-sort."""
    if not _has(conn, "trains"):
        return
    for no, js in conn.execute("SELECT train_no, operators_json FROM trains").fetchall():
        try:  # one malformed row must not block startup: leave it as it is
            items = [it for it in json.loads(js or "[]") if isinstance(it, dict)]
        except (ValueError, TypeError):
            continue
        total: dict[str, int] = {}
        for it in items:
            name = _official(it.get("operator")) or it.get("operator") or ""
            total[name] = total.get(name, 0) + int(it.get("journeys") or 0)
        new = json.dumps([{"operator": k, "journeys": v}
                          for k, v in sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))],
                         ensure_ascii=False)
        if new != js:
            conn.execute("UPDATE trains SET operators_json=? WHERE train_no=?", (new, no))


def migrate_to_10(conn: sqlite3.Connection) -> None:
    """Schema v9 -> v10, atomically with the version bump (a failure leaves v9 in place).
    Re-runnable."""
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 10:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        _remap_values(conn)
        _remap_observations(conn)
        _remap_trains(conn)
        conn.execute("PRAGMA user_version = 10")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
