# © 2026 Andy217Ace
"""Static frontend: served by the app, CSP-compatible, attribution present."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings

WEB = Path(__file__).resolve().parent.parent / "web"


@pytest.fixture
def client():
    s = Settings(db_path=":memory:", source_url="https://example.com/x",
                 vapid_private_key="", vapid_public_key="", vapid_subject="mailto:a@b.c",
                 tesseract_cmd="tesseract")
    with TestClient(create_app(s, start_poller=False)) as c:
        yield c


def test_index_has_title_meta_and_footer(client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.text
    assert "<title>Tabela Gara de Nord</title>" in html
    assert '<html lang="ro">' in html
    assert '<meta name="author" content="Andy217Ace">' in html
    assert re.search(r'<meta name="description" content="[^"]+">', html)
    assert re.search(r'<meta name="theme-color"', html)
    footer = re.search(r"<footer\b.*?</footer>", html, re.S).group(0)
    assert "© 2026 Andy217Ace" in footer
    assert "Date preluate de la CFR" in footer
    assert "neafiliat CFR" in footer
    link = re.search(r'<a [^>]*href="https://cfr.ro"[^>]*>', footer).group(0)
    assert 'rel="noopener noreferrer"' in link
    assert 'target="_blank"' in link


def test_index_has_logo_slot_and_landmarks(client):
    html = client.get("/").text
    assert re.search(r'<img [^>]*id="logo"[^>]*src="icons/logo-96.png"', html)
    assert 'alt="Sigla Tabela Gara de Nord"' in html
    for tag in ("<header", "<main", "<nav", "<footer"):
        assert tag in html
    assert 'aria-live="polite"' in html
    assert re.search(r"Sursa: (?:<a [^>]*>)?CFR", html)
    for name in ("Sosiri", "Plecări", "Tabelă", "Istoric", "Urmărite"):
        assert name in html
    assert client.get("/icons/icon-192.png").status_code == 200


def test_static_files_revalidate(client):
    for path in ("/", "/style.css", "/app.js", "/icons/icon-192.png"):
        assert client.get(path).headers.get("cache-control") == "no-cache", path


def test_index_is_csp_compatible():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<style\b", html, re.I)
    assert not re.search(r"\sstyle\s*=", html, re.I)
    assert not re.search(r"\son[a-z]+\s*=", html, re.I)  # inline handlers
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.I | re.S):
        assert "src=" in m.group(1) and m.group(2).strip() == ""
    # no external fonts; scripts/styles same-origin
    for m in re.finditer(r'(?:href|src)="(https?://[^"]+)"', html):
        url = m.group(1)
        assert url.startswith(("https://cfr.ro", "https://open-meteo.com/")), url


def test_no_external_font_hosts():
    for pattern in ("*.html", "*.css", "*.js"):
        for f in WEB.glob(pattern):
            txt = f.read_text(encoding="utf-8")
            assert "fonts.googleapis.com" not in txt, f.name
            assert "fonts.gstatic.com" not in txt, f.name


FOOTER = ('<p>© 2026 Andy217Ace · Date preluate de la CFR (cfr.ro)'
          ' — proiect independent, neafiliat CFR. Tabela oficială: <a href="https://cfr.ro"'
          ' target="_blank" rel="noopener noreferrer">cfr.ro</a></p>\n')


def test_footer_unchanged():
    """The attribution line is byte-for-byte unchanged; the logo mark sits before it and
    the separate Open-Meteo span after it (tests/test_weather_static.py)."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert FOOTER in html
    footer = re.search(r'<footer class="footer">(.*?)</footer>', html, re.S).group(1)
    assert re.search(r'<img class="logo logo-footer" src="icons/favicon-16.png"', footer)


def test_manifest_valid_and_linked(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    m = json.loads(r.text)
    assert m["name"] == "Tabela Gara de Nord"
    assert m["short_name"] == "Gara de Nord"
    assert m["start_url"] == "/" and m["scope"] == "/"
    assert m["display"] == "standalone"
    assert m["lang"] == "ro"
    assert "© 2026 Andy217Ace" in m["description"]
    assert re.match(r"^#[0-9a-f]{6}$", m["theme_color"])
    assert re.match(r"^#[0-9a-f]{6}$", m["background_color"])
    icons = {(i["src"], i["type"], i["sizes"], i.get("purpose", "any")) for i in m["icons"]}
    # the logo artwork everywhere: no leftover placeholder SVG
    assert not any(t == "image/svg+xml" for _, t, _, _ in icons)
    assert ("icons/icon-192.png", "image/png", "192x192", "any") in icons
    assert ("icons/icon-512.png", "image/png", "512x512", "any") in icons
    assert ("icons/icon-maskable-512.png", "image/png", "512x512", "maskable") in icons
    for src, typ, sizes, _ in icons:
        path = WEB / src
        assert path.is_file(), src
        if typ == "image/png":
            from PIL import Image
            with Image.open(path) as im:
                assert f"{im.width}x{im.height}" == sizes, src
        assert client.get("/" + src).status_code == 200
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<link rel="manifest" href="manifest.webmanifest">' in html
    assert '<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">' in html
    assert '<link rel="icon" href="icons/favicon-32.png" sizes="32x32" type="image/png">' in html
    assert '<link rel="icon" href="icons/favicon-16.png" sizes="16x16" type="image/png">' in html
    assert '<link rel="icon" href="favicon.ico" sizes="48x48">' in html
    assert '<link rel="icon" href="icons/icon-192.png" sizes="192x192" type="image/png">' in html
    assert ".svg" not in html
    from PIL import Image
    with Image.open(WEB / "icons" / "apple-touch-icon.png") as im:
        assert im.size == (180, 180) and im.mode == "RGB"  # iOS: no transparency
    with Image.open(WEB / "icons" / "favicon-32.png") as im:
        assert im.size == (32, 32)
    r = client.get("/favicon.ico")
    assert r.status_code == 200 and r.content[:4] == b"\x00\x00\x01\x00"


def test_service_worker_served_as_js_no_cache(client):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["content-type"].split(";")[0].strip() == "text/javascript"
    assert r.headers["cache-control"] == "no-cache"
    assert "worker-src 'self'" in r.headers["content-security-policy"]
    h = client.head("/sw.js")
    assert h.headers["content-type"].split(";")[0].strip() == "text/javascript"
    js = r.text
    assert js.startswith("// © 2026 Andy217Ace")
    for needle in ('addEventListener("install"', 'addEventListener("activate"',
                   'addEventListener("fetch"', 'addEventListener("push"',
                   'addEventListener("notificationclick"', "/api/board", "caches.delete",
                   "Gara de Nord", "skipWaiting", "clients.claim"):
        assert needle in js, needle
    m = re.search(r'var VERSION = "([^"]+)"', js)
    assert m, "versioned cache name"
    # every precached file exists
    shell = re.search(r"var SHELL = \[(.*?)\];", js, re.S).group(1)
    for path in re.findall(r'"([^"]+)"', shell):
        assert client.get(path).status_code == 200, path
    for f in ("history.js", "follows.js", "app.js", "style.css", "manifest.webmanifest",
              "icons/icon-192.png", "icons/favicon-32.png", "icons/apple-touch-icon.png",
              "favicon.ico", "panel.js", "panel.css", "theme-init.js", "icons/logo-96.png",
              "icons/favicon-16.png"):
        assert f'"/{f}"' in shell, f
    assert 'OFFLINE_URL = "/offline.html"' in js and "OFFLINE_URL," in shell
    # every same-origin static file referenced by index.html is precached
    html = (WEB / "index.html").read_text(encoding="utf-8")
    refs = set(re.findall(r'(?:src|href)="((?!https?:|#)[^"]+)"', html))
    refs |= {u.split()[0] for m in re.findall(r'srcset="([^"]+)"', html) for u in m.split(",")}
    precached = set(re.findall(r'"([^"]+)"', shell)) | {"/offline.html"}
    for ref in refs:
        assert "/" + ref.lstrip("/") in precached, ref


@pytest.mark.parametrize("name", ["app.js", "history.js", "follows.js", "sw.js", "panel.js",
                                  "theme-init.js"])
def test_js_files_safe_dom(client, name):
    r = client.get("/" + name)
    assert r.status_code == 200
    js = r.text
    assert js.startswith("// © 2026 Andy217Ace"), name
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", "setAttribute(\"style\""):
        assert bad not in js, (name, bad)


def test_index_loads_split_scripts_and_real_views():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    for src in ("app.js", "history.js", "follows.js"):
        assert re.search(rf'<script src="{src}" defer></script>', html), src
    assert "În curând" not in html
    assert 'id="view-istoric"' in html and 'id="view-urmarite"' in html
    assert 'id="h-date"' in html and 'id="h-results"' in html
    assert 'id="f-list"' in html and 'id="f-switch"' in html


def test_history_js_uses_api():
    js = (WEB / "history.js").read_text(encoding="utf-8")
    for needle in ("/api/history", "Europe/Bucharest", "createElementNS",
                   "rezultat", "AbortController"):
        assert needle in js, needle


def test_history_js_journey_result():
    """C3: the detail dialog shows the final result of /api/journeys/{id}, the service
    date, a chart from the real readings, and the list never says „la timp” unread."""
    js = (WEB / "history.js").read_text(encoding="utf-8")
    for needle in ('"/api/journeys/"', "delay_series", "disappeared_at", "estimated_at",
                   "Data de serviciu", "zilei următoare", "București Nord", "chart-gone",
                   "j.max_read_delay != null", '"necitit"', '"#tren?nr="', "openJourney",
                   "final_delay", "document.body.appendChild(dlg)"):
        assert needle in js, needle
    css = (WEB / "style.css").read_text(encoding="utf-8")
    for cls in (".res-confirmed", ".res-unconfirmed", ".res-unknown", ".res-progress", ".chart-gone"):
        assert cls in css, cls


def test_follows_js_uses_api():
    js = (WEB / "follows.js").read_text(encoding="utf-8")
    for needle in ("/api/push/key", "/api/push/subscribe", "/api/push/unsubscribe",
                   "/api/follow", "/api/follows", "urlBase64ToUint8Array", "onFollow",
                   "Notificările necesită conexiune sigură (HTTPS) și un browser compatibil.",
                   "Pe iPhone, adaugă mai întâi aplicația pe ecranul principal."):
        assert needle in js, needle


def test_style_defines_theme_variables(client):
    r = client.get("/style.css")
    assert r.status_code == 200
    css = r.text
    assert css.startswith("/* © 2026 Andy217Ace */")
    assert "prefers-color-scheme: light" in css
    assert re.search(r":root\s*\{[^}]*--bg:", css)  # dark default
    assert re.search(r"prefers-color-scheme: light\)\s*\{\s*:root[^{]*\{[^}]*--bg:", css)
    assert '[data-theme="dark"]' in css and '[data-theme="light"]' in css
    assert "prefers-reduced-motion" in css
    assert "tabular-nums" in css
    assert ":focus-visible" in css


@pytest.mark.parametrize("val,expected", [(None, True), ("1", True), ("0", False),
                                          ("false", False), ("off", False)])
def test_poller_enabled_env(monkeypatch, val, expected):
    from app.config import get_settings
    if val is None:
        monkeypatch.delenv("POLLER_ENABLED", raising=False)
    else:
        monkeypatch.setenv("POLLER_ENABLED", val)
    assert get_settings().poller_enabled is expected


def test_app_js_safe_dom(client):
    r = client.get("/app.js")
    assert r.status_code == 200
    js = r.text
    assert js.startswith("// © 2026 Andy217Ace")
    assert "innerHTML" not in js
    assert "outerHTML" not in js
    assert "insertAdjacentHTML" not in js
    assert "document.write" not in js
    assert "eval(" not in js
    assert "textContent" in js
    assert "/api/board" in js
    assert "AbortController" in js


@pytest.mark.parametrize("val,expected", [(None, "data/last.jpg"),
                                          ("/var/lib/tabela/last.jpg", "/var/lib/tabela/last.jpg"),
                                          ("", None)])
def test_last_image_path_env(monkeypatch, val, expected):
    from app.config import get_settings
    if val is None:
        monkeypatch.delenv("LAST_IMAGE_PATH", raising=False)
    else:
        monkeypatch.setenv("LAST_IMAGE_PATH", val)
    assert get_settings().last_image_path == expected


def test_app_js_quality_fixes():
    js = (WEB / "app.js").read_text(encoding="utf-8")
    # superseded (aborted by visibilitychange) request must not flag offline
    assert "state.inflight !== ctrl" in js
    # train key includes the service date
    assert re.search(r"function trainKey\(t\)\s*\{[^}]*service_date", js)
    # first-fetch failure replaces the skeleton and drops aria-busy
    assert "function showLoadFailure" in js
    # '*' flag has screen-reader text
    assert "marcat cu asterisc pe tabela CFR" in js
    assert "sr-only" in js


def test_follows_list_never_shows_la_timp_for_unread_delay():
    js = (WEB / "follows.js").read_text(encoding="utf-8")
    assert "t.delay_read !== true" in js
    assert 'el("span", "delay-unread", "necitit")' in js
    assert '" · la timp"' not in js
