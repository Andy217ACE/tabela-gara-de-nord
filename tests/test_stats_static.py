# © 2026 Andy217Ace
"""Static checks for the Trenuri / Tren / Statistici / Clasamente views (web/stats.js,
web/stats.css): served, CSP-safe, wired into routes, nav, index and the SW shell."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings

WEB = Path(__file__).resolve().parent.parent / "web"


@pytest.fixture
def client():
    s = Settings(db_path=":memory:", source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract")
    with TestClient(create_app(s, start_poller=False)) as c:
        yield c


def test_stats_js_served_and_safe(client):
    r = client.get("/stats.js")
    assert r.status_code == 200
    js = r.text
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", 'setAttribute("style"', "cssText"):
        assert bad not in js, bad
    assert "createElementNS" in js and "textContent" in js


def test_stats_js_uses_api_and_rules():
    js = (WEB / "stats.js").read_text(encoding="utf-8")
    for needle in ("/api/trains/stats", "/api/trains/", "/journeys", "/api/stats",
                   "/api/stats/rankings", '"format", "csv"', "doar_confirmate", "prag",
                   "App.views.trenuri", "App.views.tren", "App.views.statistici",
                   "App.views.clasamente", "openJourney", "station-link", "#statie?nume=",
                   "encodeURIComponent(name)", "#tren?nr=",
                   "Eșantion mic (N = ", "procentele nu sunt afișate",
                   "Încă nu există trenuri cu cel puțin", "below_min",
                   "Beta 1.04", "București Nord", "sufficient === false", "history.replaceState"):
        assert needle in js, needle
    # a missing value is „—”, never 0
    assert 'v == null ? "—"' in js


def test_stats_css_served_and_themed(client):
    r = client.get("/stats.css")
    assert r.status_code == 200
    css = r.text
    assert css.startswith("/* © 2026 Andy217Ace */")
    assert "var(--surface)" in css and "var(--warn)" in css and "var(--accent)" in css
    assert "@import" not in css and "url(" not in css
    assert re.search(r"\.st-scroll\s*\{[^}]*overflow-x:\s*auto", css)
    assert re.search(r"\.st-chart-scroll\s*\{[^}]*overflow-x:\s*auto", css)
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", css)  # theme tokens only, no fixed palette


def test_index_has_stats_views_nav_and_assets():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<script src="stats.js" defer></script>' in html
    assert '<link rel="stylesheet" href="stats.css">' in html
    for v in ("trenuri", "tren", "statistici", "clasamente"):
        assert f'id="view-{v}"' in html, v
    for route, label in (("trenuri", "Trenuri"), ("statistici", "Statistici"),
                         ("clasamente", "Clasamente")):
        assert re.search(rf'<a class="nav-item" href="#{route}" data-route="{route}">\s*<svg class="nav-icon"',
                         html), route
        assert f"<span>{label}</span>" in html
    assert 'id="rank-stations"' in html
    assert html.count("<footer") == 1


def test_app_routes_for_stats_views():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    for needle in ('"#trenuri": "trenuri"', '"#tren": "tren"', '"#statistici": "statistici"',
                   '"#clasamente": "clasamente"', 'tren: "trenuri"', 'statistici: "Statistici"',
                   'clasamente: "Clasamente"'):
        assert needle in js, needle


def test_sw_precaches_stats_and_bumped():
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    m = re.search(r'var VERSION = "v(\d+)"', sw)
    assert m and int(m.group(1)) >= 9
    shell = sw[sw.index("var SHELL"):sw.index("];", sw.index("var SHELL"))]
    assert '"/stats.js"' in shell and '"/stats.css"' in shell


def test_mobile_nav_scrolls_inside_not_page():
    css = (WEB / "style.css").read_text(encoding="utf-8")
    nav = re.search(r"\n\.mainnav \{(.*?)\n\}", css, re.S).group(1)
    assert "overflow-x: auto" in nav and "display: flex" in nav


# ---- D2: station pages (#statii, #statie?nume=), station links, station ranking ----------

def test_station_views_wired():
    js = (WEB / "stats.js").read_text(encoding="utf-8")
    for needle in ("App.views.statii", "App.views.statie", "/api/stations", "/journeys?",
                   "next_before", '"before"', "Mai multe călătorii", "Ultimele călătorii",
                   "Sosiri dinspre stație", "Plecări înspre stație", "Stația nu a fost observată pe tabelă",
                   "#statii", "Nu intră în clasamentul stațiilor", "sub eșantionul minim",
                   "Locul ", "rank-stations", "most_punctual", "Clasamentul stațiilor",
                   "Încă nu există stații cu cel puțin", "nume nesigur", "uncertain_only",
                   "d.note", "Atenție: ", "openJourney", "timeSections"):
        assert needle in js, needle
    app = (WEB / "app.js").read_text(encoding="utf-8")
    for needle in ('"#statii": "statii"', '"#statie": "statie"', 'statii: "trenuri"',
                   'statie: "trenuri"'):
        assert needle in app, needle
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for needle in ('id="view-statii"', 'id="view-statie"', 'id="st-statii"', 'id="st-statie"',
                   'id="statie-heading"', 'id="statie-sub"', 'href="#statii"'):
        assert needle in html, needle
    assert html.count("<footer") == 1


def test_station_links_everywhere_and_safe():
    href = 'href = "#statie?nume=" + encodeURIComponent('
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert '"#statie?nume=" + encodeURIComponent(t.station)' in app
    assert "station-link station-link-plain" in app
    panel = (WEB / "panel.js").read_text(encoding="utf-8")
    assert href in panel and "station-link station-link-plain" in panel
    assert 'e.target.closest("a")' in panel          # a click on the link does not open the row detail
    hist = (WEB / "history.js").read_text(encoding="utf-8")
    assert href in hist and 'closest("button, a")' in hist
    for name, src in (("app.js", app), ("panel.js", panel), ("history.js", hist)):
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", ".style.", 'setAttribute("style"'):
            assert bad not in src, (name, bad)
    css = (WEB / "stats.css").read_text(encoding="utf-8")
    assert re.search(r"\.station-link-plain\s*\{[^}]*text-decoration:\s*none", css)
    assert re.search(r"\.station-link:focus-visible\s*\{[^}]*outline", css)


def test_sw_precache_still_complete():
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    shell = sw[sw.index("var SHELL"):sw.index("];", sw.index("var SHELL"))]
    for f in ("/app.js", "/history.js", "/panel.js", "/stats.js", "/stats.css"):
        assert f'"{f}"' in shell, f


def test_nginx_rate_limits_expensive_endpoints():
    root = WEB.parent / "deploy"
    limits = (root / "tabela-limits.conf").read_text(encoding="utf-8")
    site = (root / "nginx-tabela.conf").read_text(encoding="utf-8")
    assert re.search(r"limit_req_zone \$binary_remote_addr zone=tabela_stats:\S+ rate=60r/m;", limits)
    loc = re.search(r"location ~ \^/api/\((.*?)\)\(/\|\$\) \{(.*?)\}", site, re.S)
    assert loc and "limit_req zone=tabela_stats" in loc.group(2)
    for p in ("stats", "trains/stats", "stations", "journeys"):
        assert p in loc.group(1).split("|"), p
    assert site.index("location ~ ^/api/(stats") < site.index("location /api/ {")
