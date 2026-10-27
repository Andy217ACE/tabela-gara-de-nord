# © 2026 Andy217Ace
"""Real browser: the main pages raise no Content-Security-Policy violation (fonts are
self-hosted, `style-src 'self'`) and the local Fira Sans loads. Skipped without Chromium."""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)


@pytest.mark.parametrize("hash_", ["", "#statistici", "#trenuri", "#statii"])
def test_no_csp_violations_on_main_pages(browser, base_url, hash_):  # noqa: F811
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, service_workers="block")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    msgs = []
    page.on("console", lambda m: msgs.append(m.text))
    try:
        page.goto(base_url + "/" + hash_)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        ok = page.evaluate("""async () => { await document.fonts.load("16px 'Fira Sans'");
            await document.fonts.ready; return document.fonts.check("16px 'Fira Sans'"); }""")
        assert ok is True
        assert not [m for m in msgs if "Content Security Policy" in m], msgs
    finally:
        ctx.close()
