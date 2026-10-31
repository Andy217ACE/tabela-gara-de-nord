# © 2026 Andy217Ace
"""Pagina „Sistem” (web/sistem.js, web/sistem.css): static rules (CSP, „necunoscut” for
missing values) and a real-browser check at 390 px (no horizontal scroll). The browser
part is skipped when Playwright or its Chromium is unavailable."""
import re
import socket
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import system_api
from app.store import Store

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "web" / "sistem.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "sistem.css").read_text(encoding="utf-8")


def test_no_html_injection_or_inline_style_in_page():
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                ".style.", "setAttribute(\"style\""):
        assert bad not in JS, bad
    assert "style=" not in CSS


def test_only_the_status_endpoints_are_read():
    urls = set(re.findall(r'"(/api/[^"]+)"', JS))
    assert urls == {"/api/system", "/api/admin/system"}


def test_missing_values_are_necunoscut_not_zero():
    # every displayed value goes through num() or ago(), which turn null into "necunoscut"
    assert 'v == null ? "necunoscut"' in JS
    assert 'if (s == null) return "necunoscut"' in JS
    assert 'o.unread_rate_1h == null' in JS


def test_states_have_their_romanian_labels():
    for label in ("LIVE", "Date vechi", "Necunoscut"):
        assert label in JS


sync_api = pytest.importorskip("playwright.sync_api")

import uvicorn  # noqa: E402

TZ = ZoneInfo("Europe/Bucharest")
PAGE = """<!doctype html><html lang="ro"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/web/sistem.css"></head>
<body><main id="main" tabindex="-1"></main>
<script src="/web/sistem.js"></script></body></html>"""


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("sistem")
    db = tmp / "t.db"
    store = Store(str(db))
    store.migrate()
    store._conn.execute("INSERT INTO runs(ts, image_hash, ok, n_rows) VALUES (?,'',1,12)",
                        ((datetime.now(TZ) - timedelta(seconds=20)).isoformat(),))
    app = FastAPI()
    app.include_router(system_api.router)
    app.state.store = store
    app.state.settings = SimpleNamespace(db_path=str(db))
    (tmp / "index.html").write_text(PAGE, encoding="utf-8")
    app.mount("/web", StaticFiles(directory=str(ROOT / "web")), name="web")
    app.mount("/", StaticFiles(directory=str(tmp), html=True), name="page")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)
    store.close()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # Chromium not installed here
            pytest.skip(f"Chromium unavailable: {e}")
        yield b
        b.close()


def test_sistem_page_at_390px_live_and_no_horizontal_scroll(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 800})
    try:
        page.goto(base_url + "/")
        page.wait_for_function("() => window.TabelaApp && TabelaApp.views.sistem")
        page.evaluate("() => TabelaApp.views.sistem.show()")
        page.wait_for_selector(".sys-badge")
        assert page.inner_text(".sys-badge") == "LIVE"
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        assert "Ultima citire reușită" in page.inner_text("#sys-body")
    finally:
        page.close()
