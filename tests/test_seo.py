# © 2026 Andy217Ace
"""SEO (app/seo.py): path URLs with their own head, canonical/hreflang, JSON-LD, server-rendered
content, 404 + noindex, redirects, robots.txt and sitemap.xml."""
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import observations, seo
from app.api import create_app
from app.config import Settings
from app.store import Store
from tests.test_stats import add

ROOT = Path(__file__).resolve().parent.parent
SITE = seo.SITE


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    p = tmp_path_factory.mktemp("seo") / "s.db"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "dev_seed.py"), str(p)],
                   check=True, cwd=ROOT, capture_output=True)
    return str(p)


@pytest.fixture
def client(db):
    s = Settings(db_path=db, source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract")
    with TestClient(create_app(s, start_poller=False)) as c:
        st = c.app.state.store
        with st._lock:  # the seed has services only: build the public trains catalog
            nos = [r[0] for r in st._conn.execute("SELECT DISTINCT train_no FROM services")]
            observations.refresh_trains(st._conn, nos)
            st._conn.commit()
        yield c


def _ld(h):
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)
    assert len(blocks) == 1
    return json.loads(blocks[0])


def _types(ld):
    return {n["@type"] for n in ld["@graph"]}


@pytest.mark.parametrize("path", ["/"] + ["/" + p for p in seo.PUBLIC])
def test_public_pages_have_own_head(client, path):
    r = client.get(path)
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    h = r.text
    title, desc = seo.T["ro"]["tabela" if path == "/" else path[1:]]
    assert f"<title>{seo.esc(title)}</title>" in h
    assert f'<meta name="description" content="{seo.esc(desc)}">' in h
    assert f'<link rel="canonical" href="{SITE}{path}">' in h
    assert f'<meta property="og:url" content="{SITE}{path}">' in h
    assert f'<link rel="alternate" hreflang="en" href="{SITE}{path}?lang=en">' in h
    assert f'<link rel="alternate" hreflang="x-default" href="{SITE}{path}">' in h
    assert 'name="robots"' not in h and "X-Robots-Tag" not in r.headers
    assert '<base href="/">' in h
    assert '<section class="ssr"' in h and seo.T["ro"]["disclaimer"] in h
    ld = _ld(h)
    assert {"WebSite", "WebPage", "Organization", "TrainStation"} <= _types(ld)
    pub = next(n for n in ld["@graph"] if n["@type"] == "Organization")
    assert "independent" in pub["name"] and pub["name"] != "CFR"


def test_english_version(client):
    h = client.get("/statistici?lang=en").text
    assert '<html lang="en">' in h
    assert f'<link rel="canonical" href="{SITE}/statistici?lang=en">' in h
    assert seo.esc(seo.T["en"]["statistici"][0]) in h and seo.T["en"]["disclaimer"] in h
    assert _ld(h)["@graph"][-1]["inLanguage"] == "en"


def test_canonical_ignores_filters(client):
    h = client.get("/istoric?date=2026-11-27&train=1636").text
    assert f'<link rel="canonical" href="{SITE}/istoric">' in h


def test_home_renders_the_board(client):
    h = client.get("/").text
    ssr = h[h.index('<section class="ssr"'):h.index("</section>", h.index('<section class="ssr"'))]
    assert "<table>" in ssr and 'href="/tren/' in ssr and 'href="/statie/' in ssr
    assert ssr.count("<tr>") <= 2 * (seo.BOARD_ROWS + 1)
    assert "infofer" not in ssr.lower()


def test_train_page(client):
    r = client.get("/tren/1636")
    assert r.status_code == 200
    h = r.text
    assert "<title>IR 1636 Brașov – București Nord | Istoric întârzieri</title>" in h
    assert '<h1 id="ssr-h">Trenul IR 1636 la București Nord</h1>' in h and f'href="{SITE}/tren/1636"' in h
    trip = _ld(h)["@graph"][-1]["mainEntity"]
    assert trip["@type"] == "TrainTrip" and trip["trainNumber"] == "1636"
    assert {trip["departureStation"]["name"], trip["arrivalStation"]["name"]} >= {"București Nord"}
    crumbs = _ld(h)["@graph"][-1]["breadcrumb"]["itemListElement"]
    assert [c["position"] for c in crumbs] == [1, 2, 3] and crumbs[-1]["item"] == f"{SITE}/tren/1636"


def test_station_page_and_redirects(client):
    r = client.get("/statie/BRASOV")
    assert r.status_code == 200 and "<title>Brașov: trenuri" in r.text
    assert _ld(r.text)["@graph"][-1]["mainEntity"] == {"@type": "TrainStation", "name": "Brașov"}
    for path in ("/statie/brasov", "/statie/Bra%C8%99ov"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 301 and r.headers["location"] == "/statie/BRASOV", path


@pytest.mark.parametrize("path", ["/tren/999999", "/tren/abc", "/statie/NU%20EXISTA", "/nu-exista",
                                  "/istoric/x", "/missing.js"])
def test_unknown_is_html_404_noindex(client, path):
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 404, path
    assert "text/html" in r.headers["content-type"]
    assert r.headers["x-robots-tag"] == "noindex"
    assert '<meta name="robots" content="noindex">' in r.text
    assert 'rel="canonical"' not in r.text and "application/ld+json" not in r.text


def test_api_404_stays_json_and_noindex(client):
    r = client.get("/api/nu-exista")
    assert r.status_code == 404 and r.json() == {"detail": "Nu există."}
    assert client.get("/api/health").headers["x-robots-tag"] == "noindex"


@pytest.mark.parametrize("path,target,code", [
    ("/Statistici/", "/statistici", 301), ("/trenuri/", "/trenuri", 301), ("/TREN/1636", "/tren/1636", 301),
    ("/tren/01636", "/tren/1636", 301), ("/tren", "/trenuri", 301), ("/statie", "/statii", 301),
    ("/admin", "/#admin", 302), ("/sistem", "/#sistem", 302)])
def test_redirects(client, path, target, code):
    r = client.get(path, follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (code, target)


def test_private_redirect_is_noindex(client):
    assert client.get("/ocr", follow_redirects=False).headers["x-robots-tag"] == "noindex"


def test_escaping(client, monkeypatch):
    evil = '<script>alert("x")</script>&'
    monkeypatch.setattr(seo, "station_list", lambda store: [
        {"name": "EVIL", "display_name": evil, "journeys": 1, "trains": 1,
         "first_date": "2026-11-01", "last_date": "2026-11-02"}])
    h = client.get("/statie/EVIL").text
    assert "<script>alert" not in h
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;&amp;" in h
    raw = re.search(r'<script type="application/ld\+json">(.*?)</script>', h, re.S).group(1)
    assert "<" not in raw and "\\u003cscript\\u003e" in raw
    assert json.loads(raw)["@graph"][-1]["mainEntity"]["name"] == evil


def test_site_verification_only_from_env(client, monkeypatch):
    assert "google-site-verification" not in client.get("/").text
    monkeypatch.setenv("GOOGLE_SITE_VERIFICATION", 'abc"<x')
    monkeypatch.setenv("BING_SITE_VERIFICATION", "B1NG")
    h = client.get("/cum").text   # not cached yet in this app
    assert '<meta name="google-site-verification" content="abc&quot;&lt;x">' in h
    assert '<meta name="msvalidate.01" content="B1NG">' in h


def test_robots(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    t = r.text
    assert "User-agent: *" in t and "Disallow: /api/" in t and f"Sitemap: {SITE}/sitemap.xml" in t
    for p in seo.PRIVATE:
        assert f"Disallow: /{p}\n" in t


def test_sitemap(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200 and "xml" in r.headers["content-type"]
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "x": "http://www.w3.org/1999/xhtml"}
    root = ET.fromstring(r.content)
    urls = root.findall("s:url", ns)
    locs = [u.find("s:loc", ns).text for u in urls]
    assert f"{SITE}/" in locs and f"{SITE}/?lang=en" in locs and f"{SITE}/tren/1636" in locs
    assert f"{SITE}/statie/BRASOV" in locs and f"{SITE}/statistici?lang=en" in locs
    assert len(locs) == len(set(locs))
    for loc in locs:
        assert loc.startswith(SITE + "/")
        path = loc[len(SITE):].split("?")[0]
        assert not path.startswith("/api/") and "infofer" not in loc.lower()
        assert path.split("/")[1] not in seo.PRIVATE
    for u in urls:
        alts = {a.get("hreflang"): a.get("href") for a in u.findall("x:link", ns)}
        assert set(alts) == {"ro", "en", "x-default"} and alts["en"].endswith("lang=en")


def test_head_on_seo_routes(client):
    for path in ("/robots.txt", "/sitemap.xml", "/", "/statistici"):
        g, h = client.get(path), client.head(path)
        assert h.status_code == g.status_code == 200, path
        assert h.headers["content-type"] == g.headers["content-type"], path


# ---- server-rendered content (.ssr) with real journeys ---------------------------------

@pytest.fixture
def rich(tmp_path):
    db = tmp_path / "r.db"
    s = Store(str(db))
    s.migrate()
    s._conn.close()
    st = Settings(db_path=str(db), source_url="http://x", vapid_private_key="", vapid_public_key="",
                  vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract", poller_enabled=False,
                  last_image_path=None, weather=None)
    with TestClient(create_app(st, start_poller=False)) as c:
        store = c.app.state.store
        # 1586: arrival from Constanța, delays read 0 3 8 12 2, one never read (day 15), 5 -> median 4
        for day, d in zip(range(10, 15), [0, 3, 8, 12, 2]):
            add(store, "arrival", 1586, day, "16:40", d, station="CONSTANTA")
        add(store, "arrival", 1586, 15, "16:40", 0, state="unknown", station="CONSTANTA")
        add(store, "arrival", 1586, 16, "16:40", 5, station="CONSTANTA")
        for day, d in zip(range(10, 13), [0, 1, 20]):  # 1585: departure to Constanța
            add(store, "departure", 1585, day, "07:10", d, station="CONSTANTA")
        add(store, "arrival", 1636, 10, "09:00", 4)   # two stations seen: no route in the title
        add(store, "arrival", 1636, 11, "09:00", 6)
        add(store, "arrival", 1636, 12, "09:00", 2, station="CLUJ NAPOCA")
        add(store, "arrival", 1636, 13, "09:00", 7, state="in_progress", station="CLUJ NAPOCA")
        for day in range(10, 13):
            add(store, "arrival", 1001, day, "10:00", day - 10, station="AEROPORT H COANDA")
            add(store, "departure", 1002, day, "11:00", 0, station="AEROPORT H COANDA")
        observations.refresh_trains(store._conn, [1586, 1585, 1636, 1001, 1002])
        store._conn.commit()
        yield c


def _ssr(h):
    i = h.index('<section class="ssr"')
    return h[i:h.index("</section>", i)]


def test_train_ssr_arrival_last_five_median_and_unknown(rich):
    h = rich.get("/tren/1586").text
    assert "<title>IR 1586 Constanța – București Nord | Istoric întârzieri</title>" in h
    ssr = _ssr(h)
    assert '<h1 id="ssr-h">Trenul IR 1586 la București Nord</h1>' in ssr
    assert "Categoria: IR. Numărul: 1586." in ssr and "Sosiri în București Nord" in ssr
    assert "Plecări din" not in ssr
    assert "Ruta observată: " in ssr and 'href="/statie/CONSTANTA">Constanța</a> → București Nord' in ssr
    assert "Perioada acoperită: 2026-10-10 – 2026-10-16 (7 călătorii)." in ssr
    assert "Călătorii cu întârziere citită: 6; mediana întârzierii: 4 min." in ssr
    assert "Ultimele 5 călătorii" in ssr
    rows = re.findall(r"<tr><td>(2026-10-\d\d)</td><td>16:40</td><td>([^<]+)</td></tr>", ssr)
    assert rows == [("2026-10-16", "+5 min"), ("2026-10-15", "necunoscută"), ("2026-10-14", "+2 min"),
                    ("2026-10-13", "+12 min"), ("2026-10-12", "+8 min")]   # unknown is never 0
    assert "Trenul nu apare acum pe tabelă; ultima observație: 2026-10-16." in ssr
    desc = re.search(r'<meta name="description" content="([^"]+)">', h).group(1)
    assert "7 călătorii" in desc and "mediana 4 min din 6 întârzieri citite" in desc
    trip = _ld(h)["@graph"][-1]["mainEntity"]
    assert trip["name"] == "IR 1586" and trip["arrivalStation"]["name"] == "București Nord"
    assert trip["departureStation"]["name"] == "Constanța"


def test_train_ssr_departure_title_and_english(rich):
    h = rich.get("/tren/1585").text
    assert "<title>IR 1585 București Nord – Constanța | Istoric întârzieri</title>" in h
    assert "Plecări din București Nord" in _ssr(h) and "Sosiri în" not in _ssr(h)
    assert "mediana întârzierii: 1 min" in _ssr(h)
    en = rich.get("/tren/1585?lang=en").text
    assert "<title>IR 1585 Bucharest North – Constanța | Delay history</title>" in en
    ssr = _ssr(en)
    assert '<h1 id="ssr-h">Train IR 1585 at Bucharest North</h1>' in ssr
    assert "Departures from Bucharest North" in ssr and 'href="/statie/CONSTANTA?lang=en"' in ssr
    assert "median delay: 1 min" in ssr and "Last 3 journeys" in ssr
    assert _ld(en)["@graph"][-1]["mainEntity"]["departureStation"]["name"] == "București Nord"


def test_train_ssr_several_stations_listed_with_dates_no_route_in_title(rich):
    h = rich.get("/tren/1636").text
    assert "<title>IR 1636 la București Nord | Istoric întârzieri</title>" in h
    ssr = _ssr(h)
    assert "Stații observate pe tabelă (cu perioada):" in ssr and "Ruta observată" not in ssr
    assert 'href="/statie/CLUJ%20NAPOCA">Cluj Napoca</a>: 2026-10-12 – 2026-10-13 (2 călătorii)' in ssr
    assert 'href="/statie/BRASOV">Brașov</a>: 2026-10-10 – 2026-10-11 (2 călătorii)' in ssr
    assert "Trenul apare acum pe tabelă." in ssr and "+7 min (pe tabelă acum)" in ssr
    trip = _ld(h)["@graph"][-1]["mainEntity"]
    assert "departureStation" not in trip and "arrivalStation" not in trip
    en = rich.get("/tren/1636?lang=en").text
    assert "<title>IR 1636 at Bucharest North | Delay history</title>" in en
    assert "Stations seen on the board (with dates):" in en and "on the board now" in en


def test_station_ssr_lists_trains_with_links(rich):
    ssr = _ssr(rich.get("/statie/CONSTANTA").text)
    assert "Sosiri din Constanța" in ssr and "Plecări spre Constanța" in ssr
    assert '<a href="/tren/1586">IR 1586</a>' in ssr and '<a href="/tren/1585">IR 1585</a>' in ssr
    assert "nu la stația Constanța" in ssr
    en = _ssr(rich.get("/statie/CONSTANTA?lang=en").text)
    assert '<a href="/tren/1586?lang=en">IR 1586</a>' in en and "Arrivals from Constanța" in en


def test_airport_station_says_otopeni(rich):
    h = rich.get("/statie/AEROPORT%20H%20COANDA").text
    assert "<title>Gara de Nord – Aeroport Otopeni: orele trenurilor și întârzieri</title>" in h
    assert "Otopeni" in re.search(r'<meta name="description" content="([^"]+)">', h).group(1)
    ssr = _ssr(h)
    assert "Sosiri din Aeroportul Otopeni (Henri Coandă)" in ssr and "Plecări spre Aeroportul Otopeni" in ssr
    assert 'href="/tren/1001"' in ssr and 'href="/tren/1002"' in ssr
    en = rich.get("/statie/AEROPORT%20H%20COANDA?lang=en").text
    assert "<title>Bucharest North to Otopeni Airport – train times and delays</title>" in en
    assert "Arrivals from Otopeni Airport" in en
    assert "Otopeni" in _ld(en)["@graph"][-1]["mainEntity"]["alternateName"]


def test_statistici_ssr_figures_period_and_sample_without_airport(rich):
    api = rich.get("/api/stats/overview").json()   # same defaults as the page: airport out
    ssr = _ssr(rich.get("/statistici").text)
    cov = api["coverage"]
    assert cov["journeys"] == 14   # 1586 (7) + 1585 (3) + 1636 (4); airport trains left out
    assert f"Perioada: {cov['first']} – {cov['last']}" in ssr and "N = 14 călătorii" in ssr
    assert "Fără trenurile de aeroport (Otopeni)" in ssr and "cel mult 5 minute" in ssr
    med = seo._mins(api["boards"]["arrival"]["median"], seo.T["ro"], "ro")
    assert f"<td>Sosiri</td><td>{api['boards']['arrival']['n']}</td><td>{med}</td>" in ssr
    assert "Mediana" in ssr and "La timp (≤ 5 min)" in ssr
    en = _ssr(rich.get("/statistici?lang=en").text)
    assert "Sample: N = 14 journeys" in en and "Airport trains (Otopeni) left out" in en


def test_clasamente_ssr_threshold_sample_and_first_rows(rich):
    api = rich.get("/api/stats/rankings?limit=5").json()
    ssr = _ssr(rich.get("/clasamente").text)
    assert "un tren e „la timp” când întârzierea citită este de cel mult 5 minute" in ssr
    assert "N = 20 de călătorii" in ssr   # every journey kept, airport trains included
    assert "Perioada: 2026-10-10 – 2026-10-16" in ssr
    assert api["eligible"] == 1 and api["most_delayed"][0]["train_no"] == 1586
    assert "Cele mai întârziate" in ssr and '<a href="/tren/1586">IR 1586</a>' in ssr
    en = _ssr(rich.get("/clasamente?lang=en").text)
    assert "at most 5 minutes" in en and "Most punctual" in en


def test_insufficient_data_is_said_not_zero(client):
    # the seed has only journeys still on the board: nothing finished, no delay counted yet
    ssr = _ssr(client.get("/clasamente").text)
    assert "Date insuficiente" in ssr
    ssr = _ssr(client.get("/tren/1636").text)
    assert "Călătorii cu întârziere citită: 0 — date insuficiente pentru mediană." in ssr


def test_home_ssr_both_boards_capture_time_delay_and_platform(client):
    h = client.get("/").text
    assert "<title>Gara de Nord București – sosiri și plecări live</title>" in h
    assert ('<meta name="description" content="Vezi trenurile afișate acum în Gara de Nord București, cu ora '
            'programată, întârzierea citită și linia anunțată. Verifică ora ultimei actualizări.">') in h
    ssr = _ssr(h)
    assert "<h2>Plecări</h2>" in ssr and "<h2>Sosiri</h2>" in ssr
    assert re.search(r"Ultima actualizare \(ora capturii tabelei\): \d{4}-\d\d-\d\d \d\d:\d\d", ssr)
    assert '<th scope="col">Întârziere citită</th><th scope="col">Linia anunțată</th>' in ssr
    en = client.get("/?lang=en").text
    assert "<title>Bucharest North (Gara de Nord) – live arrivals and departures</title>" in en
    assert 'href="/tren/1636?lang=en"' in _ssr(en) and "Announced platform" in _ssr(en)


@pytest.mark.parametrize("lang", ["ro", "en"])
def test_cum_ssr_has_methodology(client, lang):
    s = seo.i18n(lang)
    ssr = _ssr(client.get("/cum" + ("?lang=en" if lang == "en" else "")).text)
    assert f"<h2>{seo.esc(s['cum.method.title'])}</h2>" in ssr
    for i in range(1, 7):
        assert seo.esc(s[f"cum.method.p{i}"]) in ssr
    assert "86" in s["cum.method.p3"] and "206" in s["cum.method.p3"]
    assert 'href="https://github.com/Andy217Ace/tabela-gara-de-nord/issues"' in ssr
    assert seo.esc(s["cum.privacy.title"]) in ssr


def test_cum_sections_match_the_app():
    js = (ROOT / "web" / "cum.js").read_text(encoding="utf-8")
    sections = re.search(r"var SECTIONS = (\[.*\]);", js).group(1)
    assert json.loads(sections) == [list(x) for x in seo.CUM_SECTIONS]
    ro, en = seo.i18n("ro"), seo.i18n("en")
    for key, n in seo.CUM_SECTIONS:
        for k in [f"cum.{key}.title"] + [f"cum.{key}.p{i}" for i in range(1, n + 1)]:
            assert k in ro and k in en, k
