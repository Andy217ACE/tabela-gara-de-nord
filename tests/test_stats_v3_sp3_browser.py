# © 2026 Andy217Ace
"""Real browser: Statistici v3 sub-project 3 — alert banner, „Ce s-a schimbat săptămâna asta”, the 7-day
comparison, „Cele mai fiabile trenuri” and the weekday x hour heatmap (common scale). The routes of the
new endpoints are wired by the controller (docs/superpowers/plans/2026-11-17-sp3-integrare.md), so
here the browser intercepts them and answers with the payloads of the real modules computed on the
seeded database (the day of the data is fixed: 2026-10-20). Same fixtures as test_statistici_browser."""
import json
from datetime import date

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from app import stats, stats_changes, stats_compare, stats_heatmap, stats_overview  # noqa: E402
from app.store import Store  # noqa: E402
from tests.test_stats_overview import add  # noqa: E402
from tests.test_statistici_browser import INSIDE, NO_HSCROLL, _serve, browser  # noqa: E402,F401

expect = sync_api.expect
TODAY = date(2026, 10, 20)
P = stats.Params(on_time=5, min_sample=2)


def _seed_full(c):
    for d in range(7, 21):
        add(c, "arrival", 1001, d, "08:10", 0 if d < 14 else 25, station="SLOW", operator="Op SLOW")   # worse, alert
        add(c, "arrival", 1002, d, "09:10", 20 if d < 14 else 0, station="FAST", operator="Op FAST")   # better
        add(c, "departure", 1003, d, "17:20", 3, station="STABLE", operator="Op STABLE")
    add(c, "arrival", 1004, 20, "10:00", 0, station="ONCE", operator="Op ONCE")   # one journey: never reliable


def _seed_young(c):
    for d in (19, 20):
        add(c, "arrival", 1001, d, "08:10", 3, station="SLOW", operator="Op SLOW")


def _fixture(tmp_path_factory, name, seed):
    db = tmp_path_factory.mktemp(name) / "s.db"
    s = Store(str(db))
    s.migrate()
    seed(s._conn)
    stats_overview.clear_cache()
    server, t, url = _serve(db)
    yield url, s
    server.should_exit = True
    t.join(5)
    s.close()


@pytest.fixture(scope="module")
def full(tmp_path_factory):
    yield from _fixture(tmp_path_factory, "sp3f", _seed_full)


@pytest.fixture(scope="module")
def young(tmp_path_factory):
    yield from _fixture(tmp_path_factory, "sp3y", _seed_young)


def _payload(store, path, query):
    stats_compare.clear_cache()
    filters = {}
    if path.endswith("/changes"):
        return stats_changes.changes(store, P, filters, TODAY)
    if path.endswith("/reliable"):
        return stats_changes.reliable(store, P, filters, TODAY)
    if path.endswith("/heatmap"):
        return stats_heatmap.heatmap(store, P, filters, TODAY)
    return stats_compare.compare(store, P, filters, TODAY)


def _go(browser, fx, w=1280, h=800, theme="light", hits=None):
    base_url, store = fx
    stats_overview.clear_cache()
    ctx = browser.new_context(viewport={"width": w, "height": h}, service_workers="block")
    ctx.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}');")
    errors = []

    def handler(route):
        url = route.request.url
        if not url.startswith(base_url):
            return route.abort()
        path = url.split("?")[0]
        mocked = path.endswith(("/api/stats/changes", "/api/stats/reliable", "/api/stats/heatmap")) \
            or (path.endswith("/api/stats/overview") and "compare=prev7" in url)
        if not mocked:
            return route.continue_()
        if hits is not None:
            hits.append(url)
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps(_payload(store, path, url)))

    ctx.route("**/*", handler)
    page = ctx.new_page()
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base_url + "/#statistici")
    page.wait_for_selector(".ss-quick .ss-card")
    return ctx, page, errors


def _bottom(page, selector):
    for _ in range(12):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        try:
            page.wait_for_selector(selector, timeout=1200)
            return
        except sync_api.TimeoutError:
            pass
    page.wait_for_selector(selector, timeout=3000)


@pytest.mark.parametrize("w,h", [(1280, 800), (390, 844)])
def test_banner_changes_and_comparison(browser, full, w, h):
    ctx, page, errors = _go(browser, full, w, h)
    try:
        banner = page.locator(".ss-sp3-alert")
        expect(banner).to_be_visible()
        expect(banner).to_contain_text("Slow")
        expect(banner).to_contain_text("tipică")
        # the banner sits in the summary area, right after the cards (it comes with a second request: placed
        # above them it pushed the cards down, CLS — Phase 1)
        assert page.evaluate("""() => { const b = document.querySelector('.ss-sp3-alert'), c = document.querySelector('.ss-quick');
          return b.parentNode === c.parentNode && b.previousElementSibling === c; }""")
        chg = page.locator(".ss-sp3-changes")
        expect(chg).to_contain_text("Ce s-a schimbat săptămâna asta")
        expect(chg.locator(".ss-sp3-up")).to_contain_text("Fast")
        expect(chg.locator(".ss-sp3-down")).to_contain_text("Slow")
        cmp = page.locator(".ss-sp3-compare")
        expect(cmp.locator("tbody tr")).to_have_count(4)
        expect(cmp.locator("thead th")).to_have_count(4)
        assert page.evaluate(NO_HSCROLL)
        assert page.evaluate(INSIDE) == []
        assert errors == []
    finally:
        ctx.close()


def test_reliable_trains_and_heatmap_with_one_scale(browser, full):
    hits = []
    ctx, page, errors = _go(browser, full, hits=hits)
    try:
        # delayed sections: nothing asked for before the first visit
        assert not any(h.split("?")[0].endswith(("/reliable", "/heatmap")) for h in hits)
        _bottom(page, '[data-sp3="heatmap"] svg.ss-sp3-heat-svg')
        sec = page.locator(".ss-sp3-sec", has_text="Cele mai fiabile trenuri")
        sec.wait_for()
        page.wait_for_selector(".ss-sp3-rel-i")
        text = sec.inner_text()
        assert "1001" in text and "1004" not in text   # one journey never qualifies
        hm = page.locator('[data-sp3="heatmap"]')
        assert hm.locator("svg.ss-sp3-heat-svg").count() == 2   # arrivals and departures
        assert hm.locator("svg.ss-sp3-heat-svg").first.locator("rect.ss-cell").count() == 7 * 24
        # day axis 0-6 (letters) and hours 0-23 (ticks)
        assert hm.locator("svg.ss-sp3-heat-svg").first.locator("text.ss-tick-y").count() == 7
        # a single legend: the common scale
        assert hm.locator(".ss-legend-scale").count() == 1
        assert "12,5" in hm.locator(".ss-legend-scale").inner_text()   # 7 days at 0 and 7 at 25: mean 12.5
        # the 12.5-minute mean is the darkest class of the shared scale; the 3-minute departures are far below it
        arr = hm.locator("svg.ss-sp3-heat-svg").first
        assert arr.locator("rect.ss-q4").count() >= 1
        dep = hm.locator("svg.ss-sp3-heat-svg").nth(1)
        assert dep.locator("rect.ss-q4").count() == 0 and dep.locator("rect.ss-q1").count() >= 1
        assert page.evaluate(NO_HSCROLL)
        assert errors == []
    finally:
        ctx.close()


def test_young_database_says_insufficient_never_zero(browser, young):
    ctx, page, errors = _go(browser, young)
    try:
        page.wait_for_selector(".ss-sp3-compare:not([hidden]) .st-warn")
        for sel in (".ss-sp3-changes", ".ss-sp3-compare"):
            box = page.locator(sel)
            expect(box).to_contain_text("Date insuficiente")
            expect(box).to_contain_text("2")   # the days we do have
        assert page.locator(".ss-sp3-compare table").count() == 0   # no figures, no zero columns
        _bottom(page, '[data-sp3="heatmap"] .st-warn')
        expect(page.locator('[data-sp3="heatmap"]')).to_contain_text("Date insuficiente")
        assert page.locator('[data-sp3="heatmap"] svg').count() == 0
        assert errors == []
    finally:
        ctx.close()


def test_english_language_uses_the_dictionary(browser, full):
    ctx, page, errors = _go(browser, full)
    try:
        page.evaluate("window.I18N.setLang && window.I18N.setLang('en')")
        page.wait_for_selector(".ss-sp3-changes:not([hidden])")
        expect(page.locator(".ss-sp3-changes")).to_contain_text("What changed this week")
        assert errors == []
    finally:
        ctx.close()
