# © 2026 Andy217Ace
"""Reversible retroactive clean-up of train-number duplicates and station aliases.

DEFAULT IS A DRY RUN: it only reads and prints what would change.

    python scripts/merge_number_dups.py --db /var/lib/tabela/tabela.db            # dry run
    python scripts/merge_number_dups.py --db ... --apply --backup-dir /root/x     # merge
    python scripts/merge_number_dups.py --db ... --restore [--batch ID]           # undo

What it does (the dry run prints all three; ``--apply`` does 1 and 2 only):

1. MERGE number duplicates. One physical row on the board was read with a different
   train number ("1"/"11" noise: RE 9209 / 92011, RE 925 / 92511, IR 1581 / 45811,
   RE 109 / 10109, IRN 401 / 4011), so one slot (day + board + station + scheduled
   time) became two services. A pair is merged only when ALL hold:
   - same slot, after the station aliases of step 2;
   - the numbers differ by "1" noise only: inserted/deleted "1" characters, a digit
     read as "1"/"11" (weighted edit cost <= 1.5, where an inserted/deleted "1" and a
     substitution involving a "1" cost 0.5, any other inserted/deleted character 1, and
     any other substitution is forbidden) and the lengths differ (an equal-length
     "1" substitution, 4011 vs 4017, is only LISTED);
   - OR the shorter number (2+ digits, at most 3 fewer) is the tail or the start of
     the longer one (R 93 / R 8093: digits cut, "truncated_number") under a STRICTER
     rule: the long number is the winner and is seen on >= 2 days, and the short number
     has no life of its own (each of its non-ghost services shares a slot with a service
     of the long number). Any other truncation is only LISTED, its ``why_not_merged``
     naming the failed condition (R 19 also running alone on another day stays listed);
   - never seen in the same capture on the same board (two rows in one frame are two
     real trains): neither the two services in this slot, nor the two NUMBERS anywhere
     in the history (``coexist``, app.quality.coexisting_numbers: RE 9209 and 92011 read
     as two rows of one frame on another day are two trains). Such pairs are listed
     with ``why_not_merged`` "coexist: ..." for the user, never merged;
   - the winner (number seen on more days, then more observations, then lower id) is
     the survivor, the other number is the loser. Not transitive: every loser is compared with the winner directly.
   - ghost services (app.quality) are ignored: purge_ghosts.py owns them.
   The loser's observations move to the winner (merge), the loser's row, events,
   quality rows are archived and deleted; the winner's first/last seen cover both,
   its platform / delay are filled only when it has none (a stored read is never
   replaced). Observations keep the number as read (raw data is never rewritten).
2. ALIASES of station names ("KIEV -CHISINAU" -> "KIEV - CHISINAU", "VATRA DORNEI BA"
   -> "VATRA DORNEI BAI") in services.station, observations.station and
   service_quality.station_canonical (exact match only).
3. DIVERGENT scheduled times for the same train number on the same day and board
   (16593, 1658, 10101, 10261): LISTED with evidence, never merged (it can be a
   misread hour or two real services; the decision is the user's).

``--apply`` first writes a full online backup (``sqlite3 backup``, integrity checked)
into ``--backup-dir``; then, in ONE transaction, every row it changes or removes is
archived as JSON in ``merged_rows`` with a batch id (its own table: the restore of
purge_ghosts.py never touches it). The list is recomputed at the moment of
``--apply``. ``--restore`` puts a batch back exactly. Idempotent. Stop the service
(``systemctl stop tabela``) before ``--apply``/``--restore``; afterwards run
``python -m app.quality`` (idempotent) to refresh the winners' quality rows.
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

ARCHIVE = """CREATE TABLE IF NOT EXISTS merged_rows (
    id INTEGER PRIMARY KEY,
    batch TEXT NOT NULL,
    table_name TEXT NOT NULL,
    row_id INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    merged_at TEXT NOT NULL
)"""
ALIASES = {"KIEV -CHISINAU": "KIEV - CHISINAU", "VATRA DORNEI BA": "VATRA DORNEI BAI"}
# weighted edit cost x2 (so integers): "1" ins/del or substitution involving "1" = 1,
# other ins/del = 2, other substitution = forbidden
MAX_COST = 3
EXAMPLES = 25


def _has(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def _in(ids) -> str:
    return ",".join(str(int(i)) for i in ids) or "NULL"


def alias(name: str | None) -> str | None:
    return ALIASES.get(name, name) if name else name


def noise_cost(a: str, b: str) -> int | None:
    """Weighted edit cost x2 between two train numbers using only "1" noise, or None."""
    INF = 10 ** 6
    n, m = len(a), len(b)
    d = [[INF] * (m + 1) for _ in range(n + 1)]
    d[0][0] = 0
    for i in range(n + 1):
        for j in range(m + 1):
            v = d[i][j]
            if v >= INF:
                continue
            if i < n:  # delete a[i]
                d[i + 1][j] = min(d[i + 1][j], v + (1 if a[i] == "1" else 2))
            if j < m:  # insert b[j]
                d[i][j + 1] = min(d[i][j + 1], v + (1 if b[j] == "1" else 2))
            if i < n and j < m:
                if a[i] == b[j]:
                    d[i + 1][j + 1] = min(d[i + 1][j + 1], v)
                elif a[i] == "1" or b[j] == "1":
                    d[i + 1][j + 1] = min(d[i + 1][j + 1], v + 1)
    return d[n][m] if d[n][m] < INF else None


def is_noise_pair(a: int, b: int) -> bool:
    """True when the numbers differ by "1" noise and the lengths differ."""
    sa, sb = str(a), str(b)
    if sa == sb or len(sa) == len(sb) or min(len(sa), len(sb)) < 3:
        return False
    c = noise_cost(sa, sb)
    return c is not None and c <= MAX_COST


def _is_equal_length_one_sub(a: int, b: int) -> bool:
    sa, sb = str(a), str(b)
    if sa == sb or len(sa) != len(sb) or len(sa) < 3:
        return False
    c = noise_cost(sa, sb)
    return c is not None and c <= MAX_COST


def _support(conn: sqlite3.Connection) -> dict[int, int]:
    """Distinct days each train number is a non-ghost service: a real train runs on many
    days, a misread number (92011) almost never repeats."""
    q = _has(conn, "service_quality")
    rows = conn.execute(
        "SELECT s.train_no, COUNT(DISTINCT s.service_date) FROM services s"
        + (" LEFT JOIN service_quality q ON q.service_id = s.id WHERE COALESCE(q.ghost, 0) = 0"
           if q else "") + " GROUP BY s.train_no").fetchall()
    return {r[0]: r[1] for r in rows}


def _is_truncation(a: int, b: int) -> bool:
    """One number is the tail (R 19 / R 5019, R 93 / R 8093) or the start of the other:
    digits were cut."""
    sa, sb = sorted((str(a), str(b)), key=len)
    return (len(sa) >= 2 and len(sa) < len(sb) and len(sb) - len(sa) <= 3
            and (sb.endswith(sa) or sb.startswith(sa)))


def _services(conn: sqlite3.Connection) -> list[dict]:
    q = _has(conn, "service_quality")
    n_obs = ("(SELECT COUNT(*) FROM observations o WHERE o.service_id = s.id)"
             if _has(conn, "observations") else "0")
    rows = conn.execute(
        "SELECT s.*, " + ("COALESCE(q.ghost, 0)" if q else "0") + " AS ghost,"
        f" {n_obs} AS n_obs"
        " FROM services s" + (" LEFT JOIN service_quality q ON q.service_id = s.id" if q else "")
        + " ORDER BY s.id").fetchall()
    return [dict(r) for r in rows]


def _shared_capture(conn, a: int, b: int) -> int:
    """Number of captures where both services were read (two rows in one frame)."""
    if not _has(conn, "observations"):
        return 0
    return conn.execute(
        "SELECT COUNT(*) FROM observations x JOIN observations y"
        " ON y.capture_id = x.capture_id AND y.board = x.board"
        " WHERE x.service_id = ? AND y.service_id = ?", (a, b)).fetchone()[0]


def _brief(s: dict) -> dict:
    return {"id": s["id"], "train": f"{s['train_type']} {s['train_no']}",
            "obs": s["n_obs"], "days": s.get("support"), "first_seen": s["first_seen"], "last_seen": s["last_seen"],
            "status": s["status"], "last_delay": s["last_delay"],
            "last_platform": s["last_platform"]}


def plan_merges(conn: sqlite3.Connection, min_age_min: int = 60,
                now: datetime | None = None) -> dict:
    """{'merges': [(loser, winner)], 'listed': [...]} computed with aliased stations.

    A pair is deferred (listed) while either service is on the board or was seen less
    than ``min_age_min`` minutes ago: it can still change."""
    from app.quality import coexisting_numbers

    cutoff = (now or datetime.now(timezone.utc)) - timedelta(minutes=min_age_min)
    co_cache: dict[tuple[int, int], str | None] = {}

    def coexist(a: int, b: int) -> str | None:
        """First moment both NUMBERS were read in one frame on one board (all history)."""
        k = (min(a, b), max(a, b))
        if k not in co_cache:
            co_cache[k] = coexisting_numbers(conn, k[0], [k[1]]).get(k[1])
        return co_cache[k]

    svc = [s for s in _services(conn) if not s["ghost"]]
    sup = _support(conn)
    for s in svc:
        s["support"] = sup.get(s["train_no"], 0)
    slots: dict[tuple, list[dict]] = {}
    slots_of: dict[int, set[tuple]] = {}  # non-ghost slots of each number
    for s in svc:
        k = (s["board"], s["service_date"], alias(s["station"]), s["sched_time"])
        slots.setdefault(k, []).append(s)
        slots_of.setdefault(s["train_no"], set()).add(k)
    merges: list[dict] = []
    listed: list[dict] = []
    for key, group in sorted(slots.items()):
        if len(group) < 2:
            continue
        # the survivor is the number seen on more days (a real train), then the better
        # observed one, then the older id
        group.sort(key=lambda s: (-s["support"], -s["n_obs"], s["id"]))
        taken: set[int] = set()
        for w in group:
            if w["id"] in taken:
                continue
            for l in group:
                if l["id"] == w["id"] or l["id"] in taken or w["id"] in taken:
                    continue
                rel = ("noise" if is_noise_pair(w["train_no"], l["train_no"]) else
                       "equal_length_sub" if _is_equal_length_one_sub(
                           w["train_no"], l["train_no"]) else
                       "truncated_number" if _is_truncation(w["train_no"], l["train_no"])
                       else None)
                if rel is None:
                    continue
                if rel == "truncated_number":
                    if len(str(l["train_no"])) > len(str(w["train_no"])):
                        continue  # the winner of a truncation is the long number
                elif (l["support"], l["n_obs"], -l["id"]) > (
                        w["support"], w["n_obs"], -w["id"]):
                    continue  # the winner is the more established number
                shared = _shared_capture(conn, w["id"], l["id"])
                co = coexist(w["train_no"], l["train_no"])
                item = {"slot": {"board": key[0], "date": key[1], "station": key[2],
                                 "sched": key[3]},
                        "winner": _brief(w), "loser": _brief(l), "relation": rel,
                        "shared_captures": shared, "coexist_seen_at": co}
                item["winner_established"] = w["support"] >= 2
                recent = any(x["status"] != "gone" or _key(x["last_seen"]) >= cutoff
                             for x in (w, l))
                alone = (sorted(slots_of[l["train_no"]] - slots_of[w["train_no"]])
                         if rel == "truncated_number" else [])
                trunc_ok = (rel == "truncated_number" and w["support"] >= 2 and not alone)
                if (rel == "noise" or trunc_ok) and shared == 0 and co is None and not recent:
                    merges.append(item)
                    taken.add(l["id"])
                else:
                    item["why_not_merged"] = (
                        "both read in the same frame (two real rows)" if shared else
                        "coexist: the two numbers were read in the same frame on %s"
                        " (two real trains): never merged, decision is the user's"
                        % co[:10] if co else
                        "truncated number: the short number lives alone (%s %s %s %s,"
                        " without the long one), listed only"
                        % tuple("-" if v is None else v for v in alone[0]) if alone else
                        "truncated number: the long number is seen on %d day(s) (< 2),"
                        " listed only" % w["support"]
                        if rel == "truncated_number" and not trunc_ok else
                        "equal-length substitution: ambiguous" if rel == "equal_length_sub"
                        else "still on the board / seen less than %d min ago" % min_age_min)
                    listed.append(item)
    return {"merges": merges, "listed": listed}


def divergent_sched(conn: sqlite3.Connection) -> list[dict]:
    """Same train number, same day and board, different scheduled times: evidence only."""
    svc = [s for s in _services(conn) if not s["ghost"]]
    groups: dict[tuple, list[dict]] = {}
    for s in svc:
        groups.setdefault((s["board"], s["service_date"], s["train_no"]), []).append(s)
    out = []
    for (board, date, no), g in sorted(groups.items()):
        if len({s["sched_time"] for s in g}) < 2:
            continue
        g.sort(key=lambda s: s["sched_time"])
        pairs = []
        for i, a in enumerate(g):
            for b in g[i + 1:]:
                if a["sched_time"] != b["sched_time"]:
                    pairs.append({"a": a["id"], "b": b["id"],
                                  "shared_captures": _shared_capture(conn, a["id"], b["id"])})
        shared = any(p["shared_captures"] for p in pairs)
        small = min(s["n_obs"] for s in g)
        out.append({
            "train_no": no, "board": board, "date": date,
            "services": [{**_brief(s), "sched": s["sched_time"], "station": s["station"]}
                         for s in g],
            "pairs": pairs,
            "evidence": ("both times on the board in the same frame: two real services"
                         if shared else
                         "never in one frame; the smaller one has %d observation(s): "
                         "%s" % (small, "probably a misread hour" if small <= 3
                                 else "ambiguous (misread hour or a second run)")),
            "decision": "user"})
    return out


def alias_plan(conn: sqlite3.Connection) -> dict:
    out: dict = {}
    for src, dst in ALIASES.items():
        out[src] = {"to": dst,
                    "services": conn.execute("SELECT COUNT(*) FROM services WHERE station=?",
                                             (src,)).fetchone()[0],
                    "observations": conn.execute(
                        "SELECT COUNT(*) FROM observations WHERE station=?", (src,)
                    ).fetchone()[0] if _has(conn, "observations") else 0,
                    "service_quality": conn.execute(
                        "SELECT COUNT(*) FROM service_quality WHERE station_canonical=?",
                        (src,)).fetchone()[0] if _has(conn, "service_quality") else 0}
    return out


def _archive(conn, batch, table, rows, now, key="id"):
    for r in rows:
        d = dict(r)
        conn.execute("INSERT INTO merged_rows(batch, table_name, row_id, data_json, merged_at)"
                     " VALUES (?,?,?,?,?)", (batch, table, d.get(key, 0), json.dumps(d), now))


# Backup-urile făcute înainte de --apply / --restore: se păstrează doar ultimele N.
# N = 10 e suficient ca să poți reveni la câteva operații recente, fără să umple discul.
BACKUP_PREFIX = "tabela-before-merge-"
BACKUP_KEEP = 10


def _new_backup_path(backup_dir: Path) -> Path:
    """Alege un nume nou și îl creează exclusiv (open 'x'): nu suprascrie niciodată
    un backup existent. Numele conține microsecunde; dacă și așa se ciocnește,
    adaugă un sufix _1, _2, ..."""
    stamp = f"{datetime.now():%Y%m%d-%H%M%S-%f}"
    n = 0
    while True:
        suffix = "" if n == 0 else f"_{n}"
        p = backup_dir / f"{BACKUP_PREFIX}{stamp}{suffix}.db"
        try:
            with open(p, "x"):  # fișier gol, rezervă numele; sqlite îl completează după
                pass
            return p
        except FileExistsError:
            n += 1


def _prune_backups(backup_dir: Path, keep: Path, n: int = BACKUP_KEEP) -> list[str]:
    """Șterge backup-urile mai vechi, păstrând `keep` (cel făcut acum) și ceilalți cei mai
    noi, în total `n`. Atinge doar fișiere `tabela-before-merge-*.db`.

    Sortarea se face după NUME, nu după mtime: numele are un timestamp de lățime fixă
    scris de noi, deci ordinea numelor e ordinea creării; mtime-ul se schimbă când
    copiezi un backup (scp fără -p, restore din alt loc) și ar putea șterge greșit."""
    try:
        others = sorted((p for p in backup_dir.glob(f"{BACKUP_PREFIX}*.db")
                         if p.is_file() and p.name != keep.name),
                        key=lambda p: p.name, reverse=True)
    except OSError as e:
        print(f"avertisment: nu pot curăța backup-urile din {backup_dir}: {e}", file=sys.stderr)
        return []
    removed = []
    for p in others[max(n - 1, 0):]:
        try:
            p.unlink()
            removed.append(str(p))
        except OSError as e:
            print(f"avertisment: nu pot șterge backup-ul vechi {p}: {e}", file=sys.stderr)
    return removed


def backup(db: str, backup_dir: str) -> str:
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    dest = _new_backup_path(Path(backup_dir))
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
    _prune_backups(Path(backup_dir), dest)  # după creare; backup-ul nou nu se șterge niciodată
    return str(dest)


def _apply_aliases(conn, batch, now) -> dict:
    done = {}
    for src, dst in ALIASES.items():
        n = {"services": 0, "observations": 0, "service_quality": 0}
        _archive(conn, batch, "service_station", conn.execute(
            "SELECT id, station FROM services WHERE station=?", (src,)).fetchall(), now)
        n["services"] = conn.execute("UPDATE services SET station=? WHERE station=?",
                                     (dst, src)).rowcount
        if _has(conn, "observations"):
            _archive(conn, batch, "observation_station", conn.execute(
                "SELECT id, station FROM observations WHERE station=?", (src,)).fetchall(), now)
            n["observations"] = conn.execute(
                "UPDATE observations SET station=? WHERE station=?", (dst, src)).rowcount
        if _has(conn, "service_quality"):
            _archive(conn, batch, "quality_station", conn.execute(
                "SELECT service_id AS id, station_canonical FROM service_quality"
                " WHERE station_canonical=?", (src,)).fetchall(), now)
            n["service_quality"] = conn.execute(
                "UPDATE service_quality SET station_canonical=? WHERE station_canonical=?",
                (dst, src)).rowcount
        done[src] = n
    return done


def _merge_one(conn, batch, now, loser_id: int, winner_id: int) -> dict:
    lo = conn.execute("SELECT * FROM services WHERE id=?", (loser_id,)).fetchone()
    wi = conn.execute("SELECT * FROM services WHERE id=?", (winner_id,)).fetchone()
    moved = 0
    if _has(conn, "observations"):
        links = conn.execute("SELECT id, service_id FROM observations WHERE service_id=?",
                             (loser_id,)).fetchall()
        _archive(conn, batch, "observation_links", links, now)
        moved = conn.execute("UPDATE observations SET service_id=? WHERE service_id=?",
                             (winner_id, loser_id)).rowcount
    # winner: archive old values, widen the life, fill only what is missing
    _archive(conn, batch, "service_fields", [{
        "id": winner_id, "first_seen": wi["first_seen"], "last_seen": wi["last_seen"],
        "last_platform": wi["last_platform"], "last_delay": wi["last_delay"],
        "last_read": wi["last_read"], "delay_read_at": wi["delay_read_at"],
        "flagged": wi["flagged"]}], now)
    fs = min(wi["first_seen"], lo["first_seen"], key=_key)
    ls = max(wi["last_seen"], lo["last_seen"], key=_key)
    plat = wi["last_platform"] if wi["last_platform"] is not None else lo["last_platform"]
    sets = {"first_seen": fs, "last_seen": ls, "last_platform": plat,
            "flagged": 1 if (wi["flagged"] or lo["flagged"]) else 0}
    if wi["delay_read_at"] is None and lo["delay_read_at"] is not None:
        sets.update(last_delay=lo["last_delay"], last_read=lo["last_read"],
                    delay_read_at=lo["delay_read_at"])
    conn.execute("UPDATE services SET " + ", ".join(f"{k}=?" for k in sets) + " WHERE id=?",
                 [*sets.values(), winner_id])
    _archive(conn, batch, "services", [lo], now)
    _archive(conn, batch, "events", conn.execute(
        "SELECT * FROM events WHERE service_id=?", (loser_id,)).fetchall(), now)
    if _has(conn, "event_quality"):
        _archive(conn, batch, "event_quality", conn.execute(
            "SELECT q.* FROM event_quality q JOIN events e ON e.id = q.event_id"
            " WHERE e.service_id=?", (loser_id,)).fetchall(), now, key="event_id")
        conn.execute("DELETE FROM event_quality WHERE event_id IN"
                     " (SELECT id FROM events WHERE service_id=?)", (loser_id,))
    if _has(conn, "service_quality"):
        _archive(conn, batch, "service_quality", conn.execute(
            "SELECT * FROM service_quality WHERE service_id=?", (loser_id,)).fetchall(), now,
            key="service_id")
        conn.execute("DELETE FROM service_quality WHERE service_id=?", (loser_id,))
    conn.execute("DELETE FROM events WHERE service_id=?", (loser_id,))
    conn.execute("DELETE FROM services WHERE id=?", (loser_id,))
    return {"observations_moved": moved}


def _key(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def apply(conn: sqlite3.Connection, min_age_min: int = 60) -> tuple[str, dict]:
    """Recompute inside the write transaction, then alias + merge (all archived)."""
    from app.observations import refresh_trains

    batch = "MD" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(ARCHIVE)
        done: dict = {"aliases": _apply_aliases(conn, batch, now)}
        pl = plan_merges(conn, min_age_min)  # after the aliases: final station names
        nos, moved = set(), 0
        for m in pl["merges"]:
            nos.update((m["winner"]["id"], m["loser"]["id"]))
        nos = {conn.execute("SELECT train_no FROM services WHERE id=?", (i,)).fetchone()[0]
               for i in nos if conn.execute("SELECT 1 FROM services WHERE id=?", (i,)).fetchone()}
        for m in pl["merges"]:
            moved += _merge_one(conn, batch, now, m["loser"]["id"], m["winner"]["id"])[
                "observations_moved"]
        done["services_merged"] = len(pl["merges"])
        done["observations_moved"] = moved
        if _has(conn, "trains") and pl["merges"]:
            # only the catalog rows of the numbers involved; archived whole, so the
            # restore puts them back exactly (other stored rows are never touched)
            _archive(conn, batch, "trains_before", conn.execute(
                f"SELECT * FROM trains WHERE train_no IN ({_in(nos)})").fetchall(), now,
                key="train_no")
            refresh_trains(conn, nos)
            gone = conn.execute(
                f"SELECT train_no FROM trains WHERE train_no IN ({_in(nos)})"
                " AND train_no NOT IN (SELECT train_no FROM services)").fetchall()
            conn.execute(f"DELETE FROM trains WHERE train_no IN ({_in(r[0] for r in gone)})")
            done["catalog_rows_removed"] = len(gone)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return batch, done


def restore(conn: sqlite3.Connection, batch: str | None = None) -> dict:
    from app.observations import refresh_trains

    if not _has(conn, "merged_rows"):
        return {}
    batches = [b for (b,) in conn.execute("SELECT DISTINCT batch FROM merged_rows")]
    if batch is not None:
        batches = [b for b in batches if b == batch]
    out: dict = {}
    conn.execute("BEGIN IMMEDIATE")
    try:
        nos = set()
        restored_catalog = False
        order = ("services", "events", "event_quality", "service_quality",
                 "observation_links", "service_fields", "service_station",
                 "observation_station", "quality_station", "trains_before")
        for table in order:
            for b in batches:
                for rid, data in conn.execute(
                        "SELECT id, data_json FROM merged_rows WHERE batch=? AND table_name=?"
                        " ORDER BY id DESC", (b, table)).fetchall():
                    d = json.loads(data)
                    if table == "observation_links":
                        conn.execute("UPDATE observations SET service_id=? WHERE id=?",
                                     (d["service_id"], d["id"]))
                    elif table == "service_fields":
                        cols = [c for c in d if c != "id"]
                        conn.execute("UPDATE services SET " + ", ".join(f"{c}=?" for c in cols)
                                     + " WHERE id=?", [d[c] for c in cols] + [d["id"]])
                        nos.add(conn.execute("SELECT train_no FROM services WHERE id=?",
                                             (d["id"],)).fetchone()[0])
                    elif table == "service_station":
                        conn.execute("UPDATE services SET station=? WHERE id=?",
                                     (d["station"], d["id"]))
                    elif table == "observation_station":
                        conn.execute("UPDATE observations SET station=? WHERE id=?",
                                     (d["station"], d["id"]))
                    elif table == "trains_before":
                        cols = list(d)
                        conn.execute(f"INSERT OR REPLACE INTO trains({', '.join(cols)})"
                                     f" VALUES ({', '.join('?' * len(cols))})",
                                     [d[c] for c in cols])
                        restored_catalog = True
                    elif table == "quality_station":
                        conn.execute("UPDATE service_quality SET station_canonical=?"
                                     " WHERE service_id=?", (d["station_canonical"], d["id"]))
                    else:
                        if table == "services":
                            nos.add(d["train_no"])
                        cols = list(d)
                        conn.execute(f"INSERT OR IGNORE INTO {table}({', '.join(cols)})"
                                     f" VALUES ({', '.join('?' * len(cols))})",
                                     [d[c] for c in cols])
                    conn.execute("DELETE FROM merged_rows WHERE id=?", (rid,))
                    out[table] = out.get(table, 0) + 1
        if _has(conn, "trains") and nos and not restored_catalog:
            refresh_trains(conn, nos)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return out


def report(conn: sqlite3.Connection, min_age_min: int = 60) -> dict:
    # slots are computed with the aliased stations, as --apply does (aliases run first)
    pl = plan_merges(conn, min_age_min)
    by_no = {}
    for m in pl["merges"]:
        k = f"{m['loser']['train']} -> {m['winner']['train']}"
        by_no[k] = by_no.get(k, 0) + 1
    return {
        "aliases": alias_plan(conn),
        "merge": {
            "services_affected": len(pl["merges"]),
            "winner_seen_on_less_than_2_days": sum(
                1 for m in pl["merges"] if not m["winner_established"]),
            "observations_to_move": sum(m["loser"]["obs"] for m in pl["merges"]),
            "by_number_pair": dict(sorted(by_no.items(), key=lambda kv: -kv[1])),
            "list": pl["merges"]},
        "listed_not_merged": pl["listed"],
        "divergent_sched_listed_only": divergent_sched(conn)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--db", default=os.environ.get("DB_PATH", "tabela.db"))
    p.add_argument("--apply", action="store_true", help="merge (archived, reversible)")
    p.add_argument("--backup-dir", help="required with --apply: full DB backup goes here")
    p.add_argument("--restore", action="store_true", help="put merged rows back")
    p.add_argument("--batch", help="with --restore: only this batch")
    p.add_argument("--min-age-min", type=int, default=60,
                   help="defer pairs seen more recently than this (default 60)")
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
        rep = {"mode": "apply" if a.apply else "dry-run", **report(conn, a.min_age_min)}
        if a.apply:
            rep["backup"] = backup(a.db, a.backup_dir)
            rep["batch"], rep["applied"] = apply(conn, a.min_age_min)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
