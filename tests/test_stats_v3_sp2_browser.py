# © 2026 Andy217Ace
"""Real browser: Statistici v3, sub-project 2 — one color scale, metric tooltips, chart click ->
train list, high contrast, simple/expert mode, short texts with „Citește mai mult”.
Same fixtures as tests/test_statistici_browser.py (served page, seeded database)."""
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from app import stats_overview  # noqa: E402
from tests.test_statistici_browser import NO_HSCROLL, _open, base_url, browser  # noqa: E402,F401

expect = sync_api.expect


def _go(browser, base_url, w=1280, h=800, hash_="#statistici", ready=".ss-quick .ss-card", theme="light"):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, w, h, theme, hash_)
    if ready:
        page.wait_for_selector(ready)
    return ctx, page, errors


def test_scale_applied_to_summary_and_ranked_bars(browser, base_url):
    ctx, page, errors = _go(browser, base_url, ready=".ss-quick .ss-card")
    try:
        page.wait_for_selector(".ss-fig .ss-bar", state="attached")
        val = page.locator(".ss-quick .ss-card").first.locator(".ss-card-v")
        cls = val.get_attribute("class")
        assert any(f"ss-t-{k}" in cls for k in ("good", "mid", "bad")), cls
        ranked = page.locator('[data-key="care-operatori-sunt-cei-mai-punctu"] .ss-bar')
        assert ranked.count() > 0
        for c in ranked.evaluate_all("els => els.map(e => e.getAttribute('class'))"):
            assert any(f"ss-t-{k}" in c for k in ("good", "mid", "bad")), c
        # the tone is the same for the same number: green token color on good, red on bad
        probe = page.evaluate("""() => { const r = getComputedStyle(document.documentElement);
          return ['--ss-good','--ss-mid','--ss-bad'].map(k => r.getPropertyValue(k).trim()); }""")
        assert all(probe) and len(set(probe)) == 3, probe
        assert errors == []
    finally:
        ctx.close()
