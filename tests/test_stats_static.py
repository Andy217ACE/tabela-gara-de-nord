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
                   "Beta 1.03", "București Nord", "sufficient === false", "history.replaceState"):
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
    assert 'var VERSION = "v8"' in sw
    shell = sw[sw.index("var SHELL"):sw.index("];", sw.index("var SHELL"))]
    assert '"/stats.js"' in shell and '"/stats.css"' in shell


def test_mobile_nav_scrolls_inside_not_page():
    css = (WEB / "style.css").read_text(encoding="utf-8")
    nav = re.search(r"\n\.mainnav \{(.*?)\n\}", css, re.S).group(1)
    assert "overflow-x: auto" in nav and "display: flex" in nav
