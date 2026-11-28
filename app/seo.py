# © 2026 Andy217Ace
"""Search engines: path URLs for the public pages, server-rendered head + light content.

Public pages live at /istoric, /tren/1636, /statie/BRASOV … (the SPA routes the same paths
with the History API; old /#hash links still work). Each one is index.html with, injected
here: its own <title>, description, canonical, hreflang (ro = no query, en = ?lang=en),
Open Graph/Twitter tags, JSON-LD and a short plain-HTML version of its content (hidden by
style.css once the app runs). Private pages (#admin, #ocr …) keep their hash URL and are
never indexed. Only board/catalog data from our own database; never Infofer.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from app import journeys, observations, stations, stats
from app import stats_overview as overview_v2
from app.store import TZ

SITE = os.environ.get("SITE_URL", "https://tabelagn.online").rstrip("/")
NAME = "Tabela Gara de Nord"
PUBLIC = ("istoric", "urmarite", "trenuri", "statistici", "clasamente", "statii", "versiuni", "cum")
PRIVATE = ("admin", "ocr", "ocr2", "infofer", "sistem", "setari")  # hash-only, noindex
NOINDEX = ("urmarite",)  # served at its path, but personal (this browser's follows): noindex, not in the sitemap
BOARD_ROWS = 20
SITEMAP_DAYS = 90
SITEMAP_TRAINS_MAX = 5000
TTL_PAGE = 60.0
TTL_DATA = 600.0
CACHE_MAX = 2000
I18N_DIR = Path(__file__).resolve().parent.parent / "web" / "i18n"
RECENT_TRIPS = 5          # train page: last journeys listed per board
STATION_TRAINS = 30       # station page: most recently seen trains per board
RANK_ROWS = 5             # clasamente: first rows of each list
AIRPORT = stats.AIRPORT_STATION
# = SECTIONS in web/cum.js (heading key, paragraph count): the server-rendered /cum has the same text
CUM_SECTIONS = (("data", 3), ("delay", 3), ("history", 3), ("method", 6), ("limits", 3), ("privacy", 4),
                ("report", 2))
REPO = "https://github.com/Andy217Ace/tabela-gara-de-nord"
GARA = {"@type": "TrainStation", "@id": SITE + "/#gara-de-nord", "name": "București Nord",
        "alternateName": "Gara de Nord",
        "address": {"@type": "PostalAddress", "addressLocality": "București", "addressCountry": "RO"},
        "geo": {"@type": "GeoCoordinates", "latitude": 44.4467, "longitude": 26.0747}}
PUBLISHER = {"@type": "Organization", "@id": SITE + "/#publisher",
             "name": "Tabela Gara de Nord (proiect independent, neafiliat CFR)", "url": SITE + "/",
             "founder": {"@type": "Person", "name": "Andy217Ace"}}

T = {
    "ro": {
        "tabela": ("Gara de Nord București – sosiri și plecări live",
                   "Vezi trenurile afișate acum în Gara de Nord București, cu ora programată, întârzierea "
                   "citită și linia anunțată. Verifică ora ultimei actualizări."),
        "istoric": ("Istoric sosiri și plecări · Gara de Nord",
                    "Tot ce a afișat tabela din Gara de Nord, pe zile: ore programate, întârzieri "
                    "și linii, filtrabile după tren, stație și interval orar."),
        "urmarite": ("Trenuri urmărite · Tabela Gara de Nord",
                     "Urmărește un tren și primești notificare când i se schimbă întârzierea sau linia."),
        "trenuri": ("Trenuri observate în Gara de Nord · statistici de întârziere",
                    "Catalogul trenurilor văzute pe tabela din Gara de Nord București, cu statistici "
                    "de întârziere pe sosiri și plecări."),
        "statistici": ("Statistici de punctualitate · Gara de Nord",
                       "Cât de punctuale sunt trenurile din Gara de Nord: întârzieri, linii și "
                       "tendințe, din datele citite pe tabelă."),
        "clasamente": ("Clasamente: cele mai întârziate și cele mai punctuale trenuri",
                       "Cele mai întârziate și cele mai punctuale trenuri și stații din Gara de "
                       "Nord, doar cu eșantion suficient."),
        "statii": ("Stații: de unde vin și unde pleacă trenurile din Gara de Nord",
                   "Stațiile de origine și destinație ale trenurilor din Gara de Nord București, "
                   "fiecare cu istoricul și întârzierile trenurilor."),
        "versiuni": ("Versiuni · Tabela Gara de Nord", "Istoricul versiunilor aplicației Tabela Gara de Nord."),
        "cum": ("Cum funcționează Tabela Gara de Nord",
                "Cum sunt citite datele de pe tabela CFR din Gara de Nord, ce înseamnă și ce limite au."),
        "tren": ("{train} la București Nord | Istoric întârzieri",
                 "{train}{route}: {n} pe tabela din Gara de Nord București ({first} – {last}). {boards}"),
        "tren_route": ("{train} {a} – {b} | Istoric întârzieri", " ({a} – {b})"),
        "tren_h1": "Trenul {train} la București Nord", "gn": "București Nord",
        "statie": ("{name}: trenuri spre și dinspre Gara de Nord",
                   "Trenurile dintre {name} și Gara de Nord București, observate pe tabelă între "
                   "{first} și {last} (treceri: {n}, trenuri: {trains}), cu întârzierile citite."),
        "statie_airport": ("Gara de Nord – Aeroport Otopeni: orele trenurilor și întârzieri",
                           "Trenurile dintre Gara de Nord București și Aeroportul Otopeni (Henri Coandă), "
                           "sosiri și plecări observate pe tabelă între {first} și {last} (treceri: {n}, "
                           "trenuri: {trains}), cu întârzierile citite."),
        "airport_name": "Aeroportul Otopeni (Henri Coandă)",
        "404": ("Pagina nu există · Tabela Gara de Nord", "Pagina căutată nu există."),
        "home": "Tabela", "updated": "Ultima actualizare (ora capturii tabelei)", "arrivals": "Sosiri",
        "departures": "Plecări",
        "time": "Ora", "train": "Tren", "from": "Din", "to": "Spre", "delay": "Întârziere citită",
        "platform": "Linia anunțată", "empty": "Nu sunt trenuri afișate acum.", "route_to": " spre {}",
        "route_from": " din {}", "operator": "Operator", "recent": "Trenuri văzute recent",
        "all_stations": "Toate stațiile",
        "insufficient": "date insuficiente", "unknown": "necunoscută", "live": "pe tabelă acum",
        "minutes": "{} min", "n_trips": ("călătorie", "călătorii"), "n_trains": ("tren", "trenuri"),
        "n_days": ("zi", "zile"),
        "category": "Categoria: {cat}. Numărul: {no}.",
        "last_seen": "Ultima apariție pe tabelă: {when}.",
        "on_board": "Trenul apare acum pe tabelă.",
        "absent": "Trenul nu apare acum pe tabelă; ultima observație: {day}.",
        "board_train_arrival": "Sosiri în București Nord", "board_train_departure": "Plecări din București Nord",
        "route_seen": "Ruta observată: {a} → {b}.",
        "stations_seen": "Stații observate pe tabelă (cu perioada):",
        "station_span": "{name}: {first} – {last} ({n})",
        "period": "Perioada acoperită: {first} – {last} ({n}).",
        "known": "Călătorii cu întârziere citită: {k}; mediana întârzierii: {median}.",
        "known_none": "Călătorii cu întârziere citită: 0 — date insuficiente pentru mediană.",
        "last_trips": "Ultimele {n} călătorii", "date": "Data", "sched": "Ora programată",
        "desc_board": "{board}: mediana {median} din {k} întârzieri citite.",
        "desc_board_none": "{board}: nicio întârziere citită încă.",
        "no_public": "Date insuficiente: trenul nu are încă nicio călătorie publică în istoric.",
        "station_board_arrival": "Sosiri din {name}", "station_board_departure": "Plecări spre {name}",
        "station_note": "Întârzierea este cea citită pe tabela din București Nord, nu la stația {name}.",
        "last_day": "Ultima zi observată", "journeys": "Călătorii", "known_col": "Cu întârziere citită",
        "median": "Mediana", "mean": "Media", "on_time_col": "La timp (≤ {m} min)",
        "station_none": "Niciun tren observat în acest sens.",
        "board_col": "Panou", "board_arrival": "Sosire", "board_departure": "Plecare", "station": "Stația",
        "stats_sample": "Perioada: {first} – {last} ({days}). Eșantion: N = {n} ({trains}), dintre care {k} "
                        "cu întârziere citită.",
        "stats_scope": "Fără trenurile de aeroport (Otopeni), ca în setarea implicită a paginii; „la timp” = "
                       "întârziere citită de cel mult {m} minute.",
        "stats_none": "Date insuficiente: încă nu există călătorii în istoric.",
        "rank_sample": "Perioada: {first} – {last}. Eșantion: N = {n}. În clasament intră {elig} cu cel puțin "
                       "{min} întârzieri citite ({below} sub prag). Sunt incluse toate trenurile, și cele de "
                       "aeroport.",
        "rank_threshold": "Pragul de punctualitate: un tren e „la timp” când întârzierea citită este de cel "
                          "mult {m} minute.",
        "rank_delayed": "Cele mai întârziate (după întârzierea medie)",
        "rank_punctual": "Cele mai punctuale (după procentul la timp)",
        "rank_none": "Date insuficiente: niciun tren nu are încă {min} întârzieri citite.",
        "disclaimer": "Date citite prin OCR de pe tabela CFR din Gara de Nord; pot conține erori. "
                      "Proiect independent, neafiliat CFR.",
    },
    "en": {
        "tabela": ("Bucharest North (Gara de Nord) – live arrivals and departures",
                   "See the trains shown right now on the Bucharest North (Gara de Nord) board, with the "
                   "scheduled time, the delay read and the announced platform. Check the time of the last "
                   "update."),
        "istoric": ("Arrivals and departures history · București Nord",
                    "Everything the București Nord board showed, day by day: scheduled times, delays "
                    "and platforms, filterable by train, station and time."),
        "urmarite": ("Followed trains · București Nord board",
                     "Follow a train and get a notification when its delay or platform changes."),
        "trenuri": ("Trains seen at București Nord · delay statistics",
                    "Catalogue of the trains seen on the București Nord board, with delay statistics "
                    "for arrivals and departures."),
        "statistici": ("Punctuality statistics · București Nord",
                       "How punctual the trains at București Nord are: delays, platforms and trends, "
                       "from the data read on the board."),
        "clasamente": ("Rankings: the most delayed and most punctual trains",
                       "The most delayed and most punctual trains and stations at București Nord, "
                       "only with a sufficient sample."),
        "statii": ("Stations: where the București Nord trains come from and go to",
                   "Origin and destination stations of the trains at București Nord, each with the "
                   "history and delays of its trains."),
        "versiuni": ("Versions · București Nord board", "Version history of the Tabela Gara de Nord app."),
        "cum": ("How the București Nord board app works",
                "How the data is read from the CFR board at București Nord, what it means and its limits."),
        "tren": ("{train} at Bucharest North | Delay history",
                 "{train}{route}: {n} on the Bucharest North (Gara de Nord) board ({first} – {last}). {boards}"),
        "tren_route": ("{train} {a} – {b} | Delay history", " ({a} – {b})"),
        "tren_h1": "Train {train} at Bucharest North", "gn": "Bucharest North",
        "statie": ("{name}: trains to and from București Nord",
                   "Trains between {name} and București Nord, seen on the board between {first} and "
                   "{last} (passages: {n}, trains: {trains}), with the delays read."),
        "statie_airport": ("Bucharest North to Otopeni Airport – train times and delays",
                           "Trains between Bucharest North (Gara de Nord) and Otopeni Airport (Henri Coandă), "
                           "arrivals and departures seen on the board between {first} and {last} (passages: "
                           "{n}, trains: {trains}), with the delays read."),
        "airport_name": "Otopeni Airport (Henri Coandă)",
        "404": ("Page not found · București Nord board", "The page you are looking for does not exist."),
        "home": "Board", "updated": "Last update (time the board was captured)", "arrivals": "Arrivals",
        "departures": "Departures",
        "time": "Time", "train": "Train", "from": "From", "to": "To", "delay": "Delay read",
        "platform": "Announced platform", "empty": "No trains on the board right now.", "route_to": " to {}",
        "route_from": " from {}", "operator": "Operator", "recent": "Recently seen trains",
        "all_stations": "All stations",
        "insufficient": "insufficient data", "unknown": "unknown", "live": "on the board now",
        "minutes": "{} min", "n_trips": ("journey", "journeys"), "n_trains": ("train", "trains"),
        "n_days": ("day", "days"),
        "category": "Category: {cat}. Number: {no}.",
        "last_seen": "Last seen on the board: {when}.",
        "on_board": "The train is on the board right now.",
        "absent": "The train is not on the board right now; last seen on {day}.",
        "board_train_arrival": "Arrivals at Bucharest North", "board_train_departure": "Departures from Bucharest North",
        "route_seen": "Observed route: {a} → {b}.",
        "stations_seen": "Stations seen on the board (with dates):",
        "station_span": "{name}: {first} – {last} ({n})",
        "period": "Period covered: {first} – {last} ({n}).",
        "known": "Journeys with a delay read: {k}; median delay: {median}.",
        "known_none": "Journeys with a delay read: 0 — insufficient data for a median.",
        "last_trips": "Last {n} journeys", "date": "Date", "sched": "Scheduled time",
        "desc_board": "{board}: median {median} from {k} delays read.",
        "desc_board_none": "{board}: no delay read yet.",
        "no_public": "Insufficient data: the train has no public journey in the history yet.",
        "station_board_arrival": "Arrivals from {name}", "station_board_departure": "Departures to {name}",
        "station_note": "The delay is the one read on the Bucharest North board, not at {name}.",
        "last_day": "Last day seen", "journeys": "Journeys", "known_col": "With a delay read",
        "median": "Median", "mean": "Mean", "on_time_col": "On time (≤ {m} min)",
        "station_none": "No train seen in this direction.",
        "board_col": "Board", "board_arrival": "Arrival", "board_departure": "Departure", "station": "Station",
        "stats_sample": "Period: {first} – {last} ({days}). Sample: N = {n} ({trains}), {k} of them with a "
                        "delay read.",
        "stats_scope": "Airport trains (Otopeni) left out, as in the page's default setting; “on time” = a "
                       "delay read of at most {m} minutes.",
        "stats_none": "Insufficient data: no journeys in the history yet.",
        "rank_sample": "Period: {first} – {last}. Sample: N = {n}. Ranked: {elig} with at least {min} delays "
                       "read ({below} below the minimum). Every train is included, airport trains too.",
        "rank_threshold": "Punctuality threshold: a train is “on time” when the delay read is at most {m} "
                          "minutes.",
        "rank_delayed": "Most delayed (by mean delay)",
        "rank_punctual": "Most punctual (by share on time)",
        "rank_none": "Insufficient data: no train has {min} delays read yet.",
        "disclaimer": "Data read via OCR from the CFR board at București Nord; it may contain errors. "
                      "Independent project, not affiliated with CFR.",
    },
}


@dataclass
class Page:
    path: str                  # canonical path ("/tren/1636")
    route: str                 # T key
    title: str
    description: str
    body: str = ""             # escaped HTML inside <section class="ssr">
    jsonld: list = field(default_factory=list)
    status: int = 200
    crumbs: list = field(default_factory=list)  # [(name, path)] after the home crumb
    h1: str = ""               # visible heading of the .ssr section; the title when empty
    noindex: bool = False


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def station_path(key: str) -> str:
    return "/statie/" + quote(key, safe="!*'()")  # = encodeURIComponent in app.js


def url(path: str, lang: str) -> str:
    return SITE + path + ("?lang=en" if lang == "en" else "")


def cached(cache: dict, key, ttl: float, fn):
    hit = cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < ttl:
        return hit[1]
    if len(cache) > CACHE_MAX:
        cache.clear()
    val = fn()
    cache[key] = (now, val)
    return val


def href(path: str, lang: str) -> str:
    """Relative link inside the .ssr content, kept in the page's language."""
    return path + ("?lang=en" if lang == "en" else "")


def _num(x, lang: str) -> str:
    if lang == "ro":
        return overview_v2._fmt(x)  # 37,5 / 3 — as on the Statistici page
    x = round(float(x), 1)
    return str(int(x)) if x == int(x) else f"{x:.1f}"


def _count(n: int, forms: tuple, lang: str) -> str:
    one, many = forms
    if lang == "ro":
        return overview_v2._pl(n, one, many)  # 1 călătorie, 2 călătorii, 20 de călătorii
    return f"{n} {one if n == 1 else many}"


def _mins(x, t, lang: str) -> str:
    return t["insufficient"] if x is None else t["minutes"].format(_num(x, lang))


def _pct(x, lang: str) -> str:
    return _num(x, lang) + "%"


def _delay(d, t) -> str:
    """A delay READ on the board; a missing reading stays unknown, never 0."""
    if d is None:
        return t["unknown"]
    return "0 min" if d == 0 else f"{int(d):+d} min"


def _when(stamp: str | None) -> str:
    if not stamp:
        return "?"
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(TZ).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return stamp[:16]


def _fill(tpl: str, **parts: str) -> str:
    """The escaped template with its {placeholders} replaced by ready (escaped) HTML."""
    out = esc(tpl)
    for k, v in parts.items():
        out = out.replace("{" + k + "}", v)
    return out


def _table(head: list[str], rows: list[list[str]]) -> str:
    """Cells are already escaped HTML."""
    th = "".join(f'<th scope="col">{esc(h)}</th>' for h in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


# -- data (own database only) ---------------------------------------------------

def _day(stamp: str | None) -> str:
    if not stamp:
        return "?"
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(TZ).date().isoformat()
    except ValueError:
        return stamp[:10]


def train_row(store, no: int) -> dict | None:
    with store._lock:
        r = store._conn.execute("SELECT * FROM trains WHERE train_no=? AND journeys > 0", (no,)).fetchone()
    return observations._train_dict(r) if r else None


def recent_trains(store, days: int = SITEMAP_DAYS, limit: int = SITEMAP_TRAINS_MAX) -> list[tuple[int, str]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with store._lock:
        rows = store._conn.execute(
            "SELECT train_no, last_seen FROM trains WHERE journeys > 0 AND last_seen >= ?"
            " ORDER BY last_seen DESC, train_no LIMIT ?", (cutoff, limit)).fetchall()
    return [(r["train_no"], r["last_seen"]) for r in rows]


def station_list(store) -> list[dict]:
    return [s for s in stations.list_stations(store, None, stations.LIST_MAX) if not s.get("uncertain_only")]


def train_summary(store, no: int) -> dict | None:
    """Catalog row + the figures of /api/trains/{no}/journeys (the same stats.load + train_entries
    as stats.train_profile, every journey kept, without its whole-catalog read), reduced to what
    the HTML shows so the cache stays small."""
    d = train_row(store, no)
    if d is None:
        return None
    p = stats.Params()
    js = sorted(stats.load(store, p, ["s.train_no = ?"], [no]),
                key=lambda j: (j["service_date"], j["sched_time"]), reverse=True)  # newest first
    boards = {}
    for e in stats.train_entries(js, p):
        bj = [j for j in js if j["board"] == e["board"]]
        spans: dict = {}
        for j in bj:
            s = spans.setdefault(j["station"], [j["service_date"], j["service_date"], 0])
            s[0], s[1], s[2] = min(s[0], j["service_date"]), max(s[1], j["service_date"]), s[2] + 1
        boards[e["board"]] = {
            "journeys": e["journeys"], "first": e["first_date"], "last": e["last_date"],
            "n": e["stats"]["n"], "median": e["stats"]["median"],
            "stations": sorted(spans.items(), key=lambda kv: (kv[1][1], kv[1][2]), reverse=True),
            "recent": [{"date": j["service_date"], "sched": j["sched_time"],
                        "delay": j["result"]["observed_delay"] if j["result"]["delay_known"] else None,
                        "live": j["result"]["state"] == "in_progress"} for j in bj[:RECENT_TRIPS]]}
    return {"no": no, "first_seen": d["first_seen"], "last_seen": d["last_seen"],
            "catalog_journeys": d["journeys"],
            "operators": [o["operator"] for o in d["operators"] if o.get("operator")],
            "category": js[0]["train_type"] if js else None,
            "live": any(j["result"]["state"] == "in_progress" for j in js),
            "journeys": len(js), "boards": {b: boards[b] for b in stats.BOARDS if b in boards}}


def station_summary(store, key: str) -> dict:
    """Per board, the trains of /api/stations/{name} (stats.train_entries), most recently seen first."""
    p = stats.Params()
    js = stats.load(store, p, [f"{journeys.STATION_SQL} = ?"], [key])
    out = {}
    for b in stats.BOARDS:
        es = stats.train_entries([j for j in js if j["board"] == b], p)
        es.sort(key=lambda e: (e["last_date"], e["train_no"]), reverse=True)
        out[b] = [{"no": e["train_no"], "type": e["train_type"], "last": e["last_date"],
                   "journeys": e["journeys"], "n": e["stats"]["n"], "median": e["stats"]["median"]}
                  for e in es[:STATION_TRAINS]]
    return out


def stats_summary(store) -> dict:
    """The head figures of /api/stats/overview with the Statistici defaults (perioada=all, airport
    out); overview() has its own short cache."""
    p = stats.Params(no_airport=True)
    d = overview_v2.overview(store, p, {"perioada": "all"})
    return {"on_time": p.on_time, "min_sample": p.min_sample, "coverage": d["coverage"],
            "boards": d["boards"]}


def _rank_row(e: dict) -> dict:
    return {"no": e["train_no"], "type": e["train_type"], "board": e["board"], "station": e["station"],
            **{k: e["stats"][k] for k in ("n", "mean", "median", "on_time_pct")}}


def rank_summary(store) -> dict:
    """The first rows of /api/stats/rankings with the Clasamente defaults (every journey kept)."""
    p = stats.Params()
    r = stats.rankings(store, p, RANK_ROWS)
    dates = [j["service_date"] for j in stats.load(store, p)]
    return {"on_time": p.on_time, "min_sample": p.min_sample, "journeys": len(dates),
            "first": min(dates) if dates else None, "last": max(dates) if dates else None,
            "eligible": r["eligible"], "below_min": r["below_min"],
            "most_delayed": [_rank_row(e) for e in r["most_delayed"]],
            "most_punctual": [_rank_row(e) for e in r["most_punctual"]]}


@lru_cache(maxsize=2)
def i18n(lang: str) -> dict:
    return json.loads((I18N_DIR / f"{lang}.json").read_text(encoding="utf-8"))


# -- pages ----------------------------------------------------------------------

def _disclaimer(t) -> str:
    return f'<p class="ssr-note">{esc(t["disclaimer"])}</p>'


def _train_link(no, kind, lang: str) -> str:
    label = esc(f"{kind or ''} {no}".strip())
    return f'<a href="{esc(href(f"/tren/{no}", lang))}">{label}</a>' if isinstance(no, int) else label


def _station_link(key: str, lang: str) -> str:
    name = esc(stations.display_name(key))
    return f'<a href="{esc(href(station_path(key), lang))}">{name}</a>' if key else name


def _board_html(board: dict, t, lang: str) -> str:
    out = []
    for key, other in (("departures", "to"), ("arrivals", "from")):
        rows = board.get(key) or []
        out.append(f'<h2>{esc(t[key])}</h2>')
        if not rows:
            out.append(f'<p>{esc(t["empty"])}</p>')
            continue
        out.append(_table([t["time"], t["train"], t[other], t["delay"], t["platform"]], [
            [esc(r.get("sched_time") or ""), _train_link(r.get("train_no"), r.get("train_type"), lang),
             _station_link(r.get("station") or "", lang),
             # "—": not read on the board right now (never shown as 0)
             esc("—" if r.get("delay_min") is None else _delay(r["delay_min"], t)),
             esc(r.get("platform") or "—")] for r in rows[:BOARD_ROWS]]))
    return "".join(out)


def _stats_html(d: dict, t, lang: str) -> str:
    cov = d["coverage"]
    if not cov["journeys"]:
        return f'<p>{esc(t["stats_none"])}</p>'
    sample = t["stats_sample"].format(
        first=cov["first"], last=cov["last"], days=_count(cov["days"], t["n_days"], lang),
        n=_count(cov["journeys"], t["n_trips"], lang), trains=_count(cov["trains"], t["n_trains"], lang),
        k=cov["delay_known"])
    out = [f'<p>{esc(sample)}</p>', f'<p>{esc(t["stats_scope"].format(m=d["on_time"]))}</p>']
    rows = [[esc(t[b + "s"]), esc(s["n"]), esc(_mins(s["median"], t, lang)), esc(_mins(s["mean"], t, lang)),
             esc(t["insufficient"] if s["on_time_pct"] is None else _pct(s["on_time_pct"], lang))]
            for b, s in d["boards"].items()]
    head = [t["board_col"], "N", t["median"], t["mean"], t["on_time_col"].format(m=d["on_time"])]
    out.append(_table(head, rows))
    return "".join(out)


def _rank_html(d: dict, t, lang: str) -> str:
    out = [f'<p>{esc(t["rank_threshold"].format(m=d["on_time"]))}</p>']
    if not d["journeys"]:
        return out[0] + f'<p>{esc(t["stats_none"])}</p>'
    sample = t["rank_sample"].format(
        first=d["first"], last=d["last"], n=_count(d["journeys"], t["n_trips"], lang),
        elig=_count(d["eligible"], t["n_trains"], lang), min=d["min_sample"], below=d["below_min"])
    out.append(f'<p>{esc(sample)}</p>')
    if not d["eligible"]:
        out.append(f'<p>{esc(t["rank_none"].format(min=d["min_sample"]))}</p>')
        return "".join(out)
    head = ["#", t["train"], t["board_col"], t["station"], "N", t["mean"], t["median"],
            t["on_time_col"].format(m=d["on_time"])]
    for name in ("delayed", "punctual"):
        out.append(f'<h2>{esc(t["rank_" + name])}</h2>')
        out.append(_table(head, [
            [str(i), _train_link(e["no"], e["type"], lang), esc(t["board_" + e["board"]]),
             _station_link(e["station"] or "", lang), esc(e["n"]), esc(_mins(e["mean"], t, lang)),
             esc(_mins(e["median"], t, lang)),
             esc(t["insufficient"] if e["on_time_pct"] is None else _pct(e["on_time_pct"], lang))]
            for i, e in enumerate(d["most_" + name], 1)]))
    return "".join(out)


def _cum_html(lang: str) -> str:
    """The text of web/cum.js, from the same i18n file."""
    s = i18n(lang)
    issues = f'<p><a href="{esc(REPO)}/issues">{esc(s["cum.report.issues"])}</a></p>'
    out = [f'<p>{esc(s["cum.intro"])}</p>']
    for key, n in CUM_SECTIONS:
        out.append(f'<h2>{esc(s[f"cum.{key}.title"])}</h2>')
        out += [f'<p>{esc(s[f"cum.{key}.p{i}"])}</p>' for i in range(1, n + 1)]
        if key in ("method", "report"):
            out.append(issues)
    return "".join(out)


def static_page(name: str, lang: str, store, cache) -> Page:
    t = T[lang]
    title, desc = t[name]
    path = "/" if name == "tabela" else "/" + name
    body = ""
    if name == "tabela":
        from app.api import STALE_S  # noqa: PLC0415  (api imports this module)
        board = cached(cache, ("board",), TTL_PAGE, lambda: store.current_board(datetime.now(TZ), STALE_S))
        upd = board.get("updated_at")
        body = (f'<p>{esc(t["updated"])}: {esc(str(upd)[:16].replace("T", " ") if upd else "—")}</p>'
                + _board_html(board, t, lang))
    elif name == "statii":
        items = cached(cache, ("stations",), TTL_DATA, lambda: station_list(store))
        body = (f'<h2>{esc(t["all_stations"])}</h2><ul>' + "".join(
            f'<li><a href="{esc(href(station_path(s["name"]), lang))}">{esc(s["display_name"])}</a></li>'
            for s in items) + "</ul>")
    elif name == "trenuri":
        items = cached(cache, ("trains",), TTL_DATA, lambda: recent_trains(store))[:200]
        body = (f'<h2>{esc(t["recent"])}</h2><ul>' + "".join(
            f'<li><a href="{esc(href(f"/tren/{no}", lang))}">{esc(t["train"])} {no}</a></li>'
            for no, _ in items) + "</ul>")
    elif name == "statistici":
        body = _stats_html(cached(cache, ("stats",), TTL_PAGE, lambda: stats_summary(store)), t, lang)
    elif name == "clasamente":
        body = _rank_html(cached(cache, ("rank",), TTL_PAGE, lambda: rank_summary(store)), t, lang)
    elif name == "cum":
        body = _cum_html(lang)
    crumbs = [] if name == "tabela" else [(title.split(" · ")[0], path)]
    return Page(path, name, title, desc, body, crumbs=crumbs, noindex=name in NOINDEX)


def train_page(no: int, lang: str, store, cache) -> Page | None:
    d = cached(cache, ("train", no), TTL_PAGE, lambda: train_summary(store, no))
    if d is None:
        return None
    t = T[lang]
    train = f'{d["category"] or ""} {no}'.strip()
    boards = d["boards"]
    # the route goes in the title only when the data confirms it: one board, one station seen
    route = None
    if len(boards) == 1:
        (b, info), = boards.items()
        if len(info["stations"]) == 1:
            st = info["stations"][0][0]
            name = stations.display_name(st)
            route = (b, st, *((name, t["gn"]) if b == "arrival" else (t["gn"], name)))
    if route:
        title = t["tren_route"][0].format(train=train, a=route[2], b=route[3])
        route_txt = t["tren_route"][1].format(a=route[2], b=route[3])
    else:
        title, route_txt = t["tren"][0].format(train=train), ""
    if boards:
        parts = [(t["desc_board"] if i["n"] else t["desc_board_none"]).format(
            board=t[b + "s"], median=_mins(i["median"], t, lang), k=i["n"]) for b, i in boards.items()]
        first = min(i["first"] for i in boards.values())
        last = max(i["last"] for i in boards.values())
        n = d["journeys"]
    else:
        parts, n = [t["no_public"]], d["catalog_journeys"]
        first, last = _day(d["first_seen"]), _day(d["last_seen"])
    desc = t["tren"][1].format(train=train, route=route_txt, n=_count(n, t["n_trips"], lang), first=first,
                               last=last, boards=" ".join(parts))

    body = [f'<p>{esc(desc)}</p>']
    if d["category"]:
        body.append(f'<p>{esc(t["category"].format(cat=d["category"], no=no))}</p>')
    body.append(f'<p>{esc(t["last_seen"].format(when=_when(d["last_seen"])))}</p>')
    body.append(f'<p>{esc(t["on_board"] if d["live"] else t["absent"].format(day=_day(d["last_seen"])))}</p>')
    if d["operators"]:
        body.append(f'<p>{esc(t["operator"])}: {esc(", ".join(d["operators"][:3]))}</p>')
    for b, i in boards.items():
        body.append(f'<h2>{esc(t["board_train_" + b])}</h2>')
        if len(i["stations"]) == 1:
            link = _station_link(i["stations"][0][0], lang)
            a, z = (link, esc(t["gn"])) if b == "arrival" else (esc(t["gn"]), link)
            body.append(f'<p>{_fill(t["route_seen"], a=a, b=z)}</p>')
        else:
            items = [_fill(t["station_span"], name=_station_link(st, lang), first=esc(f), last=esc(la),
                           n=esc(_count(k, t["n_trips"], lang))) for st, (f, la, k) in i["stations"]]
            body.append(f'<p>{esc(t["stations_seen"])}</p><ul>' + "".join(f"<li>{x}</li>" for x in items) + "</ul>")
        period = t["period"].format(first=i["first"], last=i["last"], n=_count(i["journeys"], t["n_trips"], lang))
        known = t["known"].format(k=i["n"], median=_mins(i["median"], t, lang)) if i["n"] else t["known_none"]
        body += [f'<p>{esc(period)}</p>', f'<p>{esc(known)}</p>',
                 f'<h3>{esc(t["last_trips"].format(n=len(i["recent"])))}</h3>']
        body.append(_table([t["date"], t["sched"], t["delay"]], [
            [esc(j["date"]), esc(j["sched"]), esc(_delay(j["delay"], t) + (f' ({t["live"]})' if j["live"] else ""))]
            for j in i["recent"]]))

    trip = {"@type": "TrainTrip", "name": train, "trainNumber": str(no)}
    if route:
        other = {"@type": "TrainStation", "name": stations.display_name(route[1])}
        gara = {"@id": GARA["@id"], "@type": "TrainStation", "name": GARA["name"]}
        trip["departureStation"], trip["arrivalStation"] = (gara, other) if route[0] == "departure" else (other, gara)
    if d["operators"]:
        trip["provider"] = {"@type": "Organization", "name": d["operators"][0]}
    return Page(f"/tren/{no}", "tren", title, desc, "".join(body), [trip],
                crumbs=[(T[lang]["trenuri"][0].split(" · ")[0], "/trenuri"), (train, f"/tren/{no}")],
                h1=t["tren_h1"].format(train=train))


def station_page(key: str, lang: str, store, cache) -> Page | None:
    items = cached(cache, ("stations",), TTL_DATA, lambda: station_list(store))
    s = next((i for i in items if i["name"] == key), None)
    if s is None:
        return None
    t = T[lang]
    airport = key == AIRPORT  # people search for "Otopeni", the board says "AEROPORT H COANDA"
    fmt = {"name": s["display_name"], "n": s["journeys"], "trains": s["trains"],
           "first": s["first_date"] or "?", "last": s["last_date"] or "?"}
    title, desc = (x.format(**fmt) for x in t["statie_airport" if airport else "statie"])
    path = station_path(key)
    label = t["airport_name"] if airport else s["display_name"]
    data = cached(cache, ("station", key), TTL_PAGE, lambda: station_summary(store, key))
    body = [f'<p>{esc(desc)}</p>', f'<p>{esc(t["station_note"].format(name=label))}</p>']
    for b in stats.BOARDS:
        body.append(f'<h2>{esc(t["station_board_" + b].format(name=label))}</h2>')
        rows = data.get(b) or []
        if not rows:
            body.append(f'<p>{esc(t["station_none"])}</p>')
            continue
        body.append(_table([t["train"], t["last_day"], t["journeys"], t["known_col"], t["median"]], [
            [_train_link(e["no"], e["type"], lang), esc(e["last"]), esc(e["journeys"]), esc(e["n"]),
             esc(_mins(e["median"], t, lang))] for e in rows]))
    place = {"@type": "TrainStation", "name": s["display_name"]}
    if airport:
        place["alternateName"] = ["Otopeni", t["airport_name"]]
    return Page(path, "statie", title, desc, "".join(body), [place],
                crumbs=[(T[lang]["statii"][0].split(":")[0], "/statii"), (s["display_name"], path)])


def not_found_page(path: str, lang: str) -> Page:
    title, desc = T[lang]["404"]
    return Page(path, "404", title, desc, f'<p>{esc(desc)} <a href="/">{esc(NAME)}</a></p>', status=404)


# -- head/body injection --------------------------------------------------------

def _jsonld(page: Page, lang: str) -> dict:
    me = url(page.path, lang)
    site = {"@type": "WebSite", "@id": SITE + "/#website", "name": NAME, "url": SITE + "/",
            "inLanguage": ["ro", "en"], "publisher": {"@id": PUBLISHER["@id"]}}
    web = {"@type": "WebPage", "@id": me, "url": me, "name": page.title, "description": page.description,
           "inLanguage": lang, "isPartOf": {"@id": site["@id"]}, "about": {"@id": GARA["@id"]}}
    items = [{"@type": "ListItem", "position": 1, "name": T[lang]["home"], "item": url("/", lang)}]
    for i, (name, p) in enumerate(page.crumbs, 2):
        items.append({"@type": "ListItem", "position": i, "name": name, "item": url(p, lang)})
    graph = [PUBLISHER, site, GARA, web]
    if len(items) > 1:
        web["breadcrumb"] = {"@type": "BreadcrumbList", "itemListElement": items}
    if page.jsonld:
        web["mainEntity"] = page.jsonld[0]
    return {"@context": "https://schema.org", "@graph": graph}


def _ld_json(data) -> str:
    # a data block, not executed (CSP only governs scripts); "<" escaped so it cannot close the tag
    return (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def _set(html_: str, pattern: str, value: str) -> str:
    return re.sub(pattern, lambda m: m.group(1) + esc(value) + m.group(2), html_, count=1)


def indexable_page(page: Page) -> bool:
    return page.status == 200 and not page.noindex


def render(shell: str, page: Page, lang: str) -> str:
    """index.html (already in `lang`) with the page's head and content."""
    me = url(page.path, lang)
    h = shell
    h = re.sub(r"<title>[^<]*</title>", lambda m: f"<title>{esc(page.title)}</title>", h, count=1)
    for attr, name, val in (("name", "description", page.description), ("property", "og:title", page.title),
                            ("property", "og:description", page.description), ("property", "og:url", me),
                            ("name", "twitter:title", page.title),
                            ("name", "twitter:description", page.description)):
        h = _set(h, rf'(<meta {attr}="{re.escape(name)}" content=")[^"]*(">)', val)
    head = []
    indexable = indexable_page(page)
    if indexable:
        head.append(f'<link rel="canonical" href="{esc(me)}">')
        for code in ("ro", "en"):
            head.append(f'<link rel="alternate" hreflang="{code}" href="{esc(url(page.path, code))}">')
        head.append(f'<link rel="alternate" hreflang="x-default" href="{esc(url(page.path, "ro"))}">')
    else:
        head.append('<meta name="robots" content="noindex">')
    for env, meta in (("GOOGLE_SITE_VERIFICATION", "google-site-verification"),
                      ("BING_SITE_VERIFICATION", "msvalidate.01")):
        token = os.environ.get(env, "").strip()
        if token:
            head.append(f'<meta name="{meta}" content="{esc(token)}">')
    if indexable:
        head.append(f'<script type="application/ld+json">{_ld_json(_jsonld(page, lang))}</script>')
    h = h.replace("</head>", "  " + "\n  ".join(head) + "\n</head>", 1)
    body = (f'<section class="ssr" aria-labelledby="ssr-h"><h1 id="ssr-h">{esc(page.h1 or page.title)}</h1>'
            f'{page.body}{_disclaimer(T[lang])}</section>')
    return h.replace('<main id="main" tabindex="-1">', '<main id="main" tabindex="-1">\n    ' + body, 1)


# -- robots / sitemap -----------------------------------------------------------

def robots_txt() -> str:
    lines = ["User-agent: *", "Allow: /", "Disallow: /api/", "Disallow: /offline.html"]
    lines += [f"Disallow: /{p}" for p in PRIVATE]
    return "\n".join(lines + ["", f"Sitemap: {SITE}/sitemap.xml", ""])


def sitemap_xml(store) -> str:
    with store._lock:
        last = store._last_ok_ts()   # the board changes with each capture, not with each request
    entries = [("/", _day(last))] + [("/" + p, None) for p in PUBLIC if p not in NOINDEX]
    entries += [(f"/tren/{no}", _day(seen)) for no, seen in recent_trains(store)]
    entries += [(station_path(s["name"]), s["last_date"]) for s in station_list(store)]
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for path, lastmod in entries:
        alt = "".join(f'<xhtml:link rel="alternate" hreflang="{c}" href="{esc(url(path, l))}"/>'
                      for c, l in (("ro", "ro"), ("en", "en"), ("x-default", "ro")))
        mod = f"<lastmod>{esc(lastmod)}</lastmod>" if lastmod and lastmod != "?" else ""
        for lang in ("ro", "en"):  # every language version listed, each with all alternates
            out.append(f"<url><loc>{esc(url(path, lang))}</loc>{mod}{alt}</url>")
    return "\n".join(out + ["</urlset>", ""])
