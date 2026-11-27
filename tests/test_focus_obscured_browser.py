# © 2026 Andy217Ace
"""WCAG 2.2 2.4.11 Focus Not Obscured (Minimum): on a phone, tabbing through each route never leaves the
focused element entirely hidden behind a fixed/sticky bar (the bottom nav, the top header, filter bars)."""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

ROUTES = ["#", "#istoric", "#urmarite", "#trenuri", "#statii", "#statistici", "#clasamente",
          "#versiuni", "#sistem", "#setari", "#cum"]

HIDDEN_JS = """() => {
  const f = document.activeElement; if (!f || f === document.body) return null;
  const r = f.getBoundingClientRect(); if (!r.width || !r.height) return null;
  const bars = [...document.querySelectorAll('body *')].filter(e => {
    const p = getComputedStyle(e).position; return (p === 'fixed' || p === 'sticky') && !e.contains(f) && !f.contains(e); });
  for (const b of bars) { const q = b.getBoundingClientRect(), cs = getComputedStyle(b);
    if (!q.width || !q.height || cs.visibility === 'hidden' || cs.display === 'none' || cs.pointerEvents === 'none') continue;
    if (r.left >= q.left - .5 && r.right <= q.right + .5 && r.top >= q.top - .5 && r.bottom <= q.bottom + .5)
      return f.tagName + '.' + f.className + ' under ' + b.tagName + '.' + b.className; }
  return null;
}"""


def test_focus_not_obscured_on_phone(browser, base_url):  # noqa: F811
    ctx = browser.new_context(viewport={"width": 390, "height": 600}, service_workers="block")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    bad = []
    try:
        for route in ROUTES:
            page = ctx.new_page()
            page.goto(base_url + "/" + route)
            page.wait_for_load_state("networkidle")
            for _ in range(45):
                page.keyboard.press("Tab")
                hit = page.evaluate(HIDDEN_JS)
                if hit:
                    bad.append((route, hit))
                    break
            page.close()
    finally:
        ctx.close()
    assert not bad, bad


@pytest.mark.parametrize("width", [1280, 390])
def test_consistent_help_link_on_every_route(browser, base_url, width):  # noqa: F811
    """WCAG 2.2 3.2.6: the „Cum funcționează?” help link sits in the shared footer, same place on every page."""
    ctx = browser.new_context(viewport={"width": width, "height": 800}, service_workers="block")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    page.goto(base_url + "/")
    seen = set()
    try:
        for route in ROUTES[:-1]:
            page.evaluate("h => { location.hash = h; }", route)
            page.wait_for_timeout(300)
            link = page.locator("a.footer-how")
            assert link.count() == 1 and link.is_visible(), route
            seen.add(page.evaluate("() => { const f = document.querySelector('a.footer-how').closest('footer');"
                                   " return [...f.querySelectorAll('a')].findIndex(a => a.matches('.footer-how')); }"))
    finally:
        ctx.close()
    assert len(seen) == 1, seen  # same relative order everywhere
