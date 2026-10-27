# © 2026 Andy217Ace
"""Statistici v2: one aggregated payload for the #statistici page (/api/stats/overview).

- Rows come from a separate READ-ONLY SQLite connection (`file:…?mode=ro`), so the
  statistics never wait for (or hold) the store lock the OCR ingest uses; an in-memory
  database (tests) falls back to the store connection under its lock.
- `build()` is pure: journeys (+ computed result), weather rows and a few counters in,
  JSON out. Rules: the delay is the one READ on the București Nord board; only finished
  journeys with a read delay count (missing is never 0); arrivals and departures are
  never mixed; every figure carries N; below the minimum sample percentages are withheld;
  ghosts and the reduced-quality period are excluded (app.quality); the weather section
  only shows figures with enough days (correlation is not causation).
- `overview()` caches each payload for STATS_CACHE_TTL_S seconds (default 60) and computes
  one payload at a time (no stampede on a cold cache).
"""
from __future__ import annotations

import bisect
import logging
import os
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from collections import OrderedDict
from pathlib import Path

from app import journeys, stations, stats
from app import quality as dq
from app import stats_problems as sp

TZ = journeys.TZ
log = logging.getLogger(__name__)
PERIODS = ("1", "7", "30", "all")
HISTORY_MIN_DAYS = 7          # below: "date insuficiente încă" + no weather figures
WEATHER_MIN_DAYS = 7
WEATHER_MATCH_MIN = 30        # a journey gets the weather observed within ±30 min
CACHE_TTL_DEFAULT = 60
CACHE_MAX = 32
ROUTES_LIMIT = 5
TEMP_BANDS = (("lt5", "sub 5 °C", None, 5), ("5-15", "5–15 °C", 5, 15),
              ("15-25", "15–25 °C", 15, 25), ("ge25", "25 °C sau mai mult", 25, None))
BOARD_PL = {"arrival": "Sosiri", "departure": "Plecări"}
BOARD_AT = {"arrival": "la sosiri", "departure": "la plecări"}
SETS = ("distribution", "hourly", "heatmap", "daily", "operators", "types", "routes",
        "traffic", "platforms", "weather")


# ---- small helpers --------------------------------------------------------------------

def period_range(perioada: str, today: date) -> tuple[date | None, date | None]:
    """`1` = today, `7` / `30` = the last 7 / 30 days including today, `all` = everything."""
    if perioada not in PERIODS:
        raise ValueError(perioada)
    if perioada == "all":
        return None, None
    return today - timedelta(days=int(perioada) - 1), today


def _fmt(x) -> str:
    """Romanian number: 37,5 / 3 (no trailing ,0)."""
    if x is None:
        return "—"
    x = round(float(x), 1)
    return str(int(x)) if x == int(x) else f"{x:.1f}".replace(".", ",")


def _pl(n: int, one: str, many: str) -> str:
    # Romanian: 1 călătorie, 2–19 călătorii, 20+ „de călătorii”
    if n == 1:
        return f"1 {one}"
    if n == 0 or 1 <= n % 100 <= 19:
        return f"{n} {many}"
    return f"{n} de {many}"


def _hour(h: int) -> str:
    return f"{h:02d}:00–{h:02d}:59"


def _between(h: int) -> str:
    return f"între {h:02d}:00 și {h:02d}:59"


def _ttl() -> int:
    try:
        v = int(os.environ.get("STATS_CACHE_TTL_S", CACHE_TTL_DEFAULT))
    except ValueError:
        return CACHE_TTL_DEFAULT
    return v if 0 <= v <= 3600 else CACHE_TTL_DEFAULT


def empty_extra() -> dict:
    return {"excluded": {"ghost": 0, "low_quality": 0},
            "observations": {"ok": 0, "uncertain": 0, "rejected_low_conf": 0, "incomplete": 0},
            "history": {"first": None, "last": None, "days": 0},
            "low_quality_dates": {}, "delay_events": {}, "gaps": []}


# ---- reading (read-only connection) ----------------------------------------------------

@contextmanager
def _reader(store):
    """A read-only connection of its own; `:memory:` (tests) or a failure to open one:
    the store connection under the store lock."""
    path = getattr(store, "path", ":memory:")
    conn = None
    if path and path != ":memory:":
        try:
            conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True,
                                   check_same_thread=False, timeout=5)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = ON")
        except sqlite3.Error as e:
            # never silently: the fallback holds the store (OCR ingest) lock while computing
            log.warning("statistici: conexiunea read-only a eșuat (%s); folosesc store-ul", e)
            conn = None
    if conn is not None:
        try:
            conn.execute("BEGIN")  # one snapshot for every query of this computation
            yield conn
        finally:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            conn.close()
        return
    with store._lock:
        yield store._conn


def _has(conn, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,)).fetchone() is not None


def _local(stamp: str) -> str:
    """A stored timestamp as local (Europe/Bucharest) ISO, minutes precision."""
    try:
        t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return str(stamp)
    t = t.replace(tzinfo=TZ) if t.tzinfo is None else t.astimezone(TZ)
    return t.isoformat(timespec="minutes")


def _utc(d: date) -> str:
    """Local midnight of `d` as the UTC string the observation tables store."""
    return datetime(d.year, d.month, d.day, tzinfo=TZ).astimezone(timezone.utc).isoformat()


def fetch(store, p: stats.Params) -> tuple[list[dict], list[dict], dict]:
    w, a = p.where()
    gap = journeys.final_gap_min()
    extra = empty_extra()
    with _reader(store) as c:
        rows = c.execute(journeys.JOURNEY_SQL + " WHERE " + " AND ".join(w), a).fetchall()
        # excluded journeys in the same board/period (ghost first, then reduced quality)
        fw, fa = [], []
        if p.board:
            fw.append("s.board = ?")
            fa.append(p.board)
        if p.date_from:
            fw.append("s.service_date >= ?")
            fa.append(p.date_from.isoformat())
        if p.date_to:
            fw.append("s.service_date <= ?")
            fa.append(p.date_to.isoformat())
        ex = c.execute("SELECT COALESCE(SUM(q.ghost = 1), 0),"
                       " COALESCE(SUM(q.ghost = 0 AND q.low_quality = 1), 0)"
                       " FROM services s JOIN service_quality q ON q.service_id = s.id"
                       + (" WHERE " + " AND ".join(fw) if fw else ""), fa).fetchone()
        extra["excluded"] = {"ghost": ex[0],
                             "low_quality": 0 if dq.include_low_quality() else ex[1]}
        if not dq.include_low_quality():
            extra["low_quality_dates"] = dict(c.execute(
                "SELECT s.service_date, COUNT(*) FROM services s JOIN service_quality q"
                " ON q.service_id = s.id WHERE q.ghost = 0 AND q.low_quality = 1"
                + "".join(" AND " + x for x in fw) + " GROUP BY s.service_date", fa).fetchall())
        # delay events of these journeys (readings only: suspect events left out) -> did the
        # delay grow after it was first announced (app.stats_problems.growth)
        sus = (" AND e.id NOT IN (SELECT event_id FROM event_quality WHERE suspect = 1)"
               if _has(c, "event_quality") else "")
        evs: dict = {}
        for r in c.execute("SELECT e.service_id, e.old, e.new FROM events e JOIN services s"
                           " ON s.id = e.service_id WHERE e.kind = 'delay'"
                           + "".join(" AND " + x for x in fw) + sus
                           + " ORDER BY e.service_id, e.ts, e.id", fa).fetchall():
            evs.setdefault(r[0], []).append({"old": r[1], "new": r[2]})
        extra["delay_events"] = evs
        # pauses between two successful board readings (coverage); julianday() orders the
        # local timestamps correctly across a DST change
        rw, ra = ["ok = 1"], []
        if p.date_from:
            rw.append("julianday(ts) >= julianday(?)")
            ra.append(_utc(p.date_from))
        if p.date_to:
            rw.append("julianday(ts) < julianday(?)")
            ra.append(_utc(p.date_to + timedelta(days=1)))
        extra["gaps"] = [
            {"start": _local(g[0]), "end": _local(g[1]), "minutes": int(round(g[2]))}
            for g in c.execute(
                "SELECT prev, ts, (julianday(ts) - julianday(prev)) * 1440 FROM ("
                " SELECT ts, LAG(ts) OVER (ORDER BY julianday(ts)) AS prev FROM runs WHERE "
                + " AND ".join(rw) + ") WHERE prev IS NOT NULL AND"
                " (julianday(ts) - julianday(prev)) * 1440 > ?", ra + [sp.GAP_MIN]).fetchall()]
        hist = c.execute("SELECT MIN(s.service_date), MAX(s.service_date),"
                         " COUNT(DISTINCT s.service_date) FROM services s WHERE "
                         + dq.public_services_where("s")).fetchone()
        extra["history"] = {"first": hist[0], "last": hist[1], "days": hist[2] or 0}
        if _has(c, "observations"):
            ow, oa = [], []
            if p.date_from:
                ow.append("observed_at >= ?")
                oa.append(_utc(p.date_from))
            if p.date_to:
                ow.append("observed_at < ?")
                oa.append(_utc(p.date_to + timedelta(days=1)))
            if p.board:
                ow.append("board = ?")
                oa.append(p.board)
            for st, n in c.execute("SELECT validation_state, COUNT(*) FROM observations"
                                   + (" WHERE " + " AND ".join(ow) if ow else "")
                                   + " GROUP BY validation_state", oa).fetchall():
                extra["observations"][st] = n
        wx = []
        if _has(c, "weather_observations"):
            ww, wa = [], []
            if p.date_from:
                ww.append("observed_at >= ?")
                wa.append(_utc(p.date_from - timedelta(days=1)).replace("+00:00", "Z"))
            wx = [dict(r) for r in c.execute(
                "SELECT observed_at, temperature_c, precipitation_mm, wind_speed_kmh"
                " FROM weather_observations" + (" WHERE " + " AND ".join(ww) if ww else "")
                + " ORDER BY observed_at", wa).fetchall()]
    out = []
    for s in rows:
        d = dict(s)
        d["result"] = journeys.result(s, gap)
        out.append(d)
    return out, wx, extra


# ---- aggregation (pure) ----------------------------------------------------------------

def _summ(vals, p) -> dict:
    return stats.summarize(vals, p.on_time, p.min_sample)


def _groups(js, p, keyfn) -> dict:
    """key -> {"journeys": all public journeys, "delays": counted delays}."""
    g: dict = defaultdict(lambda: {"journeys": 0, "delays": []})
    for j in js:
        k = keyfn(j)
        g[k]["journeys"] += 1
        if stats.counted(j, p):
            g[k]["delays"].append(j["result"]["observed_delay"])
    return g


def _ranked(js, p, keyfn) -> list[dict]:
    """Operators / train types: eligible (N >= min) first by % on time, then the small ones
    by N (raw figures, no percentages)."""
    out = [{"key": k, "journeys": v["journeys"], **_summ(v["delays"], p)}
           for k, v in _groups(js, p, keyfn).items() if k]
    out.sort(key=lambda e: (not e["sufficient"],
                            -(e["on_time_pct"] or 0) if e["sufficient"] else -e["n"],
                            e["mean"] if e["mean"] is not None else 1e9, e["key"]))
    return out


def _distribution(vals, p) -> list[dict]:
    total = len(vals)
    ok = total >= p.min_sample
    return [dict(b, pct=round(100.0 * b["n"] / total, 1) if ok and total else None)
            for b in stats.distribution(vals)]


def _route(e) -> dict:
    s = e["stats"]
    return {"key": e["station"], "journeys": e["journeys"], "trains": e["trains"],
            "n": s["n"], "mean": s["mean"], "median": s["median"],
            "on_time_pct": s["on_time_pct"]}


def _weather(js, wx, p, boards) -> dict:
    """Weather groups per board (arrivals and departures are never mixed); the top level
    sums them up (ok when any board is)."""
    per = {b: _weather_board([j for j in js if j["board"] == b], wx, p) for b in boards}
    days = set()
    for v in per.values():
        days |= v.pop("_days")
    return {"status": "ok" if any(v["status"] == "ok" for v in per.values()) else "collecting",
            "matched": sum(v["matched"] for v in per.values()), "days": len(days),
            "needed_days": WEATHER_MIN_DAYS, "observations": len(wx),
            "note": ("Corelație, nu cauzalitate: vremea coincide cu alți factori (ora din zi, "
                     "sezonul, lucrările); o diferență între grupe nu arată că vremea a "
                     "produs întârzierea."),
            "boards": per}


def _weather_board(js, wx, p) -> dict:
    base = {"status": "collecting", "matched": 0, "days": 0, "groups": {}, "_days": set()}
    if not wx:
        return base
    stamps, keep = [], []
    for r in wx:
        try:
            t = datetime.fromisoformat(r["observed_at"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        stamps.append(t.timestamp())
        keep.append(r)
    lim = WEATHER_MATCH_MIN * 60
    matched = []
    for j in js:
        if not stats.counted(j, p):
            continue
        ts = journeys.sched_at(j["service_date"], j["sched_time"]).timestamp()
        i = bisect.bisect_left(stamps, ts)
        best = min((k for k in (i - 1, i) if 0 <= k < len(stamps)),
                   key=lambda k: abs(stamps[k] - ts), default=None)
        if best is not None and abs(stamps[best] - ts) <= lim:
            matched.append((j, keep[best]))
    dset = {j["service_date"] for j, _ in matched}
    days = len(dset)
    base.update(matched=len(matched), days=days, _days=dset)
    precip, temp = defaultdict(list), defaultdict(list)
    for j, w in matched:
        v = j["result"]["observed_delay"]
        if w["precipitation_mm"] is not None:
            precip["wet" if w["precipitation_mm"] > 0 else "dry"].append(v)
        t = w["temperature_c"]
        if t is not None:
            for key, _label, lo, hi in TEMP_BANDS:
                if (lo is None or t >= lo) and (hi is None or t < hi):
                    temp[key].append(v)
                    break
    groups = {
        "precip": [{"key": k, "label": lab, **_summ(precip[k], p)}
                   for k, lab in (("dry", "Fără precipitații"), ("wet", "Cu precipitații (> 0 mm)"))
                   if precip.get(k)],
        "temp": [{"key": k, "label": lab, **_summ(temp[k], p)}
                 for k, lab, _lo, _hi in TEMP_BANDS if temp.get(k)],
    }
    enough = any(sum(1 for g in gs if g["sufficient"]) >= 2 for gs in groups.values())
    if days >= WEATHER_MIN_DAYS and enough:
        base.update(status="ok", groups=groups)
    return base


def _insights(boards, by_board, hourly, problems, traffic, platforms, quality, p):
    out = []
    if not any(by_board[b]["journeys"] for b in boards):
        return ["Încă nu există călătorii observate pentru filtrele alese."]
    for b in boards:
        s = by_board[b]
        n = s["n"]
        if not n:
            out.append(f"{BOARD_PL[b]}: nicio călătorie încheiată cu întârziere citită (N = 0).")
        elif not s["sufficient"]:
            out.append(f"{BOARD_PL[b]}: doar {_pl(n, 'călătorie încheiată', 'călătorii încheiate')}"
                       f" cu întârziere citită (N = {n}) — prea puține pentru procente "
                       f"(minimum {p.min_sample}).")
        else:
            were = "a fost" if s["on_time"] == 1 else "au fost"
            had = "a avut" if s["over_30"] == 1 else "au avut"
            out.append(f"{BOARD_PL[b]}: din {_pl(n, 'călătorie încheiată', 'călătorii încheiate')}"
                       f" cu întârziere citită, {s['on_time']} ({_fmt(s['on_time_pct'])} %) {were}"
                       f" la timp (≤ {p.on_time} min); mediana {_fmt(s['median'])} min, iar "
                       f"{s['over_30']} {had} peste 30 min (N = {n}).")
    for b in boards:
        ok = [h for h in hourly[b] if h["sufficient"]]
        if not ok:
            continue
        # ranked by the MEDIAN, then the count above 30 min: a mean is moved by one extreme
        # case (Beta 1.17: one 390-min train made 23:00 the „worst hour”, median 5 min)
        worst = max(ok, key=lambda h: (h["median"], h["over_30"], -h["key"]))
        if worst["median"] <= p.on_time:
            most = max(ok, key=lambda h: (h["over_30"], -h["key"]))
            out.append(f"{BOARD_PL[b]}: la fiecare oră cu destule date mediana e la timp "
                       f"(≤ {p.on_time} min)" + (
                           f"; cele mai multe întârzieri peste 30 min: {_between(most['key'])} "
                           f"({most['over_30']} din N = {most['n']})." if most["over_30"] else "."))
            continue
        line = (f"{BOARD_PL[b]}: cea mai mare întârziere mediană o au trenurile programate "
                f"{_between(worst['key'])} — {_fmt(worst['median'])} min, cu "
                f"{worst['over_30']} peste 30 min (N = {worst['n']})")
        best = min(ok, key=lambda h: (h["median"], h["over_30"], h["key"]))
        if len(ok) >= 2 and best["median"] < worst["median"]:
            line += (f"; cea mai mică, {_between(best['key'])} — {_fmt(best['median'])} min "
                     f"(N = {best['n']})")
        out.append(line + ".")
    for b in boards:
        r = (problems.get("routes") or {}).get(b) or {}
        if r.get("worst") and (r["worst"][0]["median"] or 0) > p.on_time:
            e = r["worst"][0]
            way = "din" if b == "arrival" else "spre"
            out.append(f"Cea mai mare întârziere mediană {BOARD_AT[b]}: trenurile {way} "
                       f"{e['key'].title()} — {_fmt(e['median'])} min "
                       f"(N = {e['n']}, {_pl(e['trains'], 'tren', 'trenuri')}).")
    per_hour = [sum(traffic[b][h] for b in boards) for h in range(24)]
    if any(per_hour) and traffic["days"]:
        h = max(range(24), key=lambda k: (per_hour[k], -k))
        out.append(f"Cea mai aglomerată oră: {_hour(h)}, cu "
                   f"{_pl(per_hour[h], 'călătorie programată', 'călătorii programate')} în "
                   f"{_pl(traffic['days'], 'zi cu date', 'zile cu date')} "
                   f"(≈ {_fmt(per_hour[h] / traffic['days'])} pe zi).")
    lines = Counter()
    for b in boards:
        for x in platforms[b]["lines"]:
            lines[x["line"]] += x["n"]
    if lines:
        line, n = max(lines.items(), key=lambda kv: (kv[1], -kv[0]))
        out.append(f"Linia folosită cel mai des: linia {line} ({n} din "
                   f"{_pl(sum(lines.values()), 'călătorie', 'călătorii')} cu linia citită).")
    if quality["finished"]:
        miss = quality["finished"] - quality["delay_known"]
        share = (f" ({_fmt(quality['delay_known_pct'])} %)"
                 if quality["finished"] >= p.min_sample else "")
        out.append(f"Întârzierea a fost citită la {quality['delay_known']} din "
                   f"{_pl(quality['finished'], 'călătorie încheiată', 'călătorii încheiate')}"
                   f"{share}"
                   + (f"; celelalte {miss} au întârzierea necunoscută (nu 0) și nu intră în "
                      "statistici." if miss else "."))
    return out


def _options(js, field) -> list[dict]:
    c = Counter(j[field] for j in js if j[field])
    return [{"name": k, "n": n} for k, n in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))]


def build(rows: list[dict], weather: list[dict], extra: dict, p: stats.Params, today: date,
          filters: dict) -> dict:
    options = {"operators": _options(rows, "operator"), "types": _options(rows, "train_type")}
    op, tip = filters.get("operator"), filters.get("tip")
    js = [j for j in rows if (not op or j["operator"] == op) and (not tip or j["train_type"] == tip)]
    boards = [p.board] if p.board else list(stats.BOARDS)
    bj = {b: [j for j in js if j["board"] == b] for b in boards}
    vals = {b: stats.delays(bj[b], p) for b in boards}

    by_board = {b: {"journeys": len(bj[b]), **_summ(vals[b], p)} for b in boards}
    distribution = {b: _distribution(vals[b], p) for b in boards}
    hourly, heatmap, daily, operators, types, routes, platforms = {}, {}, {}, {}, {}, {}, {}
    for b in boards:
        hg = _groups(bj[b], p, lambda j: int(j["sched_time"][:2]))
        hourly[b] = [{"key": h, "journeys": hg[h]["journeys"] if h in hg else 0,
                      **_summ(hg[h]["delays"] if h in hg else [], p)} for h in range(24)]
        cg = _groups(bj[b], p, lambda j: (date.fromisoformat(j["service_date"]).weekday(),
                                          int(j["sched_time"][:2])))
        heatmap[b] = [{"d": d, "h": h, "journeys": v["journeys"], **_summ(v["delays"], p)}
                      for (d, h), v in sorted(cg.items()) if v["journeys"]]
        heatmap[b] = [{k: c[k] for k in ("d", "h", "journeys", "n", "mean", "median",
                                         "on_time_pct", "sufficient")} for c in heatmap[b]]
        dg = _groups(bj[b], p, lambda j: j["service_date"])
        daily[b] = [{"key": k, "journeys": v["journeys"], **_summ(v["delays"], p)}
                    for k, v in sorted(dg.items())]
        operators[b] = _ranked(bj[b], p, lambda j: j["operator"])
        types[b] = _ranked(bj[b], p, lambda j: j["train_type"])
        r = stations.rank_stations(bj[b], p, ROUTES_LIMIT)
        # most delayed by the MEDIAN (then the mean): one extreme case must not lead the list
        delayed = sorted(r["_ranked"], key=lambda e: (-e["stats"]["median"], -e["stats"]["mean"],
                                                      e["station"]))[:ROUTES_LIMIT]
        routes[b] = {"eligible": r["eligible"], "below_min": r["below_min"],
                     "most_delayed": [_route(e) for e in delayed],
                     "most_punctual": [_route(e) for e in r["most_punctual"]]}
        pc = Counter(j["last_platform"] for j in bj[b])
        missing = pc.pop(None, 0)
        platforms[b] = {"lines": [{"line": k, "n": n} for k, n in sorted(pc.items())],
                        "missing": missing}
    traffic = {"days": len({j["service_date"] for j in js})}
    for b in boards:
        t = [0] * 24
        for j in bj[b]:
            t[int(j["sched_time"][:2])] += 1
        traffic[b] = t

    q = stats.quality(js)
    obs = extra.get("observations") or {}
    quality = {**q, "observations": obs, "observations_total": sum(obs.values()),
               "excluded": extra.get("excluded") or {},
               # observations / exclusions are counted per board and period only
               "counters_scope": "all" if (op or tip) else "filtered"}
    problems = sp.build(js, boards, p, extra, today)
    dates = [j["service_date"] for j in js]
    hist = extra.get("history") or {}
    history = {"first": hist.get("first"), "last": hist.get("last"), "days": hist.get("days", 0),
               "needed_days": HISTORY_MIN_DAYS,
               "sufficient": (hist.get("days") or 0) >= HISTORY_MIN_DAYS}
    coverage = {"first": min(dates) if dates else None, "last": max(dates) if dates else None,
                "days": len(set(dates)), "journeys": len(js),
                "trains": len({j["train_no"] for j in js}), "finished": q["finished"],
                "delay_known": q["delay_known"], "delay_known_pct": q["delay_known_pct"],
                "observations": sum(obs.values()), "excluded": quality["excluded"]}
    return {
        "params": {**p.echo(), "perioada": filters.get("perioada") or "all",
                   "operator": op or None, "tip": tip or None, "today": today.isoformat()},
        "options": options,
        "coverage": coverage,
        "history": history,
        "boards": by_board,
        "insights": _insights(boards, by_board, hourly, problems, traffic, platforms, q, p),
        "problems": problems,
        "distribution": distribution,
        "hourly": hourly,
        "heatmap": heatmap,
        "daily": daily,
        "operators": operators,
        "types": types,
        "routes": routes,
        "traffic": traffic,
        "platforms": platforms,
        "weather": _weather(js, weather, p, boards),
        "quality": quality,
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "cache_ttl_s": _ttl(),
    }


# ---- cache ----------------------------------------------------------------------------
# Two levels: the database read (`fetch`, the expensive part) per board/period/thresholds,
# shared by every operator / train-type filter; the built payload per filter on top (LRU).
# A lock per key: a slow computation never blocks another filter.

_fetched: OrderedDict = OrderedDict()
_built: OrderedDict = OrderedDict()
_locks: dict = {}
_registry = threading.Lock()
BUILT_MAX = 64


def clear_cache() -> None:
    _fetched.clear()
    _built.clear()


def _fresh(cache, key, ttl):
    hit = cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        cache.move_to_end(key)
        return hit[1]
    return None


def _put(cache, key, value, cap):
    cache[key] = (time.monotonic(), value)
    cache.move_to_end(key)
    while len(cache) > cap:
        cache.popitem(last=False)


def _lock_for(key) -> threading.Lock:
    with _registry:
        lk = _locks.get(key)
        if lk is None:
            if len(_locks) > 256:
                _locks.clear()
            lk = _locks[key] = threading.Lock()
        return lk


def overview(store, p: stats.Params, filters: dict, today: date | None = None) -> dict:
    today = today or datetime.now(TZ).date()
    ttl = _ttl()
    fkey = (id(store), getattr(store, "path", None), tuple(sorted(p.echo().items())),
            today.isoformat())
    bkey = fkey + (tuple(sorted((k, v) for k, v in filters.items() if v)),)
    hit = _fresh(_built, bkey, ttl)
    if hit is not None:
        return hit
    with _lock_for(bkey):  # concurrent requests for one key wait for one computation
        hit = _fresh(_built, bkey, ttl)
        if hit is not None:
            return hit
        with _lock_for(fkey):
            data = _fresh(_fetched, fkey, ttl)
            if data is None:
                data = fetch(store, p)
                _put(_fetched, fkey, data, CACHE_MAX)
        d = build(*data, p, today, filters)
        _put(_built, bkey, d, BUILT_MAX)
        return d


# ---- CSV -------------------------------------------------------------------------------

_S = ["n", "mean", "median", "on_time_pct", "sufficient"]


def to_csv(d: dict, name: str) -> str:
    """One data set of the payload as CSV (KeyError for an unknown set)."""
    if name not in SETS:
        raise KeyError(name)
    rows: list[list] = []
    boards = list(d["boards"])
    if name == "distribution":
        head = ["board", "bucket_min", "n", "pct"]
        rows = [[b, x["label"], x["n"], x["pct"]] for b in boards for x in d[name][b]]
    elif name == "hourly":
        head = ["board", "hour", "journeys", "n", "mean", "median", "p90", "on_time_pct",
                "sufficient"]
        rows = [[b, x["key"], x["journeys"], x["n"], x["mean"], x["median"], x["p90"],
                 x["on_time_pct"], x["sufficient"]] for b in boards for x in d[name][b]]
    elif name == "heatmap":
        head = ["board", "weekday", "hour", "journeys"] + _S
        rows = [[b, stats.WEEKDAYS[x["d"]], x["h"], x["journeys"]] + [x[k] for k in _S]
                for b in boards for x in d[name][b]]
    elif name in ("daily", "operators", "types"):
        head = ["board", "date" if name == "daily" else "key", "journeys"] + _S
        rows = [[b, x["key"], x["journeys"]] + [x[k] for k in _S] for b in boards for x in d[name][b]]
    elif name == "routes":
        head = ["board", "list", "rank", "station", "journeys", "n", "mean", "median", "on_time_pct"]
        for b in boards:
            for lst in ("most_delayed", "most_punctual"):
                for i, x in enumerate(d[name][b][lst], 1):
                    rows.append([b, lst, i, x["key"], x["journeys"], x["n"], x["mean"],
                                 x["median"], x["on_time_pct"]])
    elif name == "traffic":
        head = ["board", "hour", "journeys", "days"]
        rows = [[b, h, d[name][b][h], d[name]["days"]] for b in boards for h in range(24)]
    elif name == "platforms":
        head = ["board", "line", "journeys"]
        for b in boards:
            rows += [[b, x["line"], x["n"]] for x in d[name][b]["lines"]]
            rows.append([b, "necitita", d[name][b]["missing"]])
    else:  # weather
        head = ["board", "dimension", "key", "label"] + _S
        rows = [[b, dim, x["key"], x["label"]] + [x[k] for k in _S]
                for b, wb in d[name]["boards"].items()
                for dim, gs in wb["groups"].items() for x in gs]
    return stats.to_csv(head, rows)
