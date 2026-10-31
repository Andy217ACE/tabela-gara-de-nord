# © 2026 Andy217Ace
"""Consensus per train over the frames that show it (no schema change).

A train stays on the board for dozens of captures (about one a minute), and one
misread frame must not decide its value. For each service, the last WINDOW usable
readings (observations of the service in captures whose validation_state is ``ok``
or ``uncertain``; ``rejected_low_conf`` and ``incomplete`` never vote) are counted per
field. A field takes the value that has a strict majority of the votes cast for that
field, and at least MIN_VOTES of them. A field without such a value is not decided
here: the caller keeps the stored value (no value is invented).

Unread cells carry ``norm: null`` in ``observations.fields_json`` and do not vote.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from typing import Any, Iterable

WINDOW = 15  # the last N usable readings of a service
MIN_VOTES = 3  # fewer votes for a field: no consensus, the stored value stays
VOTING_STATES = ("ok", "uncertain")
FIELDS = ("type", "no", "station", "operator", "time", "delay", "platform")
_CHUNK = 500  # service ids per SQL statement (SQLite parameter limit)


def winner(values: Iterable[Any]) -> Any | None:
    """The value with a strict majority of the non-None `values` (and >= MIN_VOTES), else None.

    A tie for the top count has no winner, whatever the counts are."""
    votes = [v for v in values if v is not None]
    if len(votes) < MIN_VOTES:
        return None
    top = Counter(votes).most_common(2)
    value, n = top[0]
    if len(top) > 1 and top[1][1] == n:
        return None
    if n < MIN_VOTES or n * 2 <= len(votes):
        return None
    return value


def _vote_of(reading: Any, name: str) -> Any | None:
    """The value one reading votes for `name`, None when it does not vote.

    A field the OCR completed or inferred (it carries a ``check``: a glare-inferred
    delay, a filled scheduled time, a delay voted from the digits seen) is derived from
    the train's own earlier readings, so it never votes: it would vote for itself."""
    if not isinstance(reading, dict):
        return None
    f = reading.get(name)
    if not isinstance(f, dict) or f.get("check"):
        return None
    return f.get("norm")


def consensus_of(reads: list[dict]) -> dict[str, Any]:
    """Per-field consensus of one service's readings (`fields_json` dicts, newest or not).

    Returns only the fields with a winner: {field: value}."""
    out: dict[str, Any] = {}
    for name in FIELDS:
        w = winner(_vote_of(r, name) for r in reads)
        if w is not None:
            out[name] = w
    return out


def service_consensus(conn: sqlite3.Connection, service_ids: Iterable[int],
                      window: int = WINDOW) -> dict[int, dict[str, Any]]:
    """{service_id: {field: consensus value}} for the services that have one.

    Reads the last `window` usable observations of each service in one query per chunk
    (ROW_NUMBER over the service's observations, newest first)."""
    ids = sorted({int(i) for i in service_ids if i is not None})
    out: dict[int, dict[str, Any]] = {}
    for start in range(0, len(ids), _CHUNK):
        chunk = ids[start:start + _CHUNK]
        marks = ",".join("?" * len(chunk))
        found = conn.execute(
            "SELECT service_id, fields_json FROM ("
            " SELECT service_id, fields_json, ROW_NUMBER() OVER ("
            "   PARTITION BY service_id ORDER BY observed_at DESC, id DESC) AS rn"
            " FROM observations WHERE service_id IN (" + marks + ")"
            " AND validation_state IN ('ok', 'uncertain'))"
            " WHERE rn <= ?",
            (*chunk, window)).fetchall()
        reads: dict[int, list[dict]] = defaultdict(list)
        for sid, fields_json in found:
            try:
                reads[sid].append(json.loads(fields_json or "{}"))
            except (TypeError, ValueError):
                continue  # a row that is not JSON never votes
        for sid, rs in reads.items():
            cons = consensus_of(rs)
            if cons:
                out[sid] = cons
    return out
