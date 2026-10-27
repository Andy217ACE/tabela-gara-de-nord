# © 2026 Andy217Ace
"""Real browser: Beta 1.26 „UI v2” — every redesigned page at 360 / 768 / 1280 px, dark and
light (no horizontal page scroll, no console / CSP errors, header icon, hero strip, one
footer), the donut charts of Statistici (N, legend, hover / focus tooltip, „Vezi datele” + CSV,
slices add up to the whole), reduced motion, the page transition, skeleton loaders, and the
live Tabela left exactly as it was. Skipped without Chromium."""
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from app import stats_overview  # noqa: E402
from tests.test_footer_browser import COUNT_JS  # noqa: E402
from tests.test_statistici_browser import (  # noqa: E402,F401
    NO_HSCROLL, _open, base_url, browser)

expect = sync_api.expect

# route, selector that proves the page rendered, a hero strip is expected
PAGES = [
    ("#istoric", "#h-results .h-row, #h-results tbody tr", ".ui-hero"),
    ("#urmarite", "#f-hero", None),
    ("#trenuri", "#st-trenuri tbody tr", ".st-hero .ui-hero"),
    ("#tren?nr=1621", "#st-tren .st-card", ".st-hero .ui-hero"),
    ("#statistici", "#st-statistici .ss-fig", ".ss-hero-strip .ui-hero"),
    ("#clasamente", "#st-clasamente .st-podium-card", ".st-hero .ui-hero"),
    ("#statii", "#st-statii tbody tr", ".st-hero .ui-hero"),
    ("#statie?nume=BRASOV", "#st-statie .st-card", ".st-hero .ui-hero"),
    ("#versiuni", "#v-list .v-entry", ".v-hero"),
]
VIEWS = [(360, 780, "dark"), (360, 780, "light"), (768, 900, "dark"), (1280, 800, "light"), (1280, 800, "dark")]


@pytest.mark.parametrize("w,h,theme", VIEWS)
@pytest.mark.parametrize("route,ready,hero", PAGES)
def test_page_is_polished_and_fits(browser, base_url, route, ready, hero, w, h, theme):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, w, h, theme, route)
    try:
        page.wait_for_selector(ready, state="attached", timeout=15000)
        page.wait_for_timeout(300)
        name = route.split("?")[0].lstrip("#")
        head = page.locator(f"#view-{name} .page-head")
        expect(head.locator(".ph-icon")).to_have_count(1)
        if hero:
            expect(page.locator(f"#view-{name} {hero}").first).to_be_visible()
        assert page.evaluate(NO_HSCROLL), "horizontal page scroll"
        assert page.evaluate("document.body.dataset.route") == name
        assert page.evaluate(COUNT_JS) == 1
        assert errors == []
    finally:
        ctx.close()


def _donuts_ready(page):
    page.wait_for_selector("#st-statistici .ss-fig")
    page.wait_for_selector(".ui-donut")


def test_statistici_donuts_for_part_to_whole(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "dark", "#statistici")
    try:
        _donuts_ready(page)
        # on-time share (2 boards), arrivals vs departures, types x2, operators x2, results
        assert page.locator(".ui-donut").count() >= 8
        assert page.locator(".ss-kpi .ui-donut").count() == 2
        share = page.locator(".ss-fig", has_text="Cum se împart călătoriile")
        expect(share).to_have_count(1)
        assert share.locator(".ui-donut").count() >= 5
        # N shown, how to read, CSV and the table alternative
        assert "N = " in share.text_content()
        assert "Cum se citește" in share.text_content()
        assert share.locator("a.ss-csv").count() == 2  # types + operators
        share.locator("details.ss-data summary").click()
        assert share.locator("details.ss-data tbody tr").count() >= 5
        # every ring: accessible name, a legend row per category, slices add up to the whole
        res = page.evaluate("""() => [...document.querySelectorAll('.ui-donut')].map(d => {
          const svg = d.querySelector('svg'); const arcs = [...d.querySelectorAll('circle.ui-seg')];
          const dash = arcs.reduce((a, c) => a + parseFloat(c.getAttribute('stroke-dasharray')), 0);
          return { name: svg.querySelector('title').textContent, role: svg.getAttribute('role'),
                   legend: d.querySelectorAll('.ui-leg-item').length, arcs: arcs.length, dash,
                   focusable: [...d.querySelectorAll('.ui-leg-item')].every(i => i.tabIndex === 0) };
        })""")
        for r in res:
            assert r["name"] and r["role"] == "img" and r["focusable"], r
            assert r["legend"] >= r["arcs"] >= 1, r
            assert 90 <= r["dash"] <= 100.5, r  # slices + small gaps = the whole ring
        assert errors == []
    finally:
        ctx.close()


def test_donut_hover_and_focus_show_the_slice(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "light", "#statistici")
    try:
        _donuts_ready(page)
        d = page.locator(".ss-kpi .ui-donut").first
        rest = d.locator(".ui-dc").text_content()
        item = d.locator(".ui-leg-item").nth(1)
        item.hover()
        expect(d).to_have_class(__import__("re").compile(r"has-active"))
        assert d.locator(".ui-dc").text_content() != rest
        assert d.locator(".ui-dc-l").text_content() == item.locator(".ui-leg-l").text_content()
        page.mouse.move(5, 5)
        expect(d).not_to_have_class(__import__("re").compile(r"has-active"))
        assert d.locator(".ui-dc").text_content() == rest
        d.locator(".ui-leg-item").first.focus()
        expect(d).to_have_class(__import__("re").compile(r"has-active"))
        d.locator(".ui-leg-item").first.blur()
        expect(d).not_to_have_class(__import__("re").compile(r"has-active"))
        # a slice is hit-testable too (not only the legend)
        d.locator("circle.ui-seg").nth(0).dispatch_event("pointerenter")
        expect(d).to_have_class(__import__("re").compile(r"has-active"))
        assert errors == []
    finally:
        ctx.close()


def test_ranked_lists_and_time_series_stay_bars_and_lines(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "dark", "#statistici")
    try:
        _donuts_ready(page)
        op = page.locator(".ss-fig", has_text="Care operatori")
        assert op.locator("path.ss-bar").count() >= 1 and op.locator(".ui-donut").count() == 0
        hourly = page.locator(".ss-fig", has_text="La ce oră")
        assert hourly.locator("path.ss-line").count() >= 1 and hourly.locator(".ui-donut").count() == 0
        assert page.locator(".ss-fig", has_text="Ce zile și ore").locator("rect.ss-cell").count() > 100
        assert errors == []
    finally:
        ctx.close()


def test_reduced_motion_turns_all_animation_off(browser, base_url):
    stats_overview.clear_cache()
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce",
                              service_workers="block")
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(base_url + "/#statistici")
        _donuts_ready(page)
        got = page.evaluate("""() => {
          const an = s => { const e = document.querySelector(s); return e ? getComputedStyle(e).animationName : 'missing'; };
          return { sweep: an('.ui-sweep'), bar: an('.ss-bar'), line: an('.ss-line'),
                   stat: an('.ui-stat'), enter: document.querySelectorAll('.view-enter').length,
                   hidden: document.querySelectorAll('.ui-rv').length,
                   counted: [...document.querySelectorAll('[data-final]')].every(n => n.textContent === n.getAttribute('data-final')) };
        }""")
        assert got["sweep"] == "none" and got["bar"] == "none" and got["line"] == "none", got
        assert got["stat"] == "none" and got["enter"] == 0 and got["hidden"] == 0 and got["counted"], got
        assert errors == []
    finally:
        ctx.close()


def test_motion_is_on_by_default_and_counts_up(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "dark", "#statistici")
    try:
        _donuts_ready(page)
        got = page.evaluate("""() => {
          const an = s => getComputedStyle(document.querySelector(s)).animationName;
          return { sweep: an('.ui-sweep'), bar: an('.ss-bar') };
        }""")
        assert got["sweep"] == "ui-sweep" and got["bar"].startswith("ui-grow"), got
        page.wait_for_timeout(1600)
        assert page.evaluate("""() => [...document.querySelectorAll('.ui-stat-v[data-final]')]
          .every(n => n.textContent === n.getAttribute('data-final'))""")
        # below-the-fold cards are revealed on first sight, never left hidden
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(900)
        page.evaluate("window.scrollTo(0, 0)")
        assert page.locator(".ui-rv:not(.ui-rv-in)").evaluate_all(
            "els => els.filter(e => { const r = e.getBoundingClientRect(); return r.top < innerHeight; }).length") == 0
        assert errors == []
    finally:
        ctx.close()


def test_page_transition_and_live_board_untouched(browser, base_url):
    ctx, page, errors = _open(browser, base_url, 1280, 800, "dark", "#statistici")
    try:
        page.wait_for_selector("#st-statistici .ss-fig")
        page.evaluate("""() => { window.__enter = []; new MutationObserver(ms => ms.forEach(m => {
            if (m.target.classList.contains('view-enter')) window.__enter.push(m.target.id); }))
            .observe(document.querySelector('main'), { subtree: true, attributes: true, attributeFilter: ['class'] }); }""")
        page.locator(".nav-item[data-route='istoric']").click()
        page.wait_for_selector("#view-istoric:not([hidden])")
        page.wait_for_timeout(100)
        assert "view-istoric" in page.evaluate("window.__enter")
        # the live board: no UI v2 class inside it, no page canvas, no enter animation
        page.locator(".nav-item[data-route='tabela']").click()
        page.wait_for_selector("#view-tabela:not([hidden])")
        page.wait_for_timeout(500)
        assert page.evaluate("document.body.dataset.route") == "tabela"
        assert page.evaluate("document.querySelectorAll('#view-tabela [class*=\"ui-\"], #view-tabela .ph-icon').length") == 0
        assert page.evaluate("getComputedStyle(document.body, '::before').content") in ("none", "normal")
        assert "view-enter" not in page.evaluate("document.getElementById('view-tabela').className")
        assert errors == []
    finally:
        ctx.close()


def test_skeleton_while_loading_then_content(browser, base_url):
    stats_overview.clear_cache()
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
    page = ctx.new_page()
    held = []
    page.route("**/api/stats/overview*", lambda route: held.append(route))  # hold the response
    try:
        page.goto(base_url + "/#statistici")
        page.wait_for_selector("#st-statistici .ui-skel", state="attached", timeout=8000)
        assert page.locator("#st-statistici .ui-skel").first.get_attribute("aria-hidden") == "true"
        assert "Se încarcă" in page.text_content("#st-statistici")  # still announced (sr-only)
        assert page.evaluate(NO_HSCROLL)
        for r in held:
            r.continue_()
        page.wait_for_selector("#st-statistici .ss-fig", timeout=15000)
        expect(page.locator("#st-statistici .ui-skel")).to_have_count(0)
    finally:
        ctx.close()


def test_empty_database_keeps_explicit_message_without_hero(browser, base_url):
    """(uses the shared seeded DB; the empty-DB case is covered in test_statistici_browser)"""
    ctx, page, errors = _open(browser, base_url, 360, 780, "dark", "#trenuri?query=zzzzzz")
    try:
        page.wait_for_selector("#st-trenuri .empty")
        assert "Niciun tren" in page.text_content("#st-trenuri")
        assert page.evaluate(NO_HSCROLL) and errors == []
    finally:
        ctx.close()
