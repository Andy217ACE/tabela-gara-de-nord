# © 2026 Andy217Ace
"""Journeys (= `services` rows) and their final result.

A journey is ONE appearance of a train on one board (arrivals or departures at
București Nord) for one service date. Its delay is the last value READ on the
board (`last_delay`), valid only with proof of the reading (`delay_read_at`, v6).

Final result rules (never assumed):
- in_progress  the journey is still listed on the board;
- unknown      it disappeared, but its delay was never read;
- unconfirmed  the disappearance was not observed (reading interrupted), or it
               disappeared before the estimated time (scheduled + delay), or the last
               delay reading is older than FINAL_READ_MAX_GAP_MIN before disappearing;
- confirmed    observed disappearance at/after the estimated time, with the delay
               read shortly before. Only then `final_delay` is set.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bucharest")
FINAL_READ_MAX_GAP_MIN_DEFAULT = 15
STATES = ("in_progress", "confirmed", "unconfirmed", "unknown")
LABELS = {
    "in_progress": "În desfășurare (încă pe tabelă)",
    "confirmed": "Rezultat final confirmat",
    "unconfirmed": "Rezultat neconfirmat",
    "unknown": "Rezultat necunoscut",
}
BOARD_LABEL = {"arrival": "Sosire", "departure": "Plecare"}

# Columns every journey query returns (s = services). gone_at/appeared_at: latest events.
JOURNEY_SQL = (
    "SELECT s.id, s.board, s.service_date, s.train_type, s.train_no, s.station, s.operator,"
    " s.sched_time, s.first_seen, s.last_seen, s.last_delay, s.last_platform, s.status,"
    " s.uncertain, s.delay_read_at,"
    " (SELECT e.ts FROM events e WHERE e.service_id = s.id AND e.kind = 'gone'"
    "  ORDER BY e.id DESC LIMIT 1) AS gone_at,"
    " (SELECT e.ts FROM events e WHERE e.service_id = s.id AND e.kind = 'appeared'"
    "  ORDER BY e.id DESC LIMIT 1) AS appeared_at"
    " FROM services s"
)


def final_gap_min() -> int:
    try:
        v = int(os.environ.get("FINAL_READ_MAX_GAP_MIN", FINAL_READ_MAX_GAP_MIN_DEFAULT))
    except ValueError:
        return FINAL_READ_MAX_GAP_MIN_DEFAULT
    return v if 1 <= v <= 240 else FINAL_READ_MAX_GAP_MIN_DEFAULT


def _dt(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        d = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=TZ) if d.tzinfo is None else d.astimezone(TZ)


def sched_at(service_date: str, sched_time: str) -> datetime:
    """Scheduled moment (Europe/Bucharest) of a journey: its service date + HH:MM."""
    d = date.fromisoformat(service_date)
    hh, mm = (int(p) for p in sched_time.split(":"))
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=TZ)


def _hm(d: datetime) -> str:
    return d.strftime("%H:%M")


def result(s, gap_min: int | None = None) -> dict:
    """Final result of one journey row (mapping with the JOURNEY_SQL columns)."""
    gap = timedelta(minutes=gap_min if gap_min is not None else final_gap_min())
    read_at = _dt(s["delay_read_at"])
    known = read_at is not None
    observed = s["last_delay"] if known else None
    sched = sched_at(s["service_date"], s["sched_time"])
    est = sched + timedelta(minutes=observed) if known else None
    gone, appeared = _dt(s["gone_at"]), _dt(s["appeared_at"])
    disappeared = gone if (s["status"] == "gone" and gone is not None
                           and (appeared is None or gone >= appeared)) else None
    reason = None
    if s["status"] != "gone":
        state = "in_progress"
    elif not known:
        state = "unknown"
        reason = "Întârzierea nu a fost citită niciodată pentru această călătorie."
    elif disappeared is None:
        state = "unconfirmed"
        reason = ("Dispariția de pe tabelă nu a fost observată "
                  "(citirea tabelei a fost întreruptă).")
    elif disappeared < est:
        state = "unconfirmed"
        reason = f"A dispărut de pe tabelă înainte de ora estimată ({_hm(est)})."
    elif disappeared - read_at > gap:
        state = "unconfirmed"
        reason = (f"Ultima întârziere citită ({_hm(read_at)}) este cu peste "
                  f"{int(gap.total_seconds() // 60)} min mai veche decât dispariția.")
    else:
        state = "confirmed"
    return {
        "state": state,
        "label": LABELS[state],
        "reason": reason,
        "delay_known": known,
        "observed_delay": observed,
        "final_delay": observed if state == "confirmed" else None,
        "delay_read_at": read_at.isoformat() if read_at else None,
        "sched_at": sched.isoformat(),
        "estimated_at": est.isoformat() if est else None,
        "disappeared_at": disappeared.isoformat() if disappeared else None,
    }


def as_dict(s, gap_min: int | None = None) -> dict:
    """Public shape of one journey (no raw OCR text)."""
    return {
        "id": s["id"], "board": s["board"], "service_date": s["service_date"],
        "train_type": s["train_type"], "train_no": s["train_no"], "station": s["station"],
        "operator": s["operator"], "sched_time": s["sched_time"],
        "platform": s["last_platform"], "status": s["status"],
        "first_seen": s["first_seen"], "last_seen": s["last_seen"],
        "uncertain": bool(s["uncertain"]),
        "result": result(s, gap_min),
    }


def query(store, where: list[str] | None = None, args: list | None = None,
          order: str = "s.service_date, s.sched_time, s.board, s.train_no",
          limit: int | None = None) -> list:
    sql = JOURNEY_SQL
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + order
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    with store._lock:
        return store._conn.execute(sql, args or []).fetchall()


def delay_series(store, service_id: int, s) -> list[dict]:
    """Delay READINGS of one journey, chronological: observations with a read delay,
    delay events (the new value is a reading), and the latest proven value. Unread
    frames are never points (a missing value is not 0)."""
    pts: dict[str, dict] = {}

    def add(stamp, value, source):
        t = _dt(stamp)
        if t is None or value is None:
            return
        pts.setdefault(t.isoformat(), {"t": t.isoformat(), "delay": int(value), "source": source})

    with store._lock:
        c = store._conn
        has_obs = c.execute("SELECT 1 FROM sqlite_master WHERE type='table'"
                            " AND name='observations'").fetchone()
        obs = c.execute("SELECT observed_at, delay_min FROM observations WHERE service_id=?"
                        " AND delay_read=1 AND delay_min IS NOT NULL"
                        " AND validation_state IN ('ok', 'uncertain') ORDER BY id",
                        (service_id,)).fetchall() if has_obs else []
        evs = c.execute("SELECT ts, old, new FROM events WHERE service_id=? AND kind='delay'"
                        " ORDER BY ts, id", (service_id,)).fetchall()
    for e in evs:
        add(e["ts"], _int(e["new"]), "event")
    if evs and (_int(evs[0]["old"]) or 0) > 0:
        # a non-zero previous value was a real reading, held since the first sighting
        add(s["first_seen"], _int(evs[0]["old"]), "event")
    # An OCR reading the store did not apply (e.g. a one-frame jump "15" -> "945") is not
    # drawn: keep an observation only if its value was applied (a delay event / the
    # stored value) or the next reading confirms it (the two-readings rule).
    applied = {_int(e["new"]) for e in evs} | {_int(e["old"]) for e in evs}
    if s["delay_read_at"]:
        applied.add(s["last_delay"])
    for k, o in enumerate(obs):
        nxt = obs[k + 1]["delay_min"] if k + 1 < len(obs) else None
        if o["delay_min"] in applied or o["delay_min"] == nxt:
            add(o["observed_at"], o["delay_min"], "observation")
    if s["delay_read_at"]:
        add(s["delay_read_at"], s["last_delay"], "last_read")
    return sorted(pts.values(), key=lambda p: _dt(p["t"]))


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def detail(store, service_id: int) -> dict | None:
    rows = query(store, ["s.id = ?"], [service_id])
    if not rows:
        return None
    s = rows[0]
    with store._lock:
        evs = store._conn.execute("SELECT ts, kind, old, new FROM events WHERE service_id=?"
                                  " ORDER BY ts, id", (service_id,)).fetchall()
    d = as_dict(s)
    d["events"] = [dict(e) for e in evs]
    d["delay_series"] = delay_series(store, service_id, s)
    d["final_read_max_gap_min"] = final_gap_min()
    return d
