# © 2026 Andy217Ace
"""WCAG 2.2 AA spot checks in a real browser (no axe vendored: three targeted assertions are
enough and keep the repo small): target size >= 24px (2.5.8), exactly one h1 and no skipped
heading levels per view, prefers-reduced-motion kills transitions/animations."""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

ROUTES = ["#", "#istoric", "#urmarite", "#trenuri", "#statii", "#statistici", "#clasamente",
          "#versiuni", "#sistem", "#setari"]

TARGETS_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && !e.closest('[hidden],.sr-only'); };
  const inline = e => e.tagName === 'A' && getComputedStyle(e).display === 'inline'
    && e.parentElement && e.parentElement.textContent.trim().length > e.textContent.trim().length + 8;
  const box = e => e.getBoundingClientRect();
  return [...document.querySelectorAll('a[href],button,input:not([type=hidden]),select,summary,[role=button],[tabindex="0"]')]
    .filter(e => vis(e) && !inline(e) && !e.matches('.skip,.skip-link'))
    .map(e => [e, box(e)]).filter(([e, r]) => r.width < 23.5 || r.height < 23.5)
    .map(([e, r]) => e.tagName + '.' + e.className + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)
      + ' ' + (e.textContent || '').trim().slice(0, 20)).slice(0, 8);
}"""

HEADINGS_JS = """() => {
  const sec = document.querySelector('main section.view:not([hidden])') || document;
  const hs = [...sec.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(h => h.getClientRects().length)
    .map(h => +h.tagName[1]);
  const bad = []; let prev = 0;
  for (const l of hs) { if (prev && l > prev + 1) bad.push(prev + '>' + l); prev = l; }
  return { h1: hs.filter(l => l === 1).length, bad, first: [...sec.querySelectorAll('h1,h2,h3,h4')].filter(h=>h.getClientRects().length).slice(0,4).map(h=>h.tagName+'.'+h.className) };
}"""


def _open(browser, base_url, route, width, **ctx_kw):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, service_workers="block", **ctx_kw)
    page = ctx.new_page()
    page.goto(base_url + "/" + route)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(400)
    return ctx, page


@pytest.mark.parametrize("width", [1280, 390])
def test_target_size_and_headings(browser, base_url, width):  # noqa: F811
    problems = []
    for route in ROUTES:
        ctx, page = _open(browser, base_url, route, width)
        small = page.evaluate(TARGETS_JS)
        h = page.evaluate(HEADINGS_JS)
        ctx.close()
        if small:
            problems.append((route, "target<24", small))
        if h["h1"] != 1 or h["bad"]:
            problems.append((route, "headings", h))
    assert not problems, " | ".join(map(str, problems))


def test_reduced_motion_disables_animation(browser, base_url):  # noqa: F811
    ctx, page = _open(browser, base_url, "#", 1280, reduced_motion="reduce")
    long_ = page.evaluate("""() => [...document.querySelectorAll('*')].filter(e => {
      const cs = getComputedStyle(e);
      const t = parseFloat(cs.transitionDuration) || 0, a = parseFloat(cs.animationDuration) || 0;
      return (t > 0.05 || (a > 0.05 && cs.animationName !== 'none'));
    }).map(e => e.tagName + '.' + e.className).slice(0, 8)""")
    ctx.close()
    assert not long_, long_
