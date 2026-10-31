# © 2026 Andy217Ace
"""Val 5a: comparația meteo pe sezoane (Statistici), cu prag de date.

- Sezoane meteorologice: dec–feb, mar–mai, iun–aug, sep–nov (ora României). Iarna din
  decembrie și din ianuarie–februarie e același sezon („iarnă 2026/27”).
- O zi e eligibilă dacă are cel puțin jumătate din observațiile meteo așteptate (96 pe zi,
  pas de 15 min) și nu cade în ±7 zile în jurul unei schimbări de orar CFR.
- Un sezon cu mai puțin de SEASON_MIN_DAYS zile eligibile nu are cifre: „date insuficiente
  (N=…)”. Grupele se compară între sezoane doar cu cel puțin SEASON_GROUP_MIN călătorii.
- Valorile meteo lipsă rămân lipsă (nu devin 0). Corelație, nu cauzalitate.
- Citește prin `stats_overview.fetch` (conexiune read-only); nu scrie nimic în baza de date.
"""
from __future__ import annotations

import bisect
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from app import journeys, stats, stats_overview as so

WEATHER_DAY_OBS = 96           # observații meteo așteptate pe zi (15 min)
WEATHER_DAY_MIN_SHARE = 0.5    # zi eligibilă: cel puțin jumătate din observații
SEASON_MIN_DAYS = 30           # zile eligibile per sezon, sub prag: fără cifre
SEASON_GROUP_MIN = 30          # călătorii per grupă, pentru a compara sezoanele
MATCH_MIN = so.WEATHER_MATCH_MIN
TIMETABLE_MARGIN_DAYS = 7
# Datele schimbărilor de orar CFR (decembrie 2026, de confirmat de utilizator). Până se
# confirmă data exactă, lista e goală: nicio zi nu e exclusă. Adăugați data, de ex.
# date(2026, 12, D), înainte de a publica prima comparație.
TIMETABLE_CHANGE_DATES: tuple[date, ...] = ()

SEASON_NAMES = {"iarna": "iarnă", "primavara": "primăvară", "vara": "vară", "toamna": "toamnă"}
_SEASON_OF_MONTH = {12: ("iarna", 12), 1: ("iarna", 12), 2: ("iarna", 12),
                    3: ("primavara", 3), 4: ("primavara", 3), 5: ("primavara", 3),
                    6: ("vara", 6), 7: ("vara", 6), 8: ("vara", 6),
                    9: ("toamna", 9), 10: ("toamna", 9), 11: ("toamna", 9)}
NOTE = ("Corelație, nu cauzalitate: vremea coincide cu alți factori (ora din zi, sezonul, "
        "lucrările, orarul); o diferență între sezoane nu arată că vremea a produs "
        "întârzierea. Vremea este modelul Open-Meteo, aceeași pentru toate stațiile.")


# ---- sezoane și zile -------------------------------------------------------------------

def season_of(d: date) -> tuple[str, str, date]:
    """(cheie, etichetă, prima zi) a sezonului în care cade ziua locală `d`."""
    name, sm = _SEASON_OF_MONTH[d.month]
    sy = d.year - 1 if name == "iarna" and d.month < 12 else d.year
    if name == "iarna":
        return f"iarna-{sy}", f"iarnă {sy}/{(sy + 1) % 100:02d}", date(sy, sm, 1)
    return f"{name}-{sy}", f"{SEASON_NAMES[name]} {sy}", date(sy, sm, 1)


def _utc(stamp: str) -> datetime | None:
    try:
        t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


def weather_days(wx: list[dict]) -> dict[date, int]:
    """Observațiile meteo numărate pe zi locală (ora României)."""
    c: Counter = Counter()
    for r in wx:
        t = _utc(r.get("observed_at") or "")
        if t is not None:
            c[t.astimezone(so.TZ).date()] += 1
    return dict(c)


def _in_timetable_margin(d: date, changes) -> bool:
    return any(abs((d - c).days) <= TIMETABLE_MARGIN_DAYS for c in changes)


def eligible_days(wx: list[dict], changes) -> dict[date, int]:
    """Zile cu cel puțin jumătate din observațiile așteptate, fără cele ±7 zile de la
    schimbările de orar. Valoarea e numărul de observații din zi."""
    need = int(WEATHER_DAY_OBS * WEATHER_DAY_MIN_SHARE)
    return {d: n for d, n in weather_days(wx).items()
            if n >= need and not _in_timetable_margin(d, changes)}


def _nearest(stamps: list[float], ts: float):
    i = bisect.bisect_left(stamps, ts)
    cands = [k for k in (i - 1, i) if 0 <= k < len(stamps)]
    return min(cands, key=lambda k: abs(stamps[k] - ts), default=None)


def match(js: list[dict], wx: list[dict], p: stats.Params) -> list[tuple[dict, dict]]:
    """Călătoriile numărate cu cea mai apropiată observație meteo, cel mult ±30 min.
    Ora programată se alege lângă momentul citirii (noaptea schimbării orei: două apariții
    ale aceleiași ore locale)."""
    pts = []
    for r in wx:
        t = _utc(r.get("observed_at") or "")
        if t is not None:
            pts.append((t.timestamp(), r))
    pts.sort(key=lambda x: x[0])
    stamps = [x[0] for x in pts]
    out = []
    for j in js:
        if not stats.counted(j, p):
            continue
        ref = _utc(j["result"].get("delay_read_at") or "")
        when = journeys.sched_at(j["service_date"], j["sched_time"],
                                 ref.astimezone(so.TZ) if ref else None)
        ts = when.timestamp()
        k = _nearest(stamps, ts)
        if k is not None and abs(stamps[k] - ts) <= MATCH_MIN * 60:
            out.append((j, pts[k][1]))
    return out


# ---- agregare (pură) -------------------------------------------------------------------

def _group(pairs, p, key_fn, label_fn) -> list[dict]:
    buckets: dict = defaultdict(list)
    for j, w in pairs:
        for k in key_fn(w):
            buckets[k].append(j["result"]["observed_delay"])
    out = []
    for k, vals in buckets.items():
        s = stats.summarize(vals, p.on_time, p.min_sample)
        out.append({"key": k, "label": label_fn(k), **s,
                    "comparable": s["n"] >= SEASON_GROUP_MIN})
    return out


def _precip_key(w):
    v = w.get("precipitation_mm")
    return [] if v is None else ["wet" if v > 0 else "dry"]


_PRECIP_LABEL = {"dry": "Fără precipitații", "wet": "Cu precipitații (> 0 mm)"}


def _temp_key(w):
    t = w.get("temperature_c")
    if t is None:
        return []
    for key, _label, lo, hi in so.TEMP_BANDS:
        if (lo is None or t >= lo) and (hi is None or t < hi):
            return [key]
    return []


_TEMP_LABEL = {k: lab for k, lab, _lo, _hi in so.TEMP_BANDS}


def _season_entry(key, label, start, n_days, pairs, p) -> dict:
    entry = {"key": key, "label": label, "start": start.isoformat(), "days": n_days,
             "enough": n_days >= SEASON_MIN_DAYS, "matched": len(pairs)}
    if entry["enough"]:
        entry["groups"] = {
            "precip": _group(pairs, p, _precip_key, _PRECIP_LABEL.get),
            "temp": _group(pairs, p, _temp_key, _TEMP_LABEL.get),
        }
    return entry


def _board(js, wx, p, board, days) -> dict:
    counted = [j for j in js if j["board"] == board and stats.counted(j, p)]
    on_days = [j for j in counted if date.fromisoformat(j["service_date"]) in days]
    pairs = match(on_days, wx, p)
    by_key: dict = {}
    for d in days:
        k, label, start = season_of(d)
        by_key.setdefault(k, {"label": label, "start": start, "days": 0})["days"] += 1
    for j in counted:
        k, label, start = season_of(date.fromisoformat(j["service_date"]))
        by_key.setdefault(k, {"label": label, "start": start, "days": 0})
    seasons = []
    for k, v in sorted(by_key.items(), key=lambda kv: kv[1]["start"]):
        mine = [(j, w) for j, w in pairs if season_of(date.fromisoformat(j["service_date"]))[0] == k]
        seasons.append({"key": k, **_season_entry(k, v["label"], v["start"], v["days"], mine, p)})
    return {"seasons": seasons,
            "compare": sum(1 for s in seasons if s["enough"]) >= 2}


def build(js: list[dict], wx: list[dict], p: stats.Params, boards, changes) -> dict:
    """Payload pur: pentru fiecare bord, sezoanele cu N zile eligibile și grupele (doar
    dacă sezonul are prag). Sosirile și plecările nu se amestecă."""
    days = set(eligible_days(wx, changes))
    need = int(WEATHER_DAY_OBS * WEATHER_DAY_MIN_SHARE)
    excluded = sum(1 for d, n in weather_days(wx).items()
                   if n >= need and _in_timetable_margin(d, changes))
    return {
        "min_days": SEASON_MIN_DAYS,
        "group_min": SEASON_GROUP_MIN,
        "day_obs_min": need,
        "timetable_changes": [c.isoformat() for c in changes],
        "timetable_margin_days": TIMETABLE_MARGIN_DAYS,
        "timetable_excluded_days": excluded,
        "note": NOTE,
        "boards": {b: _board(js, wx, p, b, days) for b in boards},
    }


# ---- acces la baza de date (read-only) -------------------------------------------------

def overview(store, p: stats.Params, boards=None, changes=None) -> dict:
    """Payload-ul sezoanelor pentru perioada și bordurile date. Citește cu `so.fetch`."""
    rows, wx, _extra = so.fetch(store, p)
    if changes is None:
        changes = TIMETABLE_CHANGE_DATES
    return build(rows, wx, p, boards or list(stats.BOARDS), tuple(changes))
