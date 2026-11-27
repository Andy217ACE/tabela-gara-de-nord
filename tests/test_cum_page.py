# © 2026 Andy217Ace
"""Public page #cum („Cum funcționează?"): static wiring + a real-browser run in ro and en."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def test_static_route_lazy_footer_and_i18n():
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert '"#cum": "cum"' in app and 'loadLazyPage("cum", "cum.js", "cum.css")' in app
    for name in ("VIEWS", "TITLES"):  # registered last, as a view and with a page title
        assert re.search(r'var %s = \[[^\]]*"cum"\]' % name, app), name
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'href="#cum" data-i18n="footer.how"' in html
    js = (WEB / "cum.js").read_text(encoding="utf-8")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", ".style.", "cssText"):
        assert bad not in js, bad
    css = (WEB / "cum.css").read_text(encoding="utf-8")
    assert "@import" not in css and "url(" not in css
    ro = json.loads((WEB / "i18n" / "ro.json").read_text(encoding="utf-8"))
    en = json.loads((WEB / "i18n" / "en.json").read_text(encoding="utf-8"))
    keys = lambda d: {k for k in d if k.startswith("cum.")}  # noqa: E731
    assert keys(ro) == keys(en) and len(keys(ro)) > 30
    assert ro["title.cum"] == "Cum funcționează?" and en["title.cum"] == "How it works"


sync_api = pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

VISIBLE_H1 = "() => [...document.querySelectorAll('h1')].filter(h => !h.closest('[hidden]')).map(h => h.textContent)"


@pytest.mark.parametrize("lang,title,h2", [("ro", "Cum funcționează?", "Confidențialitate"),
                                           ("en", "How it works", "Privacy")])
def test_cum_page_in_both_languages(browser, base_url, lang, title, h2):  # noqa: F811
    ctx = browser.new_context(viewport={"width": 390, "height": 800}, service_workers="block")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(base_url + "/?lang=" + lang + "#cum")
        page.wait_for_selector("#view-cum:not([hidden]) h2")
        assert page.evaluate(VISIBLE_H1) == [title]
        assert page.title().startswith(title)
        assert h2 in page.inner_text("#view-cum")
        assert page.locator("#view-cum h2").count() == 6
        assert page.locator("#view-cum .cum-step").count() == 4
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        # leaving the page hides it again (route in VIEWS)
        page.goto(base_url + "/?lang=" + lang + "#sistem")
        page.wait_for_function("() => document.getElementById('view-cum').hidden")
        assert errors == []
    finally:
        ctx.close()


def test_footer_link_opens_cum(browser, base_url):  # noqa: F811
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, service_workers="block")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    try:
        page.goto(base_url + "/")
        page.click("footer a[href='#cum']")
        page.wait_for_selector("#view-cum:not([hidden]) h1")
        assert page.evaluate(VISIBLE_H1) == ["Cum funcționează?"]
    finally:
        ctx.close()
