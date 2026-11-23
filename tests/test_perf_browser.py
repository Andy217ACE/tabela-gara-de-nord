# © 2026 Andy217Ace
"""Real browser: graphics plan, Phase 1 (speed & stability). Page stylesheets load with their page (the
board never waits for stats.css / statistici.css), a heavy page drops its DOM when left (navigation does
not pile up nodes), Trenuri draws 50 rows + „Încarcă încă 50” (sorting still over every row), Istoric
asks for 50 journeys at a time, and Statistici builds its chart sections near the screen (TOC first).
Skipped without Chromium."""
import pytest

pytest.importorskip("playwright.sync_api")

from app import stats_overview  # noqa: E402
from app.store import Store  # noqa: E402
from tests.test_stats_overview import add  # noqa: E402
from tests.test_statistici_browser import _open, _serve, browser  # noqa: E402,F401

NODES = "() => document.getElementsByTagName('*').length"


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    """3 days x 35 trains x 2 boards = 70 Trenuri rows (more than one page of 50)."""
    db = tmp_path_factory.mktemp("perf") / "p.db"
    st = Store(str(db))
    st.migrate()
    for day in (1, 2, 3):
        for i in range(35):
            for board, first in (("arrival", 1601), ("departure", 1701)):
                add(st._conn, board, first + i, day, f"{5 + i % 18:02d}:{(i * 7) % 60:02d}", (i * 3 + day) % 40,
                    station=["BRASOV", "CONSTANTA", "GALATI"][i % 3], platform=1 + i % 9)
    st._conn.commit()
    st.close()
    stats_overview.clear_cache()
    server, t, url = _serve(db)
    yield url
    server.should_exit = True
    t.join(5)


def _until(page, expr, timeout=10000):
    for _ in range(timeout // 100):
        if page.evaluate(expr):
            return True
        page.wait_for_timeout(100)
    raise AssertionError("timed out waiting for: " + expr)


def _go(page, h):
    page.evaluate("h => { location.hash = h; }", h)


def test_page_css_loads_with_its_page_before_ui2(browser, base_url):
    ctx, page, errors = _open(browser, base_url, 412, 900, "dark", "#tabela", eager=False)
    try:
        page.wait_for_selector("#boot", state="hidden")
        sheets = "() => [...document.querySelectorAll('link[rel=stylesheet]')].map(l => l.getAttribute('href'))"
        first = page.evaluate(sheets)
        assert "stats.css" not in first and "statistici.css" not in first   # the board never blocks on them
        _go(page, "#statistici")
        page.wait_for_selector("#st-statistici .ss-problems, #st-statistici .ss-fig, #st-statistici .ss-quick")
        now = page.evaluate(sheets)
        assert now.index("stats.css") < now.index("statistici.css") < now.index("ui2.css")   # same cascade as before
        # styled when shown (no FOUC): the stats grid rule is already applied
        assert page.evaluate("() => getComputedStyle(document.querySelector('#st-statistici .ss-body')).display") == "grid"
        _go(page, "#trenuri")
        page.wait_for_selector("#st-trenuri .st-table")
        assert page.evaluate(sheets).count("stats.css") == 1   # loaded once
        assert not errors, errors
    finally:
        ctx.close()


def test_deep_link_shows_its_page_not_the_board_first(browser, base_url):
    ctx, page, errors = _open(browser, base_url, 412, 900, "dark", "#trenuri")
    try:
        page.wait_for_selector("#st-trenuri .st-table")
        assert page.evaluate("() => document.getElementById('view-tabela').hidden")
        assert page.evaluate("() => !document.documentElement.hasAttribute('data-deeplink')")
        assert not errors, errors
    finally:
        ctx.close()


def test_views_release_their_dom_when_left(browser, base_url):
    ctx, page, errors = _open(browser, base_url, 412, 900, "dark", "#tabela", eager=False)
    try:
        page.wait_for_selector("#boot", state="hidden")
        start = page.evaluate(NODES)
        for h, ready in (("#istoric", "#h-results .h-row"), ("#trenuri", "#st-trenuri .st-row"),
                         ("#statistici", "#st-statistici .ss-problems, #st-statistici .ss-quick"),
                         ("#statie?nume=BRASOV", "#st-statie .st-body > *"), ("#tren?nr=1601", "#st-tren .st-body > *")):
            _go(page, h)
            page.wait_for_selector(ready)
        _go(page, "#tabela")
        page.wait_for_timeout(300)
        for root in ("st-trenuri", "st-statistici", "st-statie", "st-tren", "h-results"):
            assert page.evaluate("id => document.getElementById(id).children.length", root) == 0, root
        assert page.evaluate(NODES) < start + 400   # the board page is back to about its own size
        # back again: drawn from the cached data, filters kept
        _go(page, "#trenuri")
        page.wait_for_selector("#st-trenuri .st-row")
        assert not errors, errors
    finally:
        ctx.close()


def test_trenuri_load_more_50_and_sort_over_all_rows(browser, base_url):
    ctx, page, errors = _open(browser, base_url, 412, 900, "dark", "#trenuri")
    try:
        page.wait_for_selector("#st-trenuri .st-row")
        rows = "() => document.querySelectorAll('#st-trenuri tbody .st-row').length"
        assert page.evaluate(rows) == 50
        more = page.locator("#st-trenuri .st-more-btn")
        assert more.is_visible() and more.text_content().strip() == "Încarcă încă 20"
        assert "50 din 70" in page.locator("#st-trenuri .st-tr-shown").text_content()
        # sorting by train number ascending: the first row is the smallest number of ALL 70 rows
        page.locator("#st-trenuri .st-sort", has_text="Tren").first.click()
        page.wait_for_timeout(200)
        assert page.evaluate(rows) == 50
        first = page.evaluate("() => document.querySelector('#st-trenuri tbody .st-row td').textContent")
        assert "1601" in first
        more = page.locator("#st-trenuri .st-more-btn")
        more.focus()
        page.keyboard.press("Enter")   # keyboard works (a real <button>)
        page.wait_for_timeout(200)
        assert page.evaluate(rows) == 70
        assert not more.is_visible()
        assert page.evaluate("() => document.activeElement.classList.contains('st-scroll')")   # focus not lost to <body>
        assert not errors, errors
    finally:
        ctx.close()


def test_istoric_asks_for_50_at_a_time(browser, base_url):
    ctx, page, errors = _open(browser, base_url, 412, 900, "dark", "#tabela", eager=False)
    asked = []
    page.on("request", lambda r: asked.append(r.url) if "/api/history?" in r.url else None)
    try:
        _go(page, "#istoric")
        page.wait_for_selector("#h-results .h-row")
        assert page.evaluate("() => document.querySelectorAll('#h-results .h-row').length") == 50
        assert any("limit=50" in u for u in asked), asked
        btn = page.locator("#h-more")
        assert btn.is_visible() and btn.text_content().strip() == "Încarcă încă 50"
        btn.click()
        _until(page, "document.querySelectorAll('#h-results .h-row').length === 100")
        assert not errors, errors
    finally:
        ctx.close()


def test_statistici_builds_chart_sections_near_the_screen(browser, base_url):
    ctx, page, errors = _open(browser, base_url, 412, 900, "dark", "#statistici", eager=False)
    try:
        page.wait_for_selector("#st-statistici .ss-defer-ph")
        page.wait_for_selector("#st-statistici .c3-toc .c3-chip")
        waiting = "() => document.querySelectorAll('#st-statistici .ss-defer-ph').length"
        assert page.evaluate(waiting) > 3   # the lower sections are not built at first
        # a TOC chip of a section not built yet: everything is built and the page jumps to the real section
        page.locator("#st-statistici .c3-chip", has_text="Ore").first.click()
        _until(page, "!document.querySelector('#st-statistici .ss-defer-ph')")
        _until(page, "(() => { const f = [...document.querySelectorAll('#st-statistici .ss-fig')]"
                     ".find(x => x.querySelector('.ss-fig-title').textContent.includes('oră'));"
                     " return f && Math.abs(f.getBoundingClientRect().top) < 400; })()")
        assert page.evaluate("() => document.querySelectorAll('svg.c3-bound').length") > 3   # built sections are enhanced
        assert not errors, errors
    finally:
        ctx.close()
