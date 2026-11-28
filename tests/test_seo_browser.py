# © 2026 Andy217Ace
"""Real browser: path URLs (/statistici, /tren/1636), old #hash links normalized with
replaceState, in-app links without a reload, back/forward, the offline shell on a path, and
no CSP violation from the JSON-LD block. Skipped without Chromium."""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)


def _ctx(browser, base_url, sw="block"):  # noqa: F811
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, service_workers=sw)
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    msgs = []
    page.on("console", lambda m: msgs.append(m.text) if m.type == "error" or "Content Security" in m.text else None)
    return ctx, page, msgs


def _shown(page):
    return page.evaluate("[...document.querySelectorAll('main > .view')].filter(s => !s.hidden).map(s => s.id)")


def _where(page):
    return page.evaluate("location.pathname + location.search + location.hash")


@pytest.mark.parametrize("path,view", [("/statistici", "view-statistici"), ("/tren/1636", "view-tren"),
                                       ("/statie/BRASOV", "view-statie"), ("/cum", "view-cum")])
def test_path_routes(browser, base_url, path, view):  # noqa: F811
    ctx, page, msgs = _ctx(browser, base_url)
    try:
        page.goto(base_url + path)
        page.wait_for_function("id => { const s = document.getElementById(id); return s && !s.hidden; }", arg=view)
        page.wait_for_load_state("networkidle")
        assert _shown(page) == [view]
        assert page.locator(".ssr").is_hidden()            # the crawler copy is hidden while the app runs
        assert _where(page) == path
        # the seed has no trains catalog: /tren/1636 is a 404 shell there (no JSON-LD), tested in test_seo.py
        assert page.locator('script[type="application/ld+json"]').count() == (0 if path.startswith("/tren/") else 1)
        assert not [m for m in msgs if "Content Security Policy" in m], msgs
        assert not [m for m in msgs if "404" not in m], msgs   # unknown-train page answers 404 by design
    finally:
        ctx.close()


@pytest.mark.parametrize("old,new,view", [("/#tren?nr=1636", "/tren/1636", "view-tren"),
                                          ("/#statie?nume=BRASOV&board=arrival", "/statie/BRASOV?board=arrival", "view-statie"),
                                          ("/#istoric?train=1636", "/istoric?train=1636", "view-istoric"),
                                          ("/?lang=en#clasamente", "/clasamente?lang=en", "view-clasamente")])
def test_old_hash_links_are_normalized(browser, base_url, old, new, view):  # noqa: F811
    ctx, page, msgs = _ctx(browser, base_url)
    try:
        page.goto(base_url + old)
        page.wait_for_function("id => !document.getElementById(id).hidden", arg=view)
        assert _where(page).startswith(new), _where(page)
    finally:
        ctx.close()


def test_private_route_stays_hash(browser, base_url):  # noqa: F811
    ctx, page, msgs = _ctx(browser, base_url)
    try:
        page.goto(base_url + "/statistici#sistem")
        page.wait_for_timeout(300)
        assert _where(page) == "/#sistem"
        assert page.evaluate("document.body.dataset.route") == "sistem"
    finally:
        ctx.close()


def test_links_navigate_in_page_and_back_forward(browser, base_url):  # noqa: F811
    ctx, page, msgs = _ctx(browser, base_url)
    try:
        page.goto(base_url + "/")
        page.wait_for_function("() => document.body.dataset.route === 'tabela'")
        page.evaluate("window.__same = 1")
        page.click('.mainnav a[href="/statistici"]')
        page.wait_for_function("() => document.body.dataset.route === 'statistici'")
        assert _where(page) == "/statistici"
        page.click('.mainnav a[href="/statii"]')
        page.wait_for_function("() => document.body.dataset.route === 'statii'")
        page.evaluate("location.hash = '#tren?nr=1636'")   # how stats.js rows navigate
        page.wait_for_function("() => document.body.dataset.route === 'tren'")
        assert _where(page) == "/tren/1636"
        page.go_back()
        page.wait_for_function("() => document.body.dataset.route === 'statii'")
        assert _where(page) == "/statii"
        page.go_back()
        page.wait_for_function("() => document.body.dataset.route === 'statistici'")
        page.go_forward()
        page.wait_for_function("() => document.body.dataset.route === 'statii'")
        assert page.evaluate("window.__same") == 1        # never reloaded
        page.focus(".skip-link")                          # in-page anchor: stays on the page
        page.keyboard.press("Enter")
        page.wait_for_timeout(200)
        assert page.evaluate("window.__same") == 1 and _where(page) == "/statii"
        assert page.evaluate("document.activeElement.id") == "main"
        assert not msgs, msgs
    finally:
        ctx.close()


def test_offline_shell_on_a_path(browser, base_url):  # noqa: F811
    ctx, page, msgs = _ctx(browser, base_url, sw="allow")
    try:
        page.goto(base_url + "/")
        page.evaluate("navigator.serviceWorker.ready.then(() => true)")
        page.reload()
        page.wait_for_function("() => !!navigator.serviceWorker.controller")
        ctx.set_offline(True)
        page.goto(base_url + "/clasamente")
        page.wait_for_function("() => document.body.dataset.route === 'clasamente'")
        assert not page.locator("#view-clasamente").is_hidden()
    finally:
        ctx.set_offline(False)
        ctx.close()
