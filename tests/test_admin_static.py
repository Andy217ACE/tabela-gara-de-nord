# © 2026 Andy217Ace
"""Static checks for the hidden „Administrare" view (#admin): routing, nav, safety, contract."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


@pytest.fixture
def client():
    s = Settings(db_path=":memory:", source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract")
    with TestClient(create_app(s, start_poller=False)) as c:
        yield c


def test_admin_js_served_and_safe(client):
    r = client.get("/admin.js")
    assert r.status_code == 200
    js = r.text
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", "setAttribute(\"style\"", "cssText",
                "localStorage", "sessionStorage"):
        assert bad not in js, bad
    assert "credentials" in js
    assert "window.TabelaApp.views.admin" in js
    assert "Administrare" in js


def test_admin_css_served_and_themed(client):
    r = client.get("/admin.css")
    assert r.status_code == 200
    css = r.text
    assert css.startswith("/* © 2026 Andy217Ace */")
    assert "var(--surface)" in css and "var(--bad)" in css  # theme tokens, no fixed palette
    assert "@import" not in css and "url(" not in css


def test_admin_endpoints_match_contract():
    js = (WEB / "admin.js").read_text(encoding="utf-8")
    for path in ("/api/admin/session", "/api/admin/login", "/api/admin/csrf",
                 "/api/admin/tools/dupes", "/api/admin/tools/dupes/apply",
                 "/api/admin/tools/dupes/restore", "/api/admin/tools/server"):
        assert f'"{path}"' in js, path
    assert '"X-CSRF-Token"' in js
    assert '"APLICA"' in js and '"RESTAUREAZA"' in js
    assert "confirm(" not in js  # confirmation is typed in a field, not a browser dialog
    for key in ("generated_at", "load", "memory", "disk", "uptime_s", "process", "services",
                "watchdog"):
        assert key in js, key


def test_admin_server_card_polls_only_while_shown():
    js = (WEB / "admin.js").read_text(encoding="utf-8")
    assert "REFRESH_MS = 10000" in js
    assert 'location.hash === "#admin"' in js and "document.hidden" in js
    assert 'addEventListener("hashchange", syncTimer)' in js
    assert "clearInterval(serverTimer)" in js


def test_admin_route_registered_and_lazy():
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert '"#admin": "admin"' in app
    assert '"ocr", "admin", "versiuni"' in app  # in VIEWS
    assert 'admin: "Administrare"' in app
    assert 'if (name === "admin") loadAdminView();' in app
    assert 's.src = "admin.js"' in app and 'css.href = "admin.css"' in app
    assert 'if (currentRoute === "admin") route();' in app


def test_admin_not_in_public_nav_or_precache():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "admin.js" not in html and "admin.css" not in html and "#admin" not in html
    nav = html[html.index('<nav class="mainnav"'):]
    nav = nav[:nav.index("</nav>")]
    assert "admin" not in nav.lower()
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    shell = sw[sw.index("var SHELL"):sw.index("];", sw.index("var SHELL"))]
    assert "admin" not in shell
