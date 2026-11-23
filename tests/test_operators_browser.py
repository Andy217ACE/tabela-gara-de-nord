# © 2026 Andy217Ace
"""Real browser: Statistici „Operatori și categorii” — the section, the R-E / R-M display of the
RE / RM codes, the matrix toggle, the operator click applying the filter, 360 px without horizontal
scroll and no console/CSP errors. Skipped without Chromium."""
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from app import stats_overview  # noqa: E402
from app.store import Store  # noqa: E402
from tests.test_statistici_browser import NO_HSCROLL, _open, _serve, browser  # noqa: E402,F401
from tests.test_stats_overview import add, seed  # noqa: E402

expect = sync_api.expect


@pytest.fixture(scope="module")
def ops_url(tmp_path_factory):
    db = tmp_path_factory.mktemp("opcat") / "o.db"
    s = Store(str(db))
    s.migrate()
    seed(s._conn)
    for i in range(6):
        add(s._conn, "departure", 1801, 14 + i, "09:00", i, operator="Softrans", ttype="RE", station="CLUJ")
    add(s._conn, "departure", 1802, 14, "11:00", 1, operator="Softrans", ttype="IR", station="CLUJ")
    for i in range(3):
        add(s._conn, "arrival", 1901, 14 + i, "10:00", i, operator="Regio Calatori", ttype="RM", station="PLOIESTI")
    s.close()
    stats_overview.clear_cache()
    server, t, url = _serve(db)
    yield url
    server.should_exit = True
    t.join(5)


def _go(browser, base_url, w=1280, theme="light"):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, w, 800, theme, "#statistici")
    page.wait_for_selector(".ss-fig[data-key='operatori-si-categorii'] .oc-card")
    return ctx, page, errors


@pytest.mark.parametrize("w,theme", [(1280, "light"), (360, "dark")])
def test_section_renders_and_fits(browser, ops_url, w, theme):
    ctx, page, errors = _go(browser, ops_url, w, theme)
    try:
        sec = page.locator(".ss-fig[data-key='operatori-si-categorii']")
        expect(sec.locator(".ss-fig-title")).to_have_text("Operatori și categorii")
        assert sec.locator(".oc-legend").first.inner_text().count("%") >= 2
        heads = sec.locator(".oc-table thead th").all_inner_texts()
        assert "R-E" in heads and "R-M" in heads and "RE" not in heads and "RM" not in heads
        expect(sec.locator(".oc-card-h", has_text="Regio-Expres")).to_have_count(1)
        expect(sec.locator(".oc-punct", has_text="Întârziere tipică").first).to_be_visible()
        assert page.evaluate(NO_HSCROLL)
        assert [c for c in page.locator(".c3-chip").all_inner_texts() if c == "Operatori și categorii"]
        assert errors == []
    finally:
        ctx.close()


def test_matrix_toggle(browser, ops_url):
    ctx, page, errors = _go(browser, ops_url)
    try:
        sec = page.locator(".ss-fig[data-key='operatori-si-categorii']")
        row = sec.locator(".oc-table tbody tr", has_text="Softrans")
        expect(row.locator("td").first).to_be_visible()
        before = row.locator("td").all_inner_texts()
        sec.locator(".ss-seg-opt", has_text="% din categorie").click()
        expect(sec.locator(".oc-table caption")).to_contain_text("fiecărui operator")
        after = row.locator("td").all_inner_texts()
        assert before != after
        assert errors == []
    finally:
        ctx.close()


def test_operator_click_applies_filter(browser, ops_url):
    ctx, page, errors = _go(browser, ops_url)
    try:
        page.locator(".oc-cards .oc-name", has_text="Softrans").click()
        page.wait_for_function("() => location.hash.includes('operator=Softrans')")
        expect(page.locator("#ss-operator")).to_have_value("Softrans")
        page.wait_for_selector(".oc-card-h:has-text('Softrans')")
        assert page.locator(".oc-cards").first.locator(".oc-card").count() == 1
        assert errors == []
    finally:
        ctx.close()
