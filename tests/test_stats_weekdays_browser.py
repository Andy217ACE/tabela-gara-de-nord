# © 2026 Andy217Ace
"""Browser real: „Comparație pe zilele săptămânii" pe #statistici — ramura „date insuficiente"
(o săptămână de date: mesajul + săptămânile acumulate) și ramura cu prag atins (4 luni complete),
light/dark, 1280 și 390, fără erori de consolă/CSP și fără scroll orizontal. Sărit fără Chromium."""
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from app import stats_overview  # noqa: E402
from app.store import Store  # noqa: E402
from tests.test_stats_overview import add, seed  # noqa: E402
from tests.test_statistici_browser import NO_HSCROLL, _open, _serve, browser  # noqa: E402,F401


@pytest.fixture(scope="module")
def ok_url(tmp_path_factory):
    db = tmp_path_factory.mktemp("wd") / "w.db"
    s = Store(str(db))
    s.migrate()
    seed(s._conn)
    for i, day in enumerate((5, 12, 19, 26)):      # patru luni (octombrie 2026), toate încheiate
        for k, d in enumerate((0, 2, 10, 40, 3, 1)):
            add(s._conn, "arrival", 7000 + i * 10 + k, day, "12:00", d)
    s._conn.commit()
    s.close()
    stats_overview.clear_cache()
    server, t, url = _serve(db)
    yield url
    server.should_exit = True
    t.join(5)


@pytest.fixture(scope="module")
def few_url(tmp_path_factory):
    db = tmp_path_factory.mktemp("wd2") / "f.db"
    s = Store(str(db))
    s.migrate()
    seed(s._conn)
    s.close()
    stats_overview.clear_cache()
    server, t, url = _serve(db)
    yield url
    server.should_exit = True
    t.join(5)


def _fig(page):
    page.wait_for_selector(".ss-fig")
    return page.locator(".ss-fig", has=page.locator("h2", has_text="zilele săptămânii"))


@pytest.mark.parametrize("w,h", [(1280, 800), (390, 844)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_collecting_branch(browser, few_url, w, h, theme):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, few_url, w, h, theme, "#statistici")
    try:
        fig = _fig(page)
        text = fig.text_content()
        assert "Comparația va deveni valabilă după ~4 săptămâni de date" in text
        assert "Săptămâni acumulate:" in text
        assert fig.locator("table").count() == 0            # fără grafic/tabel înșelător
        assert page.evaluate(NO_HSCROLL)
        assert errors == []
    finally:
        ctx.close()


@pytest.mark.parametrize("w,h", [(1280, 800), (390, 844)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_ok_branch(browser, ok_url, w, h, theme):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, ok_url, w, h, theme, "#statistici")
    try:
        fig = _fig(page)
        t = fig.locator("table").first
        assert "Comparația va deveni valabilă" not in fig.text_content()
        assert "luni" in t.text_content().lower()
        assert "date insuficiente" in t.text_content()      # celelalte zile
        assert "%" in t.locator("tbody tr").first.text_content()
        assert page.evaluate(NO_HSCROLL)
        assert errors == []
    finally:
        ctx.close()
