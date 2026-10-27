# © 2026 Andy217Ace
"""Scheduled times on a panel are in chronological order: a time out of order is a misread.

The board lists the trains of one panel by scheduled time (12 lines, rising, wrapping
once at midnight). A digit read wrong in a time ("06:52" read "05:52": 5/6, "03:38"
read "08:58": 3/8, 0/8) breaks that order, and a misread that persists for many frames
creates a second, wrong service of the same train. Live audit 21-26.10: 283 of 81 823
interior lines out of order, nearly all misreads.

``check_time_order`` finds the lines that are in no longest non-decreasing run of the
panel (so one misread neighbour does not condemn the lines around it), then:

- repairs the time when exactly ONE single-digit change between digits the glyph
  matcher confuses puts it back between its neighbours (the board's own order is the
  evidence; the row is marked uncertain and its confidence capped), or
- otherwise only lowers its confidence and marks it uncertain (a new service from it
  needs a second consecutive reading; it never renames a stored one).

Nothing is invented: no change that is not unique and confusable, none for a line the
order does not contradict.
"""
from __future__ import annotations

import dataclasses

from app.normalize import parse_time

# digit pairs the template matcher / Tesseract confuse on this font (both directions)
CONFUSABLE = {frozenset(p) for p in ("08", "38", "56", "35", "68", "89", "09", "17", "14")}
DAY = 1440
SUSPECT_CONFIDENCE = 0.6  # cap: below store.CONFIRM_CONFIDENCE (0.7)
REPAIRED_CONFIDENCE = 0.65


def _minutes(t: str) -> int:
    return int(t[:2]) * 60 + int(t[3:])


def _unwrap(mins: list[int]) -> list[int]:
    """Add a day each time the sequence falls by more than 12 h (the midnight wrap)."""
    out, add = [], 0
    for k, m in enumerate(mins):
        if k and m + add < out[-1] - DAY // 2:
            add += DAY
        out.append(m + add)
    return out


def out_of_order(times: list[str]) -> list[int]:
    """Indexes (into `times`) of lines in no longest non-decreasing run."""
    n = len(times)
    if n < 3:
        return []
    v = _unwrap([_minutes(t) for t in times])
    f, g = [1] * n, [1] * n
    for i in range(n):
        for j in range(i):
            if v[j] <= v[i]:
                f[i] = max(f[i], f[j] + 1)
    for i in range(n - 1, -1, -1):
        for j in range(i + 1, n):
            if v[i] <= v[j]:
                g[i] = max(g[i], g[j] + 1)
    best = max(f)
    return [i for i in range(n) if f[i] + g[i] - 1 != best]


def _candidates(t: str) -> list[str]:
    out = []
    for pos in (0, 1, 3, 4):
        for d in "0123456789":
            if d != t[pos] and frozenset((t[pos], d)) in CONFUSABLE:
                c = parse_time(t[:pos] + d + t[pos + 1:])
                if c is not None and c != t:
                    out.append(c)
    return out


def _repair(times: list[str], k: int, bad: set[int]) -> str | None:
    """The single confusable one-digit change of times[k] that fits between the nearest
    lines the order does not condemn, or None (none / several)."""
    lo = next((times[i] for i in range(k - 1, -1, -1) if i not in bad), None)
    hi = next((times[i] for i in range(k + 1, len(times)) if i not in bad), None)
    if lo is None and hi is None:
        return None
    fits = []
    for c in _candidates(times[k]):
        ok = True
        if lo is not None and (_minutes(c) - _minutes(lo)) % DAY > DAY // 2:
            ok = False  # before the previous line
        if ok and hi is not None and (_minutes(hi) - _minutes(c)) % DAY > DAY // 2:
            ok = False  # after the next line
        if ok and lo is not None and hi is not None and (
                (_minutes(c) - _minutes(lo)) % DAY > (_minutes(hi) - _minutes(lo)) % DAY):
            ok = False
        if ok:
            fits.append(c)
    return fits[0] if len(fits) == 1 else None


def check_time_order(entries: list[dict]) -> int:
    """Apply the order check to the debug `entries` of one frame (in place). Returns
    the number of lines touched. Rows are replaced (frozen dataclass); ``fields.time``
    gets ``check`` = "order" (lowered confidence) or "order_fixed" (+ ``seen``)."""
    touched = 0
    for board in {e["board"] for e in entries}:
        idx = sorted((i for i, e in enumerate(entries)
                      if e["board"] == board and e["row"] is not None),
                     key=lambda i: entries[i]["row_index"])
        times = [entries[i]["row"].sched_time for i in idx]
        bad = set(out_of_order(times))
        for k in sorted(bad):
            e = entries[idx[k]]
            row = e["row"]
            fix = _repair(times, k, bad)
            f = e["fields"]["time"]
            if fix is not None:
                f["seen"], f["check"], f["norm"] = row.sched_time, "order_fixed", fix
                e["row"] = dataclasses.replace(
                    row, sched_time=fix, uncertain=True,
                    confidence=min(row.confidence, REPAIRED_CONFIDENCE))
            else:
                f["check"] = "order"
                e["row"] = dataclasses.replace(
                    row, uncertain=True, confidence=min(row.confidence, SUSPECT_CONFIDENCE))
            touched += 1
    return touched
