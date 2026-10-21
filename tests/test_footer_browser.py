# © 2026 Andy217Ace
"""Real-browser check: exactly ONE attribution footer is visible (bug: on desktop the page
footer and the Panou credit were both shown). Also: version in the footer and the
„Versiuni” screen. Skipped when Playwright (dev only) or its Chromium is unavailable."""
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

import uvicorn  # noqa: E402

from app.api import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.version import __version__  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ATTR = "© 2026 Andy217Ace"

COUNT_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && cs.display !== 'none' && cs.visibility !== 'hidden'; };
  return [...document.querySelectorAll('footer, .pnl-credit')]
    .filter(e => e.textContent.includes('%s') && vis(e)).length;
}""" % ATTR


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    db = tmp_path_factory.mktemp("browser") / "b.db"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "dev_seed.py"), str(db)],
                   check=True, cwd=ROOT, capture_output=True)
    settings = Settings(db_path=str(db), source_url="http://127.0.0.1:9/none",
                        vapid_private_key="", vapid_public_key="", vapid_subject="mailto:a@b.c",
                        tesseract_cmd="tesseract", poller_enabled=False, last_image_path=None)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings, start_poller=False),
                                           host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # browser binaries missing
            pytest.skip(f"Chromium indisponibil: {e}")
        yield b
        b.close()


def _page(browser, base_url, w, h, theme, view):
    ctx = browser.new_context(viewport={"width": w, "height": h}, service_workers="block")
    ctx.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}');"
                        f"localStorage.setItem('tabela.view', '{view}');")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(base_url + "/")
    page.wait_for_function("document.documentElement.dataset.view === '%s'" % view)
    page.wait_for_timeout(300)
    return ctx, page, errors


@pytest.mark.parametrize("w,h", [(1280, 800), (390, 844)])
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("view", ["panou", "carduri"])
def test_exactly_one_visible_footer(browser, base_url, w, h, theme, view):
    ctx, page, _ = _page(browser, base_url, w, h, theme, view)
    try:
        assert page.evaluate(COUNT_JS) == 1
    finally:
        ctx.close()


def test_footer_shows_version_and_versions_screen(browser, base_url):
    ctx, page, errors = _page(browser, base_url, 1280, 800, "dark", "carduri")
    try:
        page.wait_for_function(
            "document.getElementById('app-version').textContent === %r" % __version__)
        page.click("#app-version")
        page.wait_for_selector("#view-versiuni:not([hidden]) .v-entry")
        assert __version__ in page.inner_text("#view-versiuni")
        assert page.title().startswith("Versiuni")
        assert not [e for e in errors if "Content Security Policy" in e]
    finally:
        ctx.close()


@pytest.mark.parametrize("w,h", [(1280, 800), (390, 844)])
@pytest.mark.parametrize("view", ["panou", "carduri"])
def test_clocks_show_seconds_without_breaking_the_header(browser, base_url, w, h, view):
    ctx, page, _ = _page(browser, base_url, w, h, "dark", view)
    try:
        sel = ".pnl-clock-time" if view == "panou" else ".hdr-clock-time"
        # poll from Python: page-side string predicates need eval, which the CSP forbids
        seen = []
        for _ in range(40):
            seen.append(page.text_content(sel))
            if len(set(x for x in seen if re.fullmatch(r"\d{2}:\d{2}:\d{2}", x or ""))) >= 2:
                break
            page.wait_for_timeout(100)
        good = [x for x in seen if re.fullmatch(r"\d{2}:\d{2}:\d{2}", x or "")]
        assert len(set(good)) >= 2, seen  # HH:MM:SS, ticking every second
        assert not page.evaluate("document.documentElement.scrollWidth > "
                                 "document.documentElement.clientWidth")
        if view == "carduri":  # header clock row: the clock text never wraps
            box = page.locator(".hdr-clock-time").bounding_box()
            assert box and box["height"] < 40
    finally:
        ctx.close()
