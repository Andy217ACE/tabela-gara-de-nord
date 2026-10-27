# © 2026 Andy217Ace
"""Automatic contrast audit (Beta 1.20, UI2): every visible text on the main screens has a
contrast ratio of at least 4.5:1 (3:1 for large text) against its composed background, in
the dark and the light theme, on desktop and phone widths. Same JS as
scripts/contrast_audit.py. Skipped when Playwright (dev only) or its Chromium is missing."""
import pytest

pytest.importorskip("playwright.sync_api")

from scripts.contrast_audit import AUDIT_JS, SETTLE_JS  # noqa: E402
from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

SCREENS = [("#", "panou"), ("#", "carduri"), ("#istoric", "panou"), ("#urmarite", "panou"),
           ("#trenuri", "panou"), ("#statii", "panou"), ("#statistici", "panou"),
           ("#clasamente", "panou"), ("#versiuni", "panou")]


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("width", [1280, 390])
def test_text_contrast(browser, base_url, theme, width):  # noqa: F811
    ctx = browser.new_context(viewport={"width": width, "height": 900}, service_workers="block")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    failures = []
    try:
        for route, view in SCREENS:
            page = ctx.new_page()
            page.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}');"
                                 f"localStorage.setItem('tabela.view', '{view}');")
            page.goto(base_url + "/" + route)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(300)
            page.evaluate(SETTLE_JS)  # entrance animations finished: audit the settled page
            for f in page.evaluate(AUDIT_JS):
                failures.append((route, view, f))
            page.close()
    finally:
        ctx.close()
    assert not failures, failures[:10]


def test_audit_detects_low_contrast(browser, base_url):  # noqa: F811
    """The audit itself works: a grey-on-grey text is reported, a normal text is not."""
    ctx = browser.new_context(viewport={"width": 800, "height": 600}, service_workers="block")
    page = ctx.new_page()
    page.goto(base_url + "/offline.html")
    page.evaluate("""() => {
      const a = document.createElement('p'); a.textContent = 'slab'; a.className = 'probe-low';
      a.style.color = '#777'; a.style.background = '#888'; a.style.fontSize = '14px';
      document.body.appendChild(a);
    }""")
    texts = [f["text"] for f in page.evaluate(AUDIT_JS)]
    ctx.close()
    assert "slab" in texts
    assert not any(t.startswith("Ești offline") or t.startswith("Tabela") for t in texts)
