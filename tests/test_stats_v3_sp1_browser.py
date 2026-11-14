# © 2026 Andy217Ace
"""Real browser: Statistici v3, sub-project 1 — quick summary cards, sticky filters + reset,
deep links to sections (?sect=), saved presets, mobile filter panel. Same fixtures as
tests/test_statistici_browser.py (served page, seeded database)."""
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from app import stats_overview  # noqa: E402
from tests.test_statistici_browser import _open, base_url, browser  # noqa: E402,F401

expect = sync_api.expect


def _go(browser, base_url, w, h, hash_="#statistici", ready=".ss-quick .ss-card"):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, w, h, "light", hash_)
    if ready:
        page.wait_for_selector(ready)
    return ctx, page, errors


def test_summary_cards_show_four_metrics(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 1280, 800)
    try:
        cards = page.locator(".ss-quick .ss-card")
        assert cards.count() == 4
        titles = [t.strip() for t in cards.locator(".ss-card-t").all_text_contents()]
        assert titles == ["La timp", "Întârziere medie", "Trenuri analizate", "Cea mai problematică rută"]
        for txt in cards.locator(".ss-card-v").all_text_contents():
            assert txt.strip() and "NaN" not in txt and "undefined" not in txt
        assert "NaN" not in page.text_content(".ss-quick")
        assert errors == []
    finally:
        ctx.close()


def test_filters_stay_sticky_after_scroll(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 1280, 800)
    try:
        page.evaluate("window.scrollTo(0, 900)")
        page.wait_for_timeout(200)
        assert page.evaluate("window.scrollY") > 300
        # sticky under the sticky main menu bar, never behind it
        nav_bottom = page.evaluate("document.querySelector('.navbar').getBoundingClientRect().bottom")
        top = page.evaluate("document.querySelector('.ss-filters').getBoundingClientRect().top")
        assert nav_bottom - 1 <= top <= nav_bottom + 1, (top, nav_bottom)
        assert errors == []
    finally:
        ctx.close()


def test_reset_clears_filters_and_hash(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 1280, 800)
    try:
        reset = page.locator(".ss-reset")
        expect(reset).to_be_hidden()
        page.locator(".ss-seg-opt", has_text="7 zile").click()
        expect(reset).to_be_visible()
        assert "perioada=7" in page.evaluate("location.hash")
        reset.click()
        expect(reset).to_be_hidden()
        expect(page.locator("input[name=ss-perioada][value=all]")).to_be_checked()
        assert "perioada=" not in page.evaluate("location.hash")
        assert page.evaluate("location.hash") == "#statistici"
        assert errors == []
    finally:
        ctx.close()
