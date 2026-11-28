# © 2026 Andy217Ace
"""SEO (app/seo.py): path URLs with their own head, canonical/hreflang, JSON-LD, server-rendered
content, 404 + noindex, redirects, robots.txt and sitemap.xml."""
import html
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


@pytest.mark.parametrize("path", ["/"] + ["/" + p for p in seo.PUBLIC if p not in seo.NOINDEX])
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
    assert "<title>Trenul 1636" in h and f'href="{SITE}/tren/1636"' in h
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


def test_followed_page_is_noindex_and_not_in_sitemap(client):
    r = client.get("/urmarite")
    assert r.status_code == 200 and r.headers["x-robots-tag"] == "noindex"
    h = r.text
    assert '<meta name="robots" content="noindex">' in h
    assert 'rel="canonical"' not in h and "application/ld+json" not in h
    sm = client.get("/sitemap.xml").text
    assert "/urmarite" not in sm
    assert client.get("/api/meta", params={"path": "/urmarite"}).json()["robots"] == "noindex"


def test_sitemap_board_lastmod_is_last_capture(client):
    st = client.app.state.store
    with st._lock:
        last = st._last_ok_ts()
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(client.get("/sitemap.xml").content)
    home = next(u for u in root.findall("s:url", ns) if u.find("s:loc", ns).text == f"{SITE}/")
    mod = home.find("s:lastmod", ns)
    assert (mod.text if mod is not None else "?") == seo._day(last)


@pytest.mark.parametrize("path", ["/tren/999999", "/statie/NUEXISTA"])
def test_unknown_detail_pages_are_404_noindex(client, path):
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 404 and r.headers["x-robots-tag"] == "noindex"
    assert '<meta name="robots" content="noindex">' in r.text and 'rel="canonical"' not in r.text
    m = client.get("/api/meta", params={"path": path}).json()
    assert m["status"] == 404 and m["robots"] == "noindex" and m["canonical"] is None and m["jsonld"] is None


def _head(h):
    """The head values the SPA keeps in sync, read from a server-rendered page."""
    def one(pat):
        m = re.search(pat, h)
        return html.unescape(m.group(1)) if m else None
    alts = {c: html.unescape(u) for c, u in re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">', h)}
    ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', h, re.S)
    return {"title": one(r"<title>([^<]*)</title>"), "description": one(r'<meta name="description" content="([^"]*)">'),
            "url": one(r'<meta property="og:url" content="([^"]*)">'),
            "canonical": one(r'<link rel="canonical" href="([^"]*)">'), "alternates": alts or None,
            "robots": one(r'<meta name="robots" content="([^"]*)">'),
            "jsonld": json.loads(ld.group(1)) if ld else None}


@pytest.mark.parametrize("path", ["/", "/statistici", "/urmarite", "/tren/1636", "/statie/BRASOV", "/tren/999999",
                                  "/statie/NUEXISTA", "/nu-exista"])
@pytest.mark.parametrize("lang", ["ro", "en"])
def test_api_meta_equals_the_rendered_head(client, path, lang):
    """/api/meta (what app.js applies after an in-app navigation) = the head of a direct visit."""
    page = client.get(path + ("?lang=en" if lang == "en" else ""), follow_redirects=False)
    m = client.get("/api/meta", params={"path": path, "lang": lang}).json()
    assert m["status"] == page.status_code
    assert {k: m[k] for k in _head("")} == _head(page.text)
