# © 2026 Andy217Ace
"""Cross-browser smoke (Firefox + WebKit = Safari engine, iPhone users): every main route renders at phone
and desktop width without JS errors or horizontal scroll; bottom nav, „Mai mult”, theme and language
toggles work. Chromium is covered by the other *_browser.py files. A missing engine skips cleanly."""
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url  # noqa: E402,F401  (shared seeded-server fixture)

ROUTES = ["tabela", "istoric", "trenuri", "statistici", "statii", "sistem", "versiuni", "cum", "setari"]
SIZES = {"phone": dict(viewport={"width": 390, "height": 844}, has_touch=True),
         "desktop": dict(viewport={"width": 1280, "height": 800})}


@pytest.fixture(scope="module", params=["firefox", "webkit"])
def xbrowser(request):
    with sync_api.sync_playwright() as p:
        try:
            b = getattr(p, request.param).launch()
        except Exception as e:  # engine binaries missing
            pytest.skip(f"{request.param} indisponibil: {e}")
        yield b
        b.close()


def _open(xbrowser, base_url, size, hash_=""):
    ctx = xbrowser.new_context(service_workers="block", **SIZES[size])
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base_url + "/" + hash_)
    page.wait_for_selector(".nav-item[aria-current='page'], .nav-more-link[aria-current='page']", state="attached")
    return ctx, page, errors


@pytest.mark.parametrize("size", SIZES)
def test_routes_render_without_errors(xbrowser, base_url, size):
    ctx, page, errors = _open(xbrowser, base_url, size)
    try:
        for route in ROUTES:
            page.goto(base_url + "/#" + ("" if route == "tabela" else route))
            sec = page.locator(f"#view-{route}")
            sec.wait_for(state="visible")
            page.wait_for_function("r => document.getElementById('view-' + r).innerText.trim().length > 20", arg=route)
            page.wait_for_timeout(150)
            assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"), route
        assert not errors, errors
    finally:
        ctx.close()


def test_phone_bottom_nav_and_more_menu(xbrowser, base_url):
    ctx, page, errors = _open(xbrowser, base_url, "phone")
    try:
        for route in ("istoric", "trenuri", "statistici", "tabela"):
            page.locator(f".mainnav .nav-item[data-route='{route}']").click()
            page.wait_for_function("r => document.querySelector(`.mainnav .nav-item[data-route='${r}']`)"
                                   ".getAttribute('aria-current') === 'page'", arg=route)
        page.click("#nav-more-btn")
        menu = page.locator("#nav-more-menu")
        menu.wait_for(state="visible")
        assert page.get_attribute("#nav-more-btn", "aria-expanded") == "true"
        menu.locator("a").first.click()
        menu.wait_for(state="hidden")
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("size", SIZES)
def test_theme_and_language_toggles(xbrowser, base_url, size):
    ctx, page, errors = _open(xbrowser, base_url, size)
    try:
        before = page.get_attribute("#theme-btn", "data-mode")
        if size == "phone":
            page.click("#nav-more-btn")
        page.click("#theme-btn")
        page.wait_for_function("b => document.getElementById('theme-btn').dataset.mode !== b", arg=before)
        if size == "phone" and not page.locator(".navbar [data-lang-toggle]").is_visible():
            page.click("#nav-more-btn")
        page.click(".navbar [data-lang-toggle]")
        page.wait_for_function("() => document.documentElement.lang === 'en'")
        assert not errors, errors
    finally:
        ctx.close()
