# © 2026 Andy217Ace
"""Real browser: Statistici v3, sub-project 1 — quick summary cards, sticky filters + reset,
deep links to sections (?sect=), saved presets, mobile filter panel. Same fixtures as
tests/test_statistici_browser.py (served page, seeded database)."""
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from app import stats_overview  # noqa: E402
from tests.test_statistici_browser import _open, base_url, browser  # noqa: E402,F401

expect = sync_api.expect

# the route as an old-style #hash (pages have path URLs now: /istoric?date=…)
ROUTE_JS = "location.hash || '#' + location.pathname.slice(1) + location.search"


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
        assert titles == ["La timp", "Întârziere în medie", "Trenuri analizate", "Cea mai problematică rută"]
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
        assert "perioada=7" in page.evaluate(ROUTE_JS)
        reset.click()
        expect(reset).to_be_hidden()
        expect(page.locator("input[name=ss-perioada][value=all]")).to_be_checked()
        assert "perioada=" not in page.evaluate(ROUTE_JS)
        assert page.evaluate(ROUTE_JS) == "#statistici"
        assert errors == []
    finally:
        ctx.close()


def test_deep_link_scrolls_and_highlights_section(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 1280, 800, "#statistici?sect=probleme", ".ss-problems .ss-prob")
    try:
        page.wait_for_selector(".ss-problems.ss-target")
        page.wait_for_function("window.scrollY > 0")
        assert page.locator(".ss-target").count() == 1
        # the filters stay in the address while navigating between sections
        page.locator(".ss-seg-opt", has_text="7 zile").click()
        page.wait_for_selector(".ss-quick .ss-card")
        h = page.evaluate(ROUTE_JS)
        assert "perioada=7" in h and "sect=probleme" in h
        assert errors == []
    finally:
        ctx.close()


def test_summary_card_link_sets_sect(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 1280, 800)
    try:
        page.locator(".ss-quick .ss-card-link").first.click()
        assert "sect=probleme" in page.evaluate(ROUTE_JS)
        page.wait_for_selector(".ss-problems.ss-target")
        assert errors == []
    finally:
        ctx.close()


def test_unknown_section_is_ignored(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 1280, 800, "#statistici?sect=nu-exista")
    try:
        page.wait_for_selector(".ss-problems .ss-prob")
        page.wait_for_timeout(300)
        assert page.locator(".ss-target").count() == 0
        assert page.evaluate("window.scrollY") == 0
        assert errors == []
    finally:
        ctx.close()


def _reload(page, base_url, n):
    """A real reload (new query string), so the page starts from localStorage only."""
    page.goto(f"{base_url}/?r={n}#statistici")
    page.wait_for_selector(".ss-quick .ss-card")


def test_preset_saves_and_restores_filters(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 1280, 800)
    try:
        page.select_option("#ss-operator", "Transferoviar")
        page.locator(".ss-seg-opt", has_text="7 zile").click()
        page.locator(".ss-presets-toggle").click()
        page.fill(".ss-preset-name", "Test")
        page.locator(".ss-preset-save").click()
        expect(page.locator(".ss-preset-apply", has_text="Test")).to_be_visible()
        _reload(page, base_url, 1)
        page.locator(".ss-presets-toggle").click()
        page.locator(".ss-preset-apply", has_text="Test").click()
        expect(page.locator("#ss-operator")).to_have_value("Transferoviar")
        expect(page.locator("input[name=ss-perioada][value='7']")).to_be_checked()
        assert "operator=Transferoviar" in page.evaluate(ROUTE_JS)
        # delete it again
        page.locator(".ss-presets-toggle").click()
        page.locator(".ss-preset-del").first.click()
        expect(page.locator(".ss-preset-apply")).to_have_count(0)
        assert page.evaluate("JSON.parse(localStorage.getItem('tabela.statsPresets')).length") == 0
        assert errors == []
    finally:
        ctx.close()


def test_preset_with_missing_field_applies_valid_fields_only(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 1280, 800)
    try:
        page.evaluate("""localStorage.setItem('tabela.statsPresets', JSON.stringify([
            {name: 'Vechi', filters: {perioada: '7', operator: 'Operator Sters', tip: 'ZZ', camp_vechi: 'x'}}]))""")
        _reload(page, base_url, 2)
        page.locator(".ss-presets-toggle").click()
        page.locator(".ss-preset-apply", has_text="Vechi").click()
        expect(page.locator("input[name=ss-perioada][value='7']")).to_be_checked()
        assert page.locator("#ss-operator").input_value() == ""
        assert page.locator("#ss-tip").input_value() == ""
        assert "operator=" not in page.evaluate(ROUTE_JS)
        assert errors == []
    finally:
        ctx.close()


def test_presets_disabled_without_storage(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 1280, 800)
    try:
        ctx.add_init_script("""const blocked = () => { throw new Error('blocked'); };
            Storage.prototype.getItem = blocked; Storage.prototype.setItem = blocked;
            Storage.prototype.removeItem = blocked;""")
        _reload(page, base_url, 3)
        page.locator(".ss-presets-toggle").click()
        expect(page.locator(".ss-preset-msg")).to_contain_text("indisponibile")
        expect(page.locator(".ss-preset-save")).to_have_count(0)
        # the filters themselves keep working
        page.locator(".ss-seg-opt", has_text="7 zile").click()
        assert "perioada=7" in page.evaluate(ROUTE_JS)
        assert not [e for e in errors if "blocked" in e and "statistici" in e.lower()]
    finally:
        ctx.close()


def test_mobile_filters_collapse_into_panel(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 360, 740, "#statistici?board=arrival&doar_confirmate=1")
    try:
        toggle = page.locator(".ss-filters-toggle")
        expect(toggle).to_be_visible()
        expect(toggle).to_have_text("Filtre (2)")
        expect(page.locator(".ss-seg").first).to_be_hidden()
        expect(page.locator("#ss-operator")).to_be_hidden()
        toggle.click()
        expect(page.locator(".ss-seg").first).to_be_visible()
        expect(page.locator("#ss-operator")).to_be_visible()
        page.select_option("#ss-operator", "Transferoviar")
        expect(toggle).to_have_text("Filtre (3)")
        page.locator(".ss-reset").click()
        expect(toggle).to_have_text("Filtre (0)")
        toggle.click()
        expect(page.locator(".ss-seg").first).to_be_hidden()
        assert errors == []
    finally:
        ctx.close()


def test_wide_screen_keeps_filters_open_without_toggle(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 1280, 800)
    try:
        expect(page.locator(".ss-filters-toggle")).to_be_hidden()
        expect(page.locator(".ss-seg").first).to_be_visible()
        assert errors == []
    finally:
        ctx.close()


def test_no_horizontal_scroll_at_360(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 360, 740, "#statistici?perioada=7")
    try:
        assert page.evaluate("document.documentElement.scrollWidth") <= 360
        page.locator(".ss-filters-toggle").click()
        assert page.evaluate("document.documentElement.scrollWidth") <= 360
        page.locator(".ss-presets-toggle").click()
        expect(page.locator(".ss-presets-menu")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth") <= 360
        rect = page.evaluate("(() => { const r = document.querySelector('.ss-presets-menu').getBoundingClientRect(); return [r.left, r.right]; })()")
        assert rect[0] >= 0 and rect[1] <= 360
        assert errors == []
    finally:
        ctx.close()
