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


def _tip_text(page, key):
    import json
    from pathlib import Path
    ro = json.loads((Path(__file__).resolve().parent.parent / "web" / "i18n" / "ro.json").read_text(encoding="utf-8"))
    return ro[key]


def test_metric_tooltips_on_hover_and_keyboard_focus(browser, base_url):
    ctx, page, errors = _go(browser, base_url, ready=".ss-prob")
    try:
        helps = page.locator(".ss-prob").first.locator(".ss-help")
        assert helps.count() == 3  # severity, confidence, N
        first = helps.first
        tip = first.locator("[role=tooltip]")
        expect(tip).to_be_hidden()
        # keyboard focus (not only hover) shows the explanation
        first.focus()
        expect(tip).to_be_visible()
        assert tip.inner_text().strip() == _tip_text(page, "stats.sp2.help.sev")
        described = first.get_attribute("aria-describedby")
        assert described and page.locator("#" + described).count() == 1
        page.keyboard.press("Escape")
        expect(tip).to_be_hidden()
        # hover shows it too
        page.locator(".ss-prob").first.locator(".ss-help").nth(1).hover()
        expect(page.locator(".ss-prob").first.locator(".ss-help").nth(1).locator("[role=tooltip]")).to_be_visible()
        # median vs mean, on the summary card
        med = page.locator(".ss-quick .ss-card").nth(1).locator(".ss-help")
        med.focus()
        expect(med.locator("[role=tooltip]")).to_be_visible()
        assert errors == []
    finally:
        ctx.close()


def test_tooltips_do_not_overflow_at_360(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 360, 740, ready=".ss-prob")
    try:
        last = page.locator(".ss-prob").first.locator(".ss-help").last
        last.focus()
        expect(last.locator("[role=tooltip]")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth") <= 360
        box = last.locator("[role=tooltip]").bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 360 + 0.5, box
    finally:
        ctx.close()
