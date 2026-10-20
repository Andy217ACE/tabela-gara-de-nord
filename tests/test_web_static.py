# © 2026 Andy217Ace
"""Static frontend: served by the app, CSP-compatible, attribution present."""
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
    assert re.search(r'<img [^>]*id="logo"[^>]*src="icons/logo.svg"', html)
    assert 'alt="Sigla Tabela Gara de Nord"' in html
    for tag in ("<header", "<main", "<nav", "<footer"):
        assert tag in html
    assert 'aria-live="polite"' in html
    assert re.search(r"Sursa: (?:<a [^>]*>)?CFR", html)
    for name in ("Sosiri", "Plecări", "Tabelă", "Istoric", "Urmărite"):
        assert name in html
    assert client.get("/icons/logo.svg").status_code == 200
    assert client.get("/icons/icon.svg").status_code == 200


def test_static_files_revalidate(client):
    for path in ("/", "/style.css", "/app.js", "/icons/logo.svg"):
        assert client.get(path).headers.get("cache-control") == "no-cache", path


def test_index_is_csp_compatible():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<style\b", html, re.I)
    assert not re.search(r"\sstyle\s*=", html, re.I)
    assert not re.search(r"\son[a-z]+\s*=", html, re.I)  # inline handlers
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.I | re.S):
        assert "src=" in m.group(1) and m.group(2).strip() == ""
    # fonts only from Google Fonts, scripts/styles same-origin
    for m in re.finditer(r'(?:href|src)="(https?://[^"]+)"', html):
        url = m.group(1)
        assert url.startswith(("https://fonts.googleapis.com", "https://fonts.gstatic.com",
                               "https://cfr.ro")), url


def test_manifest_only_linked_when_present():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    if not (WEB / "manifest.webmanifest").exists():
        assert "manifest.webmanifest" not in html


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
