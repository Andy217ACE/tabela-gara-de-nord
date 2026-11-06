# © 2026 Andy217Ace
"""Coloana „Peron estimat" din tabela principală: comutator implicit oprit, tabela identică
cu coloana ascunsă, valori doar peste prag, persistență, light/dark, 360 și 1280 px, fără
scroll orizontal / erori CSP. Sărit fără Chromium."""
from datetime import datetime, timedelta

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from app.store import TZ, Store  # noqa: E402
from scripts.contrast_audit import AUDIT_JS  # noqa: E402
from tests.test_peron_api import _obs, _svc  # noqa: E402
from tests.test_statistici_browser import NO_HSCROLL, _serve, browser  # noqa: E402,F401


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    db = tmp_path_factory.mktemp("peronest") / "p.db"
    s = Store(str(db))
    s.migrate()
    c = s._conn
    today = datetime.now(TZ).date()
    for k in range(1, 7):
        d = (today - timedelta(days=k)).isoformat()
        for base, plats in ((0, [4, 4, 4, 4, 4, 6]), (100, [3, 5, 3, 5, 3, 5]),
                            (300, [4] * 6)):
            no = {0: 100, 100: 200, 300: 300}[base]
            _svc(c, base + k, no, d, plats[k - 1], board="arrival")
            _obs(c, base + k, no, plats[k - 1], board="arrival")
    t = today.isoformat()
    _svc(c, 900, 100, t, None, status="listed", board="arrival")   # estimat: 4 · 83%
    _svc(c, 901, 200, t, None, status="listed", board="arrival")   # sub prag: —
    _svc(c, 902, 300, t, 7, status="listed", board="arrival")      # peron anunțat: —
    c.commit()
    s.close()
    server, th, url = _serve(db)
    yield url
    server.should_exit = True
    th.join(5)


def _open(browser, base_url, w, h, theme, view="carduri"):
    ctx = browser.new_context(viewport={"width": w, "height": h}, service_workers="block")
    ctx.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}');"
                        f"localStorage.setItem('tabela.view', '{view}');")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base_url + "/")
    return ctx, page, errors


def _board(page):
    page.wait_for_selector("#list-arrivals .train:not(.skeleton)")
    return page


def _shown(page):
    """Coloana e afișată și estimările au sosit (celula tren 100 are 83%)."""
    page.wait_for_function("() => [...document.querySelectorAll('#list-arrivals .pe-val')]"
                           ".some(e => e.textContent.includes('83%'))")


def _geometry(page):
    return page.evaluate("""() => [...document.querySelectorAll('#list-arrivals .train')].map(
        li => { const r = li.getBoundingClientRect(); const p = li.querySelector('.plat').getBoundingClientRect();
                return [Math.round(r.width), Math.round(r.height), Math.round(p.left), Math.round(p.top)]; })""")


def _cells(page):
    return page.evaluate("""() => [...document.querySelectorAll('#list-arrivals .train')].map(li => {
        const c = li.querySelector('.pe-cell');
        return { no: li.querySelector('.t-no, .no') ? li.querySelector('.t-no, .no').textContent : '',
                 visible: !!c && c.getBoundingClientRect().width > 0, text: c ? c.textContent : null,
                 label: c ? c.getAttribute('aria-label') : null }; })""")


@pytest.mark.parametrize("w,h", [(360, 740), (1280, 800)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_toggle_off_by_default_and_table_unchanged(browser, base_url, w, h, theme):
    ctx, page, errors = _open(browser, base_url, w, h, theme)
    requests = []
    page.on("request", lambda r: requests.append(r.url))
    try:
        _board(page)
        toggle = page.locator("#pe-toggle")
        assert toggle.count() == 1 and not toggle.is_checked()
        assert "Arată peron estimat" in page.locator("label[for=pe-toggle]").text_content()
        before = _geometry(page)
        assert not any(c["visible"] for c in _cells(page))
        assert not any("/api/predict/peron" in u or "peron_est" in u for u in requests)  # nimic cerut cât e oprit
        assert page.evaluate(NO_HSCROLL)
        toggle.check()
        _shown(page)
        assert page.evaluate(NO_HSCROLL)
        toggle.uncheck()
        page.wait_for_timeout(200)
        assert _geometry(page) == before          # exact ca înainte: fără spațiu rămas
        assert not any(c["visible"] for c in _cells(page))
        assert errors == []
    finally:
        ctx.close()


@pytest.mark.parametrize("w,h", [(360, 740), (1280, 800)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_column_values_labels_and_contrast(browser, base_url, w, h, theme):
    ctx, page, errors = _open(browser, base_url, w, h, theme)
    try:
        _board(page)
        page.locator("#pe-toggle").check()
        _shown(page)
        cells = _cells(page)
        assert len(cells) == 3 and all(c["visible"] for c in cells)
        texts = sorted(c["text"] for c in cells)
        est = [t for t in texts if "83%" in t]
        assert len(est) == 1 and "4" in est[0]
        assert sum(1 for t in texts if t.strip().endswith("—")) == 2   # sub prag + peron anunțat
        for c in cells:                                              # eticheta de estimare peste tot
            assert "estimare din istoricul observat, nu informație oficială CFR" in c["label"]
        assert "estimare" in page.locator("#pe-note").text_content().lower()
        assert "nu informație oficială CFR" in page.locator("#pe-note").text_content()
        assert page.evaluate(NO_HSCROLL)
        bad = page.evaluate(AUDIT_JS)
        assert not [f for f in bad if page.evaluate(
            "(t) => [...document.querySelectorAll('.pe-cell *, #pe-note, .pe-toggle *')].some("
            "e => e.textContent.trim().startsWith(t))", (f["text"] or "zzz")[:12])], bad
        assert errors == []
    finally:
        ctx.close()


def test_choice_persists_and_page_works_without_storage(browser, base_url):
    ctx, page, errors = _open(browser, base_url, 360, 740, "light")
    try:
        _board(page)
        page.locator("#pe-toggle").check()
        page.reload()
        _board(page)
        assert page.locator("#pe-toggle").is_checked()
        _shown(page)
        page.locator("#pe-toggle").uncheck()
        page.reload()
        _board(page)
        assert not page.locator("#pe-toggle").is_checked()
        assert errors == []
    finally:
        ctx.close()
    # fără localStorage: pagina merge, comutatorul rămâne oprit și funcțional în sesiune
    ctx = browser.new_context(viewport={"width": 360, "height": 740}, service_workers="block")
    ctx.add_init_script("Object.defineProperty(window, 'localStorage',"
                        " { get() { throw new Error('blocat'); } });")
    page = ctx.new_page()
    page.goto(base_url + "/")
    try:
        _board(page)
        assert not page.locator("#pe-toggle").is_checked()
        page.locator("#pe-toggle").check()
        _shown(page)
    finally:
        ctx.close()


# --- Panou (tabelul din modul „Panou", implicit pe desktop) ------------------------------

PANEL_PEST = "() => [...document.querySelectorAll('.pnl-board[data-board=arrivals] .pnl-row')].map("     "r => { const c = r.querySelector('.c-pest'); return c && c.getBoundingClientRect().width > 0 "     "? c.textContent.trim() : null; })"
PANEL_GEOM = "() => [...document.querySelectorAll('.pnl-board[data-board=arrivals] .pnl-row')].map("     "r => { const b = r.getBoundingClientRect(); const p = r.querySelector('.c-plat').getBoundingClientRect(); "     "return [Math.round(b.width), Math.round(b.height), Math.round(p.left - b.left), Math.round(p.top - b.top)]; })"


def _panel_ready(page):
    page.wait_for_selector(".pnl-board[data-board=arrivals] .pnl-row")


@pytest.mark.parametrize("w,h", [(360, 740), (1280, 800)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_panel_column_off_by_default_then_toggle(browser, base_url, w, h, theme):
    ctx, page, errors = _open(browser, base_url, w, h, theme, "panou")
    requests = []
    page.on("request", lambda r: requests.append(r.url))
    try:
        _panel_ready(page)
        before = page.evaluate(PANEL_GEOM)
        assert page.evaluate(PANEL_PEST) == [None, None, None]        # ascunsă: nicio urmă
        assert not any("/api/predict/peron" in u or "peron_est" in u for u in requests)
        assert page.evaluate(NO_HSCROLL)
        page.locator(".pnl-cols > summary").click()
        box = page.locator("#pnl-col-pest")
        assert not box.is_checked()
        assert "Arată peron estimat" in page.locator("label.pnl-check", has=box).text_content()
        box.check()
        page.wait_for_function("() => [...document.querySelectorAll('.c-pest')].some("
                               "e => e.textContent.includes('83%'))")
        got = page.evaluate(PANEL_PEST)
        assert sorted(got) == ["4 · 83%", "—", "—"]
        th = page.locator(".pnl-board[data-board=arrivals] th.c-pest")
        assert "nu informație oficială CFR" in th.get_attribute("title")
        assert page.evaluate(NO_HSCROLL)
        bad = page.evaluate(AUDIT_JS)
        assert not [f for f in bad if page.evaluate(
            "(t) => [...document.querySelectorAll('.c-pest *')].some(e => e.textContent.trim().startsWith(t))",
            (f["text"] or "zzz")[:6])], bad
        page.reload()                                                   # persistență
        _panel_ready(page)
        page.wait_for_function("() => [...document.querySelectorAll('.c-pest')].some("
                               "e => e.textContent.includes('83%'))")
        page.locator(".pnl-cols > summary").click()
        page.locator("#pnl-col-pest").uncheck()
        page.wait_for_timeout(200)
        assert page.evaluate(PANEL_PEST) == [None, None, None]
        assert page.evaluate(PANEL_GEOM) == before                      # exact ca înainte
        assert errors == []
    finally:
        ctx.close()
