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
from urllib.parse import quote

from app import observations, stations
from app.store import TZ

SITE = os.environ.get("SITE_URL", "https://tabelacfr.ddns.net").rstrip("/")
NAME = "Tabela Gara de Nord"
PUBLIC = ("istoric", "urmarite", "trenuri", "statistici", "clasamente", "statii", "versiuni", "cum")
PRIVATE = ("admin", "ocr", "ocr2", "infofer", "sistem", "setari")  # hash-only, noindex
BOARD_ROWS = 20
SITEMAP_DAYS = 90
SITEMAP_TRAINS_MAX = 5000
TTL_PAGE = 60.0
TTL_DATA = 600.0
CACHE_MAX = 2000
GARA = {"@type": "TrainStation", "@id": SITE + "/#gara-de-nord", "name": "București Nord",
        "alternateName": "Gara de Nord",
        "address": {"@type": "PostalAddress", "addressLocality": "București", "addressCountry": "RO"},
        "geo": {"@type": "GeoCoordinates", "latitude": 44.4467, "longitude": 26.0747}}
PUBLISHER = {"@type": "Organization", "@id": SITE + "/#publisher",
             "name": "Tabela Gara de Nord (proiect independent, neafiliat CFR)", "url": SITE + "/",
             "founder": {"@type": "Person", "name": "Andy217Ace"}}

T = {
    "ro": {
        "tabela": ("Tabela Gara de Nord — sosiri și plecări live",
                   "Sosirile și plecările din Gara de Nord București, actualizate în timp real: ore, "
                   "întârzieri și linii. Proiect independent, cu date preluate de la CFR."),
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
        "tren": ("Trenul {no}{route} · Gara de Nord", "Trenul {no}{route}, observat pe tabela din Gara de "
                 "Nord între {first} și {last} (treceri: {n}), cu întârzieri și linii."),
        "statie": ("{name}: trenuri spre și dinspre Gara de Nord",
                   "Trenurile dintre {name} și Gara de Nord București, observate pe tabelă între "
                   "{first} și {last} (treceri: {n}, trenuri: {trains}), cu întârzierile citite."),
        "404": ("Pagina nu există · Tabela Gara de Nord", "Pagina căutată nu există."),
        "home": "Tabela", "updated": "Actualizat", "arrivals": "Sosiri", "departures": "Plecări",
        "time": "Ora", "train": "Tren", "from": "Din", "to": "Spre", "delay": "Întârziere",
        "platform": "Linia", "empty": "Nu sunt trenuri afișate acum.", "route_to": " spre {}",
        "route_from": " din {}", "operator": "Operator", "recent": "Trenuri văzute recent",
        "all_stations": "Toate stațiile",
        "disclaimer": "Date citite prin OCR de pe tabela CFR din Gara de Nord; pot conține erori. "
                      "Proiect independent, neafiliat CFR.",
    },
    "en": {
        "tabela": ("București Nord station board — live arrivals and departures",
                   "Live arrivals and departures at București Nord (Gara de Nord): times, delays and "
                   "platforms. Independent project, data read from the CFR board."),
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
        "tren": ("Train {no}{route} · București Nord", "Train {no}{route}, seen on the București Nord "
                 "board between {first} and {last} (passages: {n}), with delays and platforms."),
        "statie": ("{name}: trains to and from București Nord",
                   "Trains between {name} and București Nord, seen on the board between {first} and "
                   "{last} (passages: {n}, trains: {trains}), with the delays read."),
        "404": ("Page not found · București Nord board", "The page you are looking for does not exist."),
        "home": "Board", "updated": "Updated", "arrivals": "Arrivals", "departures": "Departures",
        "time": "Time", "train": "Train", "from": "From", "to": "To", "delay": "Delay",
        "platform": "Platform", "empty": "No trains on the board right now.", "route_to": " to {}",
        "route_from": " from {}", "operator": "Operator", "recent": "Recently seen trains",
        "all_stations": "All stations",
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


# -- pages ----------------------------------------------------------------------

def _disclaimer(t) -> str:
    return f'<p class="ssr-note">{esc(t["disclaimer"])}</p>'


def _board_html(board: dict, t) -> str:
    out = []
    for key, other in (("departures", "to"), ("arrivals", "from")):
        rows = board.get(key) or []
        out.append(f'<h2>{esc(t[key])}</h2>')
        if not rows:
            out.append(f'<p>{esc(t["empty"])}</p>')
            continue
        out.append(f'<table><thead><tr><th scope="col">{esc(t["time"])}</th><th scope="col">{esc(t["train"])}</th>'
                   f'<th scope="col">{esc(t[other])}</th><th scope="col">{esc(t["delay"])}</th>'
                   f'<th scope="col">{esc(t["platform"])}</th></tr></thead><tbody>')
        for r in rows[:BOARD_ROWS]:
            no, st = r.get("train_no"), r.get("station") or ""
            train = esc(f'{r.get("train_type") or ""} {no}'.strip())
            if isinstance(no, int):
                train = f'<a href="/tren/{no}">{train}</a>'
            name = esc(stations.display_name(st))
            if st:
                name = f'<a href="{esc(station_path(st))}">{name}</a>'
            d = r.get("delay_min")
            delay = "—" if d is None else ("0" if d == 0 else f"+{int(d)} min")
            out.append(f'<tr><td>{esc(r.get("sched_time") or "")}</td><td>{train}</td><td>{name}</td>'
                       f'<td>{esc(delay)}</td><td>{esc(r.get("platform") or "—")}</td></tr>')
        out.append("</tbody></table>")
    return "".join(out)


def _route_text(routes: list, t) -> tuple[str, str | None, str | None]:
    """(" spre Brașov", board, station key) of the train's most frequent route."""
    if not routes:
        return "", None, None
    r = routes[0]
    tpl = t["route_to"] if r.get("board") == "departure" else t["route_from"]
    return tpl.format(stations.display_name(r["station"])), r.get("board"), r["station"]


def static_page(name: str, lang: str, store, cache) -> Page:
    t = T[lang]
    title, desc = t[name]
    path = "/" if name == "tabela" else "/" + name
    body = ""
    if name == "tabela":
        from app.api import STALE_S  # noqa: PLC0415  (api imports this module)
        board = cached(cache, ("board",), TTL_PAGE, lambda: store.current_board(datetime.now(TZ), STALE_S))
        upd = board.get("updated_at")
        body = (f'<p>{esc(t["updated"])}: {esc(str(upd)[:16].replace("T", " ") if upd else "—")}</p>' + _board_html(board, t))
    elif name == "statii":
        items = cached(cache, ("stations",), TTL_DATA, lambda: station_list(store))
        body = (f'<h2>{esc(t["all_stations"])}</h2><ul>' + "".join(
            f'<li><a href="{esc(station_path(s["name"]))}">{esc(s["display_name"])}</a></li>' for s in items)
                + "</ul>")
    elif name == "trenuri":
        items = cached(cache, ("trains",), TTL_DATA, lambda: recent_trains(store))[:200]
        body = (f'<h2>{esc(t["recent"])}</h2><ul>' + "".join(
            f'<li><a href="/tren/{no}">{esc(t["train"])} {no}</a></li>' for no, _ in items) + "</ul>")
    crumbs = [] if name == "tabela" else [(title.split(" · ")[0], path)]
    return Page(path, name, title, desc, body, crumbs=crumbs)


def train_page(no: int, lang: str, store, cache) -> Page | None:
    d = cached(cache, ("train", no), TTL_PAGE, lambda: train_row(store, no))
    if d is None:
        return None
    t = T[lang]
    route, board, st = _route_text(d["routes"], t)
    fmt = {"no": no, "route": route, "n": d["journeys"], "first": _day(d["first_seen"]),
           "last": _day(d["last_seen"])}
    title, desc = (s.format(**fmt) for s in t["tren"])
    ops = [o["operator"] for o in d["operators"] if o.get("operator")]
    body = f'<p>{esc(desc)}</p>'
    if ops:
        body += f'<p>{esc(t["operator"])}: {esc(", ".join(ops[:3]))}</p>'
    if st:
        body += f'<p><a href="{esc(station_path(st))}">{esc(stations.display_name(st))}</a></p>'
    trip = {"@type": "TrainTrip", "name": f"{t['train']} {no}", "trainNumber": str(no)}
    if st:
        other = {"@type": "TrainStation", "name": stations.display_name(st)}
        gara = {"@id": GARA["@id"], "@type": "TrainStation", "name": GARA["name"]}
        trip["departureStation"], trip["arrivalStation"] = (gara, other) if board == "departure" else (other, gara)
    if ops:
        trip["provider"] = {"@type": "Organization", "name": ops[0]}
    return Page(f"/tren/{no}", "tren", title, desc, body, [trip],
                crumbs=[(T[lang]["trenuri"][0].split(" · ")[0], "/trenuri"), (f"{t['train']} {no}", f"/tren/{no}")])


def station_page(key: str, lang: str, store, cache) -> Page | None:
    items = cached(cache, ("stations",), TTL_DATA, lambda: station_list(store))
    s = next((i for i in items if i["name"] == key), None)
    if s is None:
        return None
    t = T[lang]
    fmt = {"name": s["display_name"], "n": s["journeys"], "trains": s["trains"],
           "first": s["first_date"] or "?", "last": s["last_date"] or "?"}
    title, desc = (x.format(**fmt) for x in t["statie"])
    path = station_path(key)
    place = {"@type": "TrainStation", "name": s["display_name"]}
    return Page(path, "statie", title, desc, f'<p>{esc(desc)}</p>', [place],
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
    indexable = page.status == 200
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
    body = (f'<section class="ssr" aria-labelledby="ssr-h"><h1 id="ssr-h">{esc(page.title)}</h1>'
            f'{page.body}{_disclaimer(T[lang])}</section>')
    return h.replace('<main id="main" tabindex="-1">', '<main id="main" tabindex="-1">\n    ' + body, 1)


# -- robots / sitemap -----------------------------------------------------------

def robots_txt() -> str:
    lines = ["User-agent: *", "Allow: /", "Disallow: /api/", "Disallow: /offline.html"]
    lines += [f"Disallow: /{p}" for p in PRIVATE]
    return "\n".join(lines + ["", f"Sitemap: {SITE}/sitemap.xml", ""])


def sitemap_xml(store) -> str:
    today = datetime.now(TZ).date().isoformat()
    entries = [("/", today)] + [("/" + p, None) for p in PUBLIC]
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
