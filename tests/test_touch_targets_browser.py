# © 2026 Andy217Ace
"""Real browser at 390×844 (phone): the follow controls — the card „urmărește” button and the
Panou row star + bell — are at least 44×44 px touch targets and neighbouring targets do not
overlap. Skipped when Playwright (dev only) or its Chromium is unavailable."""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

MIN = 44
EPS = 0.5
RECTS = """sel => [...document.querySelectorAll(sel)].map(e => {
  const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })
  .filter(r => r[2] > 0 && r[3] > 0)"""


def _open(browser, base_url, view):  # noqa: F811
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
    ctx.add_init_script(f"localStorage.setItem('tabela.view', '{view}');")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    page.goto(base_url + "/")
    page.wait_for_selector(".pnl-row" if view == "panou" else ".train .follow")
    page.wait_for_timeout(300)
    return ctx, page


def _overlap(a, b):
    return (a[0] < b[0] + b[2] - EPS and b[0] < a[0] + a[2] - EPS and
            a[1] < b[1] + b[3] - EPS and b[1] < a[1] + a[3] - EPS)


def _check(rects):
    assert rects, "no targets found"
    for r in rects:
        assert r[2] >= MIN - EPS and r[3] >= MIN - EPS, rects
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            assert not _overlap(a, b), (a, b)


def test_follow_buttons_min_44px_on_phone(browser, base_url):  # noqa: F811
    ctx, page = _open(browser, base_url, "carduri")
    try:
        assert page.locator(".train .follow").count() >= 2
        _check(page.evaluate(RECTS, ".train .follow"))
    finally:
        ctx.close()


# The card as drawn before the change (BASE: .follow was 32 px high, no min-width, no margin),
# emulated through the CSSOM (inline <style> would be blocked by the CSP): the card height and
# the position of its other parts must not move.
LAYOUT = """emulate => [...document.querySelectorAll('.train')].filter(c => c.offsetWidth > 0)
  .slice(0, 6).map(c => {
  const f = c.querySelector('.follow');
  if (emulate) { f.style.minHeight = '32px'; f.style.minWidth = '0'; f.style.marginBlock = '0'; }
  else { f.style.minHeight = ''; f.style.minWidth = ''; f.style.marginBlock = ''; }
  const pick = sel => { const e = c.querySelector(sel); if (!e) return null;
    const r = e.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; };
  const r = c.getBoundingClientRect();
  return [[r.left, r.top, r.width, r.height], pick('.t-main'), pick('.t-time'), pick('.delay'),
          pick('.t-plat'), (() => { const q = f.getBoundingClientRect();
            return [q.left, q.top + q.height / 2, q.width]; })()];
})"""


def test_card_layout_unchanged_by_touch_target(browser, base_url):  # noqa: F811
    ctx, page = _open(browser, base_url, "carduri")
    try:
        before = page.evaluate(LAYOUT, True)    # as on BASE
        after = page.evaluate(LAYOUT, False)    # as now
        assert len(before) >= 2
        for b, a in zip(before, after):
            for x, y in zip(b, a):
                if x is None or y is None:
                    assert x == y
                    continue
                for u, v in zip(x, y):
                    # the button itself grows 44 px wide only when it was narrower (it is not)
                    assert abs(u - v) <= 0.5, (b, a)
    finally:
        ctx.close()


def test_panou_star_and_bell_min_44px_on_phone(browser, base_url):  # noqa: F811
    ctx, page = _open(browser, base_url, "panou")
    try:
        assert page.locator(".pnl-row .pnl-follow").count() >= 2
        stars = page.evaluate(RECTS, ".pnl-row .pnl-star:not(.pnl-follow)")
        bells = page.evaluate(RECTS, ".pnl-row .pnl-follow")
        assert stars and bells
        _check(stars + bells)           # every star and bell: ≥ 44 px, no overlap among them
        rows = page.evaluate("""() => [...document.querySelectorAll('.pnl-row')].map(r => {
          const g = s => [...r.querySelectorAll(s)].map(e => { const b = e.getBoundingClientRect();
            return [b.left, b.top, b.width, b.height]; }).filter(b => b[2] > 0 && b[3] > 0);
          return { btn: g('.pnl-star'), others: g('a.station-link').concat(g('.pnl-plat')) }; })
          .filter(x => x.btn.length)""")
        assert rows
        for row in rows:
            assert len(row["btn"]) == 2, row  # star + bell in every row
            for b in row["btn"]:
                for o in row["others"]:
                    assert not _overlap(b, o), (b, o)
    finally:
        ctx.close()
