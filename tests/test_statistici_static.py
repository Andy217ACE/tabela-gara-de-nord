# © 2026 Andy217Ace
"""Static checks for Statistici v2 (web/statistici.js, web/statistici.css): served,
CSP-safe, one aggregated endpoint, explanatory copy, theme tokens only, wired into the
index and the service-worker shell; the old view is gone from stats.js."""
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


def test_statistici_js_served_and_csp_safe(client):
    r = client.get("/statistici.js")
    assert r.status_code == 200
    js = r.text
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", 'setAttribute("style"', "cssText", '"style"'):
        assert bad not in js, bad
    assert "createElementNS" in js and "textContent" in js


def test_statistici_js_content_and_rules():
    js = (WEB / "statistici.js").read_text(encoding="utf-8")
    for needle in ("/api/stats/overview", "App.views.statistici", "history.replaceState",
                   "perioada", "operator", "tip", "doar_confirmate", 'set: set', 'format: "csv"',
                   "Cum se citește", "Vezi datele", "Date insuficiente încă", "Pe scurt",
                   "Glosar", "în curs de adunare", "w.note", "sufficient",
                   "N = ", "eșantion mic", "linie necitită", "prefers-reduced-motion",
                   "aria-labelledby", "caption", "scope"):
        assert needle in js, needle
    # a missing value is „—”, never 0
    assert 'v == null ? "—"' in js
    # one request per state: the page never calls the older endpoints
    for old in ("/api/stats?", "/api/stats/rankings", "/api/trains/stats"):
        assert old not in js, old


def test_statistici_css_tokens_only(client):
    r = client.get("/statistici.css")
    assert r.status_code == 200
    css = r.text
    assert css.startswith("/* © 2026 Andy217Ace */")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)  # theme tokens only
    for tok in ("var(--c-arr)", "var(--c-dep)", "var(--c-seq)", "var(--surface)", "var(--accent)"):
        assert tok in css, tok
    assert "@import" not in css and "url(" not in css
    assert "prefers-reduced-motion" in css


def test_series_tokens_in_every_theme_block():
    css = (WEB / "style.css").read_text(encoding="utf-8")
    for tok in ("--c-arr:", "--c-dep:", "--c-seq:"):
        assert css.count(tok) >= 3, tok  # dark default, light (media), [data-theme=light]


def test_index_and_sw_wiring():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="statistici.css">' in html
    assert '<script src="statistici.js" defer></script>' in html
    assert html.index('src="stats.js"') < html.index('src="statistici.js"')
    assert 'id="st-statistici"' in html and html.count("<footer") == 1
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    shell = sw[sw.index("var SHELL"):sw.index("];", sw.index("var SHELL"))]
    assert '"/statistici.js"' in shell and '"/statistici.css"' in shell
    assert int(re.search(r'var VERSION = "v(\d+)"', sw).group(1)) >= 17


def test_old_statistici_view_removed_from_stats_js():
    js = (WEB / "stats.js").read_text(encoding="utf-8")
    assert "renderStatistici" not in js and "App.views.statistici" not in js
    for helper in ("getJSON", "errorText", "stationLink", "plural", "titleCase", "dayText"):
        assert re.search(rf"App\.stats = \{{[^}}]*\b{helper}\b", js), helper
