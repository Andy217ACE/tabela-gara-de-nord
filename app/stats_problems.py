# © 2026 Andy217Ace
"""Statistici — „Probleme”: deterministic findings for the top of #statistici (no AI).

Input: the public journeys of /api/stats/overview (already filtered, with `result`), the
delay events of those journeys (to see how a delay evolved), the reading gaps and the
history counters. Output: one JSON section, `problems`, with

- `items`: findings ranked by severity × impact × confidence (each with N, raw figures,
  why it matters and links to the train / station / day);
- detail tables: recurrent trains, routes, 3-hour windows, one-day episodes, arrivals vs
  departures, big delays, delay growth after the first announcement, the trend per day;
- `good`: a short „what works” list; `coverage`: how much the data can say.

Rules (product principles): the delay is the one READ on the București Nord board; only
finished journeys with a read delay count (missing is never 0); arrivals and departures are
never mixed; every figure carries N; below the minimum sample no percentages (raw counts
only, „date insuficiente”); groups are ranked by the MEDIAN and the count above 15 min,
never by the mean (one 390-min case moved a whole hour / route in Beta 1.17); a group needs
at least two different trains (N counts journeys, i.e. the same train on several days); a
train is „recurrent” only when seen on >= 3 days; a trend needs >= 7 days of history;
correlation is not causation (operators and train types follow their routes).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date
from urllib.parse import quote

from app import journeys, stats

LATE = 15                 # „întârziere semnificativă”: impact counts use > 15 min
BIG = 30
HUGE = 60
REC_MIN_DAYS = 3          # fewer days: a train cannot be called recurrent
GROUP_MIN_TRAINS = 2      # a route / type with one train is that train, not a pattern
TYPE_MIN_TRAINS = 3
WINDOW_H = 3              # hour windows: 00–03, 03–06, ...
TOP_TRAINS = 8
TOP_ROUTES = 5
MAX_ITEMS = 10
MAX_EPISODES = 3
GAP_MIN = 10              # a pause between two successful board readings longer than this
TREND_MIN_DAYS = 7
SEV_W = {"mare": 3, "medie": 2, "mică": 1}
CONF_W = {"ridicată": 1.0, "medie": 0.7, "scăzută": 0.4}
BOARD_PL = {"arrival": "Sosiri", "departure": "Plecări"}
BOARD_LOW = {"arrival": "sosiri", "departure": "plecări"}
TYPE_NAME = {"R": "Regio", "RM": "Regio Metropolitan", "RE": "Regio Expres", "IR": "InterRegio",
             "IRN": "InterRegio de noapte", "IC": "InterCity"}
MONTHS = ("ian.", "feb.", "mar.", "apr.", "mai", "iun.", "iul.", "aug.", "sept.", "oct.",
          "nov.", "dec.")


# ---- helpers -------------------------------------------------------------------------------

def _fmt(x) -> str:
    if x is None:
        return "—"
    x = round(float(x), 1)
    return str(int(x)) if x == int(x) else f"{x:.1f}".replace(".", ",")


def _pct(k: int, n: int, p) -> float | None:
    """Percentage only at or above the minimum sample (never a misleading %)."""
    return round(100.0 * k / n, 1) if n and n >= p.min_sample else None


def _median(vals) -> float | None:
    return stats._r(stats.percentile(sorted(vals), 0.5)) if vals else None


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1]}"


def _name(s: str | None) -> str:
    return (s or "").title()


def _hrange(h: int) -> str:
    return f"{h:02d}:00–{min(h + WINDOW_H, 24):02d}:00"


def _d(j) -> int:
    return j["result"]["observed_delay"]


def severity_of(median) -> str:
    if median is None:
        return "mică"
    return "mare" if median >= BIG else "medie" if median >= LATE else "mică"


def score(sev: str, conf: str, impact: int) -> float:
    """Severity × confidence × √impact (affected journeys): deterministic and monotone."""
    return round(SEV_W[sev] * CONF_W[conf] * math.sqrt(max(impact, 0)), 2)


def _summary(js, p) -> dict:
    v = [_d(j) for j in js]
    n = len(v)
    on = sum(1 for x in v if x <= p.on_time)
    return {"n": n, "on_time": on, "on_time_pct": _pct(on, n, p), "median": _median(v),
            "over_15": sum(1 for x in v if x > LATE), "over_30": sum(1 for x in v if x > BIG),
            "over_60": sum(1 for x in v if x > HUGE), "max": max(v) if v else None,
            "trains": len({j["train_no"] for j in js}),
            "days": len({j["service_date"] for j in js}), "sufficient": n >= p.min_sample}


def _train_link(j) -> dict:
    return {"label": f"{j['train_type']} {j['train_no']}", "href": f"#tren?nr={j['train_no']}"}


def _station_link(station: str, board: str) -> dict:
    return {"label": _name(station), "href": f"#statie?nume={quote(station)}&board={board}"}


def _day_link(iso: str, board: str) -> dict:
    return {"label": _day(iso), "href": f"#istoric?date={iso}&board={board}"}


def _item(kind, board, sev, conf, impact, title, figures, why, n, links=(), key=None) -> dict:
    return {"id": f"{kind}:{board or 'all'}:{key if key is not None else ''}", "kind": kind,
            "board": board, "severity": sev, "confidence": conf, "impact": impact,
            "score": score(sev, conf, impact), "title": title, "figures": figures, "why": why,
            "n": n, "links": list(links)}


def _conf_group(s: dict, p, min_trains: int = GROUP_MIN_TRAINS) -> str:
    if s["n"] >= 2 * p.min_sample and s["trains"] >= min_trains + 1 and s["days"] >= 3:
        return "ridicată"
    return "medie"


# ---- pieces ---------------------------------------------------------------------------------

def boards_compare(bj, p) -> dict:
    """Arrivals vs departures, plus the „mix” note: one dominant, very different station that
    moves the board figure (e.g. the airport shuttles at arrivals)."""
    out = {}
    for b, js in bj.items():
        s = _summary(js, p)
        s["mix"] = None
        if s["sufficient"]:
            by = defaultdict(list)
            for j in js:
                by[j["station"]].append(j)
            best = None
            for st, sj in sorted(by.items()):
                rest = [j for j in js if j["station"] != st]
                if len(sj) < max(0.15 * s["n"], p.min_sample) or len(rest) < p.min_sample:
                    continue
                a, r = _summary(sj, p), _summary(rest, p)
                gap = abs(a["on_time_pct"] - r["on_time_pct"])
                if gap >= 30 and (best is None or gap > best[0]):
                    best = (gap, {"station": st, "n": a["n"], "on_time": a["on_time"],
                                  "on_time_pct": a["on_time_pct"], "rest_n": r["n"],
                                  "rest_on_time": r["on_time"],
                                  "rest_on_time_pct": r["on_time_pct"]})
            s["mix"] = best[1] if best else None
        out[b] = s
    return out


def groups(js, p, keyfn, min_trains=GROUP_MIN_TRAINS) -> dict:
    by = defaultdict(list)
    for j in js:
        k = keyfn(j)
        if k:
            by[k].append(j)
    rows = []
    for k, g in by.items():
        s = _summary(g, p)
        s["key"] = k
        s["eligible"] = s["sufficient"] and s["trains"] >= min_trains
        rows.append(s)
    elig = [r for r in rows if r["eligible"]]
    worst = sorted(elig, key=lambda r: (-(r["median"] or 0), -r["over_15"] / r["n"], -r["n"], r["key"]))
    best = sorted([r for r in elig if r["on_time_pct"] >= 90],
                  key=lambda r: (-r["on_time_pct"], r["median"] or 0, -r["n"], r["key"]))
    return {"worst": worst, "best": best, "eligible": len(elig),
            "below_min": sum(1 for r in rows if not r["sufficient"]),
            "single_train": sum(1 for r in rows if r["sufficient"] and r["trains"] < min_trains)}


def recurrent(js, p) -> dict:
    """Trains late on (almost) every day they were seen: >= REC_MIN_DAYS days, late on all
    of them (one day may be missed from 5 days on). Raw counts, never percentages."""
    by = defaultdict(list)
    for j in js:
        by[(j["board"], j["train_no"])].append(j)
    rows = []
    seen = 0
    for (b, no), g in by.items():
        per_day = defaultdict(list)
        for j in g:
            per_day[j["service_date"]].append(_d(j))
        days = len(per_day)
        if days < REC_MIN_DAYS:
            continue
        seen += 1
        worst = {d: max(v) for d, v in per_day.items()}
        late = sum(1 for v in worst.values() if v > p.on_time)
        if late < REC_MIN_DAYS or late < days - (1 if days >= 5 else 0):
            continue
        g = sorted(g, key=lambda j: (j["service_date"], j["sched_time"]))
        vals = [_d(j) for j in g]
        rows.append({
            "board": b, "train_no": no, "train_type": g[-1]["train_type"],
            "station": g[-1]["station"], "operator": g[-1]["operator"],
            "sched_time": Counter(j["sched_time"] for j in g).most_common(1)[0][0],
            "days": days, "late_days": late,
            "over_15_days": sum(1 for v in worst.values() if v > LATE),
            "delays": [{"date": j["service_date"], "delay": _d(j)} for j in g],
            "median": _median(vals), "max": max(vals),
            "confidence": "ridicată" if days >= p.min_sample else "medie"})
    rows.sort(key=lambda r: (-r["over_15_days"], -(r["median"] or 0), -r["days"], r["board"],
                             r["train_no"]))
    return {"trains": rows[:TOP_TRAINS], "count": len(rows), "seen": seen,
            "over_15_every_day": sum(1 for r in rows if r["over_15_days"] == r["days"]),
            "late_journeys": sum(r["late_days"] for r in rows),
            "journeys": sum(len(r["delays"]) for r in rows), "min_days": REC_MIN_DAYS}


def windows(js, p, board_share) -> list[dict]:
    """3-hour windows of the scheduled time: share above 15 min and on how many days."""
    by = defaultdict(list)
    for j in js:
        by[int(j["sched_time"][:2]) // WINDOW_H * WINDOW_H].append(j)
    out = []
    for h in range(0, 24, WINDOW_H):
        g = by.get(h, [])
        s = _summary(g, p)
        s["from_h"] = h
        s["label"] = _hrange(h)
        s["over_15_pct"] = _pct(s["over_15"], s["n"], p)
        late_days = {j["service_date"] for j in g if _d(j) > LATE}
        s["late_days"] = len(late_days)
        s["critical"] = bool(s["sufficient"] and s["over_15"] >= 3 and s["late_days"] >= 2
                             and s["over_15"] / s["n"] >= max(0.2, 1.3 * board_share))
        out.append(s)
    return out


def episodes(js, p, board_share30) -> list[dict]:
    """One day × one 3-hour window with many delays above 30 min: an incident, not a pattern."""
    by = defaultdict(list)
    for j in js:
        by[(j["service_date"], int(j["sched_time"][:2]) // WINDOW_H * WINDOW_H)].append(j)
    out = []
    for (d, h), g in by.items():
        n = len(g)
        o30 = sum(1 for j in g if _d(j) > BIG)
        if n >= p.min_sample and o30 >= 3 and o30 / n >= max(0.25, 2 * board_share30):
            out.append({"date": d, "from_h": h, "label": _hrange(h), "n": n, "over_30": o30,
                        "over_30_pct": _pct(o30, n, p), "median": _median([_d(j) for j in g]),
                        "unconfirmed": sum(1 for j in g if j["result"]["state"] == "unconfirmed"),
                        "stations": len({j["station"] for j in g if _d(j) > BIG})})
    out.sort(key=lambda e: (-e["over_30"], -e["over_30"] / e["n"], e["date"], e["from_h"]))
    return out[:MAX_EPISODES]


def big(js, p) -> dict:
    top = sorted((j for j in js if _d(j) > BIG), key=lambda j: (-_d(j), j["service_date"],
                                                                 j["sched_time"]))[:5]
    return {"n": len(js), "over_30": sum(1 for j in js if _d(j) > BIG),
            "over_60": sum(1 for j in js if _d(j) > HUGE),
            "top": [{"train_no": j["train_no"], "train_type": j["train_type"],
                     "station": j["station"], "date": j["service_date"],
                     "sched_time": j["sched_time"], "delay": _d(j),
                     "state": j["result"]["state"]} for j in top]}


def growth(js, p, events: dict) -> dict:
    """Did the delay grow after it was first announced (> 0)? Readings only: suspect events
    are already out; values a revert shows to be a misread "+" are dropped."""
    grew, same, rec = [], 0, []
    for j in js:
        evs = events.get(j["id"]) or []
        bad = journeys.misread_values(evs)
        vals = [journeys._int(e["new"]) for e in evs]
        vals = [v for v in vals if v is not None and v not in bad]
        first = next((v for v in vals if v > 0), None)
        if first is None:
            continue
        fin = _d(j)
        if fin > first:
            grew.append(fin - first)
        elif fin < first:
            rec.append(first - fin)
        else:
            same += 1
    n = len(grew) + same + len(rec)
    return {"n": n, "grew": len(grew), "same": same, "recovered": len(rec),
            "grew_pct": _pct(len(grew), n, p), "grew_median": _median(grew),
            "recovered_median": _median(rec), "sufficient": n >= p.min_sample}


def trend(bj, p, history_days: int, partial: set) -> dict:
    per = {}
    for b, js in bj.items():
        by = defaultdict(list)
        for j in js:
            by[j["service_date"]].append(j)
        per[b] = [dict(_summary(g, p), date=d, partial=d in partial) for d, g in sorted(by.items())]
    status = "ok" if history_days >= TREND_MIN_DAYS else "insufficient"
    direction = {}
    for b, rows in per.items():
        full = [r for r in rows if not r["partial"] and r["sufficient"]]
        direction[b] = None
        if status == "ok" and len(full) >= 6:
            k = len(full) // 2
            a = sum(r["on_time"] for r in full[:k]) / sum(r["n"] for r in full[:k])
            z = sum(r["on_time"] for r in full[k:]) / sum(r["n"] for r in full[k:])
            diff = round(100 * (z - a), 1)
            direction[b] = {"diff_pp": diff, "label": "mai bine" if diff >= 10 else
                            "mai rău" if diff <= -10 else "stabil"}
    return {"status": status, "needed_days": TREND_MIN_DAYS, "days": history_days,
            "boards": per, "direction": direction}


def coverage(js, extra: dict, today: date) -> dict:
    hist = extra.get("history") or {}
    days = hist.get("days") or 0
    dates = sorted({j["service_date"] for j in js})
    low = extra.get("low_quality_dates") or {}
    gaps = extra.get("gaps") or []
    partial = {}
    for d in dates:
        why = []
        if d == today.isoformat():
            why.append("ziua în curs")
        if low.get(d):
            why.append(f"{low[d]} călătorii excluse, calitate redusă")
        gm = sum(g["minutes"] for g in gaps if g["start"][:10] == d)
        if gm >= 60:
            why.append(f"{gm} min fără citire")
        if why:
            partial[d] = ", ".join(why)
    st = Counter(j["result"]["state"] for j in js)
    finished = len(js) - st["in_progress"]
    level = "insuficientă" if days < 3 else "parțială" if days < TREND_MIN_DAYS else "bună"
    return {"level": level, "days": days, "needed_days": TREND_MIN_DAYS, "first": hist.get("first"),
            "last": hist.get("last"), "partial": [{"date": d, "why": w} for d, w in partial.items()],
            "gaps": gaps[:20], "gaps_count": len(gaps),
            "gap_minutes": sum(g["minutes"] for g in gaps), "gap_threshold_min": GAP_MIN,
            "finished": finished, "unconfirmed": st["unconfirmed"], "unknown": st["unknown"],
            "in_progress": st["in_progress"]}


# ---- items ----------------------------------------------------------------------------------

def _items(boards, cmp_, routes, types, rec, wins, eps, bigs, grow, p, bj) -> list[dict]:
    items = []
    # 1. arrivals vs departures
    if len(boards) == 2 and all(cmp_[b]["sufficient"] for b in boards):
        a, d = cmp_["arrival"], cmp_["departure"]
        worse, better = ("arrival", "departure") if a["on_time_pct"] <= d["on_time_pct"] \
            else ("departure", "arrival")
        w, bt = cmp_[worse], cmp_[better]
        if bt["on_time_pct"] - w["on_time_pct"] >= 20:
            fig = " · ".join(f"{BOARD_PL[b]}: {cmp_[b]['on_time']} din {cmp_[b]['n']} la timp "
                             f"({_fmt(cmp_[b]['on_time_pct'])} %), mediana "
                             f"{_fmt(cmp_[b]['median'])} min" for b in boards)
            mix = w["mix"]
            if mix:
                fig += (f" · fără {_name(mix['station'])} ({mix['n']} {BOARD_LOW[worse]}, "
                        f"{_fmt(mix['on_time_pct'])} % la timp): {mix['rest_on_time']} din "
                        f"{mix['rest_n']} ({_fmt(mix['rest_on_time_pct'])} %)")
            why = ("Întârzierea vine cu trenul din rețea, nu apare la plecarea din București Nord. "
                   "La plecări tabela arată întârzierea anunțată, nu ora reală de plecare."
                   if worse == "arrival" else
                   "Trenurile pleacă din București Nord cu întârziere mai des decât sosesc — "
                   "semn de probleme la formare sau la linie, de verificat pe trenuri.")
            sev = "mare" if w["on_time_pct"] < 50 else "medie" if w["on_time_pct"] < 75 else "mică"
            conf = "ridicată" if min(a["days"], d["days"]) >= 3 else "medie"
            items.append(_item("boards", worse, sev, conf, w["n"] - w["on_time"],
                               f"{BOARD_PL[worse]}: întârzieri mult mai dese decât la "
                               f"{BOARD_LOW[better]}", fig, why, w["n"],
                               [{"label": f"Istoric {BOARD_LOW[worse]}",
                                 "href": f"#istoric?board={worse}"}]))
    # 2. routes (worst by median, >= 2 trains)
    for b in boards:
        for r in routes[b]["worst"][:2]:
            if not (r["median"] is not None and (r["median"] >= LATE or r["on_time_pct"] <= 50)):
                continue
            way = "din" if b == "arrival" else "spre"
            fig = (f"{r['on_time']} din {r['n']} la timp ({_fmt(r['on_time_pct'])} %) · mediana "
                   f"{_fmt(r['median'])} min · {r['over_15']} peste 15 min, {r['over_30']} peste "
                   f"30 · {r['trains']} trenuri în {r['days']} zile")
            why = ("Cea mai întârziată direcție după mediană (nu după medie, pe care un singur caz "
                   "extrem o poate deforma). Întârzierea e cea afișată la București Nord, "
                   "acumulată pe drum." if b == "arrival" else
                   "Plecări întârziate repetat pe aceeași direcție: de verificat dacă trenul "
                   "vine întârziat din cursa anterioară.")
            items.append(_item("route", b, severity_of(r["median"]), _conf_group(r, p),
                               r["over_15"], f"{BOARD_PL[b]} {way} {_name(r['key'])}: "
                               f"rar la timp", fig, why, r["n"],
                               [_station_link(r["key"], b)], key=r["key"]))
    # 3. train types far below the board
    for b in boards:
        base = cmp_[b]["on_time_pct"]
        if base is None:
            continue
        for r in types[b]["worst"]:
            if r["on_time_pct"] is None or r["on_time_pct"] > base - 25:
                continue
            name = TYPE_NAME.get(r["key"], r["key"])
            fig = (f"{r['on_time']} din {r['n']} la timp ({_fmt(r['on_time_pct'])} %, față de "
                   f"{_fmt(base)} % la toate {BOARD_LOW[b]}le) · mediana {_fmt(r['median'])} min · "
                   f"{r['over_30']} peste 30 min · {r['trains']} trenuri")
            items.append(_item("type", b, severity_of(r["median"]), _conf_group(r, p, TYPE_MIN_TRAINS),
                               r["over_15"], f"{r['key']} ({name}) la {BOARD_LOW[b]}: "
                               f"mult sub medie", fig,
                               "Tipul de tren coincide cu anumite rute (de exemplu cele lungi sau "
                               "de noapte): arată unde apar întârzierile, nu de ce (corelație, nu "
                               "cauzalitate).", r["n"],
                               [{"label": f"Doar {r['key']}",
                                 "href": f"#statistici?board={b}&tip={r['key']}"}], key=r["key"]))
    # 4. recurrent trains
    if rec["count"]:
        top = rec["trains"][:3]
        fig = "; ".join(f"{t['train_type']} {t['train_no']} {_name(t['station'])} "
                        f"{t['sched_time']} ({BOARD_LOW[t['board']]}) — {t['late_days']} din "
                        f"{t['days']} zile întârziat: " + ", ".join(str(x["delay"]) for x in t["delays"])
                        + " min" for t in top)
        sev = "mare" if rec["over_15_every_day"] >= 5 else "medie"
        conf = "ridicată" if all(t["days"] >= p.min_sample for t in rec["trains"]) else "medie"
        items.append(_item("recurrent", None, sev, conf, rec["late_journeys"],
                           f"{rec['count']} {'tren întârziat' if rec['count'] == 1 else 'trenuri întârziate'}"
                           f" în fiecare zi în care au fost văzute",
                           f"Din {rec['seen']} trenuri văzute în cel puțin {REC_MIN_DAYS} zile · "
                           f"{rec['over_15_every_day']} peste 15 min în fiecare zi · {fig}",
                           "Același tren întârziat zi de zi e o problemă de orar sau de rută, nu un "
                           "incident: întârzierea lui e previzibilă pentru călători."
                           + ("" if conf == "ridicată" else
                              f" Puține zile pe tren (sub {p.min_sample}): doar cifre brute."),
                           rec["journeys"],
                           [{"label": f"{t['train_type']} {t['train_no']}",
                             "href": f"#tren?nr={t['train_no']}"} for t in top]))
    # 5. critical windows
    for b in boards:
        crit = sorted([w for w in wins[b] if w["critical"]],
                      key=lambda w: (-w["over_15"] / w["n"], -w["n"]))[:2]
        base = cmp_[b]
        for w in crit:
            js = [j for j in bj[b] if int(j["sched_time"][:2]) // WINDOW_H * WINDOW_H == w["from_h"]]
            worst = sorted(js, key=lambda j: -_d(j))[:2]
            pct15 = w["over_15_pct"]
            sev = "mare" if pct15 >= 40 else "medie" if pct15 >= 25 else "mică"
            items.append(_item("window", b, sev, "ridicată" if w["late_days"] >= 3 else "medie",
                               w["over_15"], f"{BOARD_PL[b]} programate {w['label']}: cele mai "
                               f"multe întârzieri", f"{w['over_15']} din {w['n']} peste 15 min "
                               f"({_fmt(pct15)} %, față de {_fmt(_pct(base['over_15'], base['n'], p))} % "
                               f"la toate {BOARD_LOW[b]}le) · mediana {_fmt(w['median'])} min · în "
                               f"{w['late_days']} din {w['days']} zile",
                               "Fereastra în care legăturile sunt cel mai des ratate; se repetă în "
                               "mai multe zile, deci nu e un singur incident.", w["n"],
                               [_train_link(j) for j in worst], key=w["from_h"]))
    # 6. episodes
    for e in eps:
        b = e["board"]
        conf = "medie" if e["unconfirmed"] * 2 <= e["over_30"] else "scăzută"
        items.append(_item("episode", b, "mare" if e["over_30"] >= 5 else "medie", conf,
                           e["over_30"], f"{_day(e['date'])}, {e['label']}: episod de întârzieri "
                           f"mari la {BOARD_LOW[b]}", f"{e['over_30']} din {e['n']} peste 30 min "
                           f"({_fmt(e['over_30_pct'])} %, de obicei {_fmt(e['base_pct'])} %) · "
                           f"{e['stations']} direcții diferite · {e['unconfirmed']} cu rezultat "
                           f"neconfirmat",
                           "Un incident de o zi, nu un tipar: direcții diferite întârziate în "
                           "același timp indică o perturbare comună." +
                           (" Multe rezultate sunt neconfirmate (au dispărut de pe tabelă înainte "
                            "de ora estimată), deci cifrele sunt orientative." if conf == "scăzută"
                            else ""), e["n"], [_day_link(e["date"], b)],
                           key=f"{e['date']}-{e['from_h']}"))
    # 7. big delays
    for b in boards:
        g = bigs[b]
        if g["over_60"] or g["over_30"] >= 3:
            top = g["top"][:3]
            fig = (f"{g['over_30']} peste 30 min, {g['over_60']} peste 60 min (N = {g['n']}) · cele "
                   "mai mari: " + "; ".join(f"{t['train_type']} {t['train_no']} {_name(t['station'])}"
                                            f", {_day(t['date'])} {t['sched_time']} — {t['delay']} min"
                                            for t in top))
            items.append(_item("big", b, "mare" if g["over_60"] else "medie",
                               "ridicată" if g["n"] >= p.min_sample else "medie", g["over_30"],
                               f"{BOARD_PL[b]}: întârzieri foarte mari (maxim {top[0]['delay']} min)",
                               fig, "Puține, dar cu impact mare pentru cei afectați. Un singur caz "
                               "extrem poate muta media unei ore sau a unei rute — de aceea "
                               "clasamentele de aici folosesc mediana.", g["n"],
                               [{"label": f"{t['train_type']} {t['train_no']}",
                                 "href": f"#tren?nr={t['train_no']}"} for t in top]))
    # 8. delay grows after the first announcement
    for b in boards:
        g = grow[b]
        if g["sufficient"] and g["grew"] >= 3 and g["grew"] / g["n"] >= 0.3:
            items.append(_item("growth", b, "mică", "ridicată" if g["n"] >= 2 * p.min_sample
                               else "medie", g["grew"], f"{BOARD_PL[b]}: prima întârziere "
                               f"anunțată crește adesea", f"Din {g['n']} {BOARD_LOW[b]} cu "
                               f"întârziere anunțată (> 0): {g['grew']} au crescut după primul "
                               f"anunț ({_fmt(g['grew_pct'])} %, mediana +{_fmt(g['grew_median'])} "
                               f"min), {g['same']} au rămas la fel, {g['recovered']} au scăzut",
                               "Prima cifră de pe tabelă tinde să subestimeze întârzierea finală: "
                               "pentru o legătură strânsă, socotește o marjă.", g["n"]))
    items.sort(key=lambda i: (-i["score"], i["id"]))
    for k, it in enumerate(items[:MAX_ITEMS], 1):
        it["rank"] = k
    return items[:MAX_ITEMS]


def _good(boards, cmp_, routes, types) -> list[str]:
    out = []
    for b in boards:
        s = cmp_[b]
        if s["sufficient"] and s["on_time_pct"] >= 90:
            out.append(f"{BOARD_PL[b]}: {s['on_time']} din {s['n']} la timp "
                       f"({_fmt(s['on_time_pct'])} %), mediana {_fmt(s['median'])} min.")
    for b in boards:
        for r in routes[b]["best"][:2]:
            way = "din" if b == "arrival" else "spre"
            out.append(f"{BOARD_PL[b]} {way} {_name(r['key'])}: {r['on_time']} din {r['n']} la timp "
                       f"({_fmt(r['on_time_pct'])} %, {r['trains']} trenuri).")
    for b in boards:
        for r in types[b]["best"][:1]:
            out.append(f"{r['key']} ({TYPE_NAME.get(r['key'], r['key'])}) la {BOARD_LOW[b]}: "
                       f"{r['on_time']} din {r['n']} la timp ({_fmt(r['on_time_pct'])} %).")
    return out[:6]


def build(js: list[dict], boards: list[str], p, extra: dict, today: date) -> dict:
    """The `problems` section. `js` = the filtered public journeys of the overview."""
    counted = [j for j in js if stats.counted(j, p)]
    bj = {b: [j for j in counted if j["board"] == b] for b in boards}
    cmp_ = boards_compare(bj, p)
    routes = {b: groups(bj[b], p, lambda j: j["station"]) for b in boards}
    types = {b: groups(bj[b], p, lambda j: j["train_type"], TYPE_MIN_TRAINS) for b in boards}
    rec = recurrent(counted, p)
    wins, eps = {}, []
    for b in boards:
        s = cmp_[b]
        share15 = s["over_15"] / s["n"] if s["n"] else 0
        share30 = s["over_30"] / s["n"] if s["n"] else 0
        wins[b] = windows(bj[b], p, share15)
        for e in episodes(bj[b], p, share30):
            e["board"] = b
            e["base_pct"] = _pct(s["over_30"], s["n"], p)
            eps.append(e)
    eps.sort(key=lambda e: (-e["over_30"], e["date"], e["from_h"]))
    eps = eps[:MAX_EPISODES]
    bigs = {b: big(bj[b], p) for b in boards}
    events = extra.get("delay_events") or {}
    grow = {b: growth(bj[b], p, events) for b in boards}
    cov = coverage(js, extra, today)
    hist_days = (extra.get("history") or {}).get("days") or 0
    tr = trend(bj, p, hist_days, {x["date"] for x in cov["partial"]})
    enough = any(cmp_[b]["sufficient"] for b in boards)
    items = _items(boards, cmp_, routes, types, rec, wins, eps, bigs, grow, p, bj) if enough else []

    def trim(g):
        return {"worst": g["worst"][:TOP_ROUTES], "best": g["best"][:3], "eligible": g["eligible"],
                "below_min": g["below_min"], "single_train": g["single_train"]}

    return {
        "status": "ok" if enough else "insufficient",
        "message": None if enough else (
            f"Date insuficiente: sub {p.min_sample} călătorii încheiate cu întârziere citită pe "
            "fiecare panou — nu se pot trage concluzii (fără procente)."),
        "rules": {"late_min": LATE, "big_min": BIG, "huge_min": HUGE, "rec_min_days": REC_MIN_DAYS,
                  "group_min_trains": GROUP_MIN_TRAINS, "window_h": WINDOW_H,
                  "min_sample": p.min_sample, "on_time_max_min": p.on_time},
        "items": items,
        "good": _good(boards, cmp_, routes, types) if enough else [],
        "boards": cmp_,
        "recurrent": rec,
        "routes": {b: trim(routes[b]) for b in boards},
        "types": {b: trim(types[b]) for b in boards},
        "windows": wins,
        "episodes": eps,
        "big": bigs,
        "growth": grow,
        "trend": tr,
        "coverage": cov,
    }
