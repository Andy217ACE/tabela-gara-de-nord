# © 2026 Andy217Ace
"""READ-ONLY report of ambiguous train-number pairs. Writes nothing.

    python scripts/ambiguous_pairs.py --db /path/tabela.db [--days 30]

``find_pairs(conn, days=30, today=None) -> list[Pair]`` (importable; no side effects).

Definitions
-----------
* Window: services with ``service_date >= today - days`` and observations with
  ``observed_at >= (today - days)`` (date prefix compare). ``today`` defaults to the
  local date; tests pass it explicitly.
* Candidate numbers: ``services.train_no`` in the window plus ``observations.train_no``
  (as read) in the window. Only numbers of 2+ digits take part.
* ``kind`` (priority coexist > prefix_dup > one_digit); a pair is reported only when its
  numbers are related by shape and/or coexist:
  - shape ``prefix_dup``: the shorter number (>= 2 digits) is a prefix OR a suffix of the
    longer (8093/93, 5019/19, 10055/55, 503/5031, 800/8001);
  - shape ``one_digit``: same length, exactly one differing character (1584/1581);
  - ``coexist``: the two numbers were read (observations.train_no) in the SAME capture
    on the SAME board at least once in the window -> distinct trains, never merge, whatever
    their shape (5011/5014). Only shape-related pairs are listed as coexist (every two
    rows of a frame coexist; listing them all would be noise).
* ``no_a < no_b`` numerically.
* ``reads_a`` / ``reads_b``: observations of that number (observations.train_no, as read)
  in the window; without an ``observations`` table: number of services in the window.
* ``station``: stations (``services.station`` in the window) of both numbers; if they
  share some, the one with most services (both numbers together, ties alphabetical),
  else None.
* ``same_day_overlap``: some service of no_a and some service of no_b have the same
  service_date and board and overlapping first_seen..last_seen intervals.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple


class Pair(NamedTuple):
    no_a: int
    no_b: int
    station: str | None
    same_day_overlap: bool
    reads_a: int
    reads_b: int
    kind: str


def _has(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def _ts(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _shape(a: int, b: int) -> str | None:
    sa, sb = sorted((str(a), str(b)), key=lambda s: (len(s), s))
    if sa == sb:
        return None
    if len(sa) == len(sb):
        return "one_digit" if sum(x != y for x, y in zip(sa, sb)) == 1 else None
    if len(sa) >= 2 and (sb.startswith(sa) or sb.endswith(sa)):
        return "prefix_dup"
    return None


def _shape_pairs(nums: set[int]) -> set[tuple[int, int]]:
    """Shape-related pairs among nums, via lookup keys (no O(n^2) scan)."""
    strs = {str(n) for n in nums}
    out: set[tuple[int, int]] = set()
    for s in strs:
        for k in range(2, len(s)):  # proper prefixes / suffixes of 2+ digits
            for t in (s[:k], s[-k:]):
                if t in strs:
                    out.add((int(t), int(s)))
    buckets: dict[tuple, list[str]] = defaultdict(list)
    for s in strs:
        for i in range(len(s)):
            buckets[(s[:i], i, s[i + 1:])].append(s)
    for grp in buckets.values():
        for i, x in enumerate(grp):
            for y in grp[i + 1:]:
                out.add((min(int(x), int(y)), max(int(x), int(y))))
    return {(a, b) for a, b in out if _shape(a, b)}


def find_pairs(conn: sqlite3.Connection, days: int = 30,
               today: date | None = None) -> list[Pair]:
    cutoff = ((today or date.today()) - timedelta(days=days)).isoformat()
    has_obs = _has(conn, "observations")
    svcs = conn.execute(
        "SELECT train_no, board, service_date, station, first_seen, last_seen FROM services"
        " WHERE service_date >= ?", (cutoff,)).fetchall()
    reads: Counter = Counter()
    coexist: set[tuple[int, int]] = set()
    if has_obs:
        for no, n in conn.execute(
                "SELECT train_no, COUNT(*) FROM observations WHERE observed_at >= ?"
                " AND train_no IS NOT NULL GROUP BY train_no", (cutoff,)):
            reads[no] = n
        coexist = {(a, b) for a, b in conn.execute(
            "SELECT DISTINCT x.train_no, y.train_no FROM observations x"
            " JOIN observations y ON y.capture_id = x.capture_id AND y.board = x.board"
            " WHERE x.train_no < y.train_no AND x.observed_at >= ?", (cutoff,))}
    else:
        for r in svcs:
            reads[r[0]] += 1
    by_no: dict[int, list] = defaultdict(list)
    for r in svcs:
        by_no[r[0]].append(r)
    nums = {n for n in set(by_no) | set(reads) if n >= 10}
    related = _shape_pairs(nums)
    out: list[Pair] = []
    for a, b in sorted(related):
        kind = "coexist" if (a, b) in coexist else _shape(a, b)
        sa, sb = by_no.get(a, []), by_no.get(b, [])
        common = Counter(r[3] for r in sa) & Counter(r[3] for r in sb)
        both = Counter(r[3] for r in sa + sb)
        station = (min(common, key=lambda s: (-both[s], s)) if common else None)
        overlap = any(
            x[1] == y[1] and x[2] == y[2]
            and _ts(x[4]) <= _ts(y[5]) and _ts(y[4]) <= _ts(x[5])
            for x in sa for y in sb)
        out.append(Pair(a, b, station, overlap, reads[a], reads[b], kind))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--db", default=os.environ.get("DB_PATH", "tabela.db"))
    p.add_argument("--days", type=int, default=30, help="window in days (default 30)")
    a = p.parse_args(argv)
    if not os.path.exists(a.db):
        p.error(f"no database at {a.db}")
    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    try:
        pairs = find_pairs(conn, a.days)
    finally:
        conn.close()
    print(f"{'kind':<11}{'no_a':>7}{'no_b':>7}  {'station':<24}{'overlap':<8}"
          f"{'reads_a':>8}{'reads_b':>8}")
    for q in sorted(pairs, key=lambda q: (q.kind, q.no_a, q.no_b)):
        print(f"{q.kind:<11}{q.no_a:>7}{q.no_b:>7}  {q.station or '-':<24}"
              f"{'yes' if q.same_day_overlap else 'no':<8}{q.reads_a:>8}{q.reads_b:>8}")
    print(f"{len(pairs)} pair(s), window {a.days} day(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
