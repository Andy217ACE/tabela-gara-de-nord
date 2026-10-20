# © 2026 Andy217Ace
"""Mod „Panou": static files wired in, CSP-safe, and the read-only /api/config."""
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


def test_index_links_panel_files_and_mount():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert re.search(r'<link rel="stylesheet" href="panel.css">', html)
    assert re.search(r'<script src="panel.js" defer></script>', html)
    assert 'id="panel-root"' in html
    # still CSP-compatible after the edit
    assert not re.search(r"<style\b", html, re.I)
    assert not re.search(r"\sstyle\s*=", html, re.I)
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.I | re.S):
        assert "src=" in m.group(1) and m.group(2).strip() == ""


def test_panel_files_served_with_header(client):
    js = client.get("/panel.js")
    css = client.get("/panel.css")
    assert js.status_code == 200 and css.status_code == 200
    assert js.headers.get("cache-control") == "no-cache"
    assert js.text.startswith("// © 2026 Andy217Ace")
    assert css.text.startswith("/* © 2026 Andy217Ace */")


def test_panel_js_safe_dom():
    js = (WEB / "panel.js").read_text(encoding="utf-8")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", "setAttribute(\"style\""):
        assert bad not in js, bad
    assert "textContent" in js
    # /api/config is fetched once by app.js (single source of truth); the panel reuses it
    assert "TabelaApp.config" in js or "App.config" in js
    assert 'fetch("/api/config"' not in js
    assert "#istoric?train=" in js
    assert "SOSIRI — GARA DE NORD BUCUREȘTI" in js
    assert "PLECĂRI — GARA DE NORD BUCUREȘTI" in js
    assert "necunoscut" in js
    assert "Favorite (local)" in js
    assert "requestFullscreen" in js
    # never colour "la timp" without a read delay: the level function guards null
    assert "delay_min == null" in js


def test_panel_css_theme_and_levels():
    css = (WEB / "panel.css").read_text(encoding="utf-8")
    assert "prefers-color-scheme: light" in css
    assert '[data-theme="light"]' in css and '[data-theme="dark"]' in css
    for lvl in ("ok", "low", "mid", "high", "unknown"):
        assert f'[data-level="{lvl}"]' in css, lvl
    assert "prefers-reduced-motion" in css
    assert "tabular-nums" in css


def test_api_config_defaults(client, monkeypatch):
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert body == {"delay_thresholds": {"low": 5, "mid": 15, "high": 30},
                    "stale_after_s": 180, "refresh_s": 10}


def test_api_config_env_override(monkeypatch):
    from app.api import panel_config
    monkeypatch.setenv("DELAY_THRESHOLDS", "3,10,45")
    assert panel_config()["delay_thresholds"] == {"low": 3, "mid": 10, "high": 45}
    for bad in ("10,5,30", "a,b,c", "1,2", "0,5,10", "-1,5,10"):
        monkeypatch.setenv("DELAY_THRESHOLDS", bad)
        assert panel_config()["delay_thresholds"] == {"low": 5, "mid": 15, "high": 30}, bad


def test_api_config_read_only(client):
    assert client.post("/api/config").status_code == 405
