# © 2026 Andy217Ace
"""Real-browser checks for the i18n module (web/i18n/i18n.js). The script is injected into a
plain served page (offline.html) so the tests do not depend on index.html wiring."""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)


def _open(browser, base_url, query="", init=None, ctx=None):  # noqa: F811
    ctx = ctx or browser.new_context(service_workers="block")
    if init:
        ctx.add_init_script(init)
    page = ctx.new_page()
    page.goto(base_url + "/offline.html" + query)
    page.add_script_tag(url=base_url + "/i18n/i18n.js")
    page.evaluate("() => window.I18N.ready")
    return ctx, page


def test_default_is_romanian_and_t_falls_back(browser, base_url):  # noqa: F811
    ctx, page = _open(browser, base_url)
    try:
        assert page.evaluate("I18N.lang()") == "ro"
        assert page.evaluate("I18N.t('test.hello')") == "Bună"
        assert page.evaluate("I18N.t('cheie.inexistenta')") == "cheie.inexistenta"
    finally:
        ctx.close()


def test_url_lang_en(browser, base_url):  # noqa: F811
    ctx, page = _open(browser, base_url, "?lang=en")
    try:
        assert page.evaluate("I18N.lang()") == "en"
    finally:
        ctx.close()


@pytest.mark.parametrize("query", ["?lang=fr", "?lang=", "?lang=%3Cscript%3Ealert(1)%3C/script%3E"])
def test_invalid_url_lang_falls_back_to_ro(browser, base_url, query):  # noqa: F811
    ctx = browser.new_context(service_workers="block")
    dialogs = []
    ctx.on("page", lambda p: p.on("dialog", lambda d: (dialogs.append(d), d.dismiss())))
    try:
        # even with a valid stored language, an invalid URL value goes straight to ro
        _, page = _open(browser, base_url, query, init="localStorage.setItem('tabela-lang','en');", ctx=ctx)
        assert page.evaluate("I18N.lang()") == "ro"
        assert dialogs == []
    finally:
        ctx.close()


def test_set_lang_persists_and_survives_reload(browser, base_url):  # noqa: F811
    ctx, page = _open(browser, base_url)
    try:
        page.evaluate("I18N.setLang('en')")
        assert page.evaluate("I18N.lang()") == "en"
        assert page.evaluate("localStorage.getItem('tabela-lang')") == "en"
        page.reload()
        page.add_script_tag(url=base_url + "/i18n/i18n.js")
        page.evaluate("() => window.I18N.ready")
        assert page.evaluate("I18N.lang()") == "en"
    finally:
        ctx.close()


def test_set_lang_rejects_invalid(browser, base_url):  # noqa: F811
    ctx, page = _open(browser, base_url, "?lang=en")
    try:
        page.evaluate("I18N.setLang('fr')")
        assert page.evaluate("I18N.lang()") == "ro"
    finally:
        ctx.close()


def test_set_lang_survives_throwing_storage(browser, base_url):  # noqa: F811
    init = "Object.defineProperty(window,'localStorage',{get(){throw new Error('blocked')}});"
    ctx, page = _open(browser, base_url, init=init)
    try:
        assert page.evaluate("I18N.lang()") == "ro"
        page.evaluate("I18N.setLang('en')")
        assert page.evaluate("I18N.lang()") == "en"
    finally:
        ctx.close()


def test_toggle_switches_language_and_url(browser, base_url):  # noqa: F811
    ctx = browser.new_context(service_workers="block", viewport={"width": 360, "height": 740})
    try:
        page = ctx.new_page()
        page.goto(base_url + "/")
        page.evaluate("() => window.I18N && window.I18N.ready")
        btn = page.locator(".navbar [data-lang-toggle]")
        assert btn.is_visible()
        assert page.evaluate("() => document.documentElement.scrollWidth") <= 360
        assert page.evaluate("document.documentElement.lang") == "ro"
        btn.click()
        page.wait_for_function("() => document.documentElement.lang === 'en'")
        assert page.evaluate("I18N.lang()") == "en"
        assert "lang=en" in page.url
        assert page.evaluate("document.documentElement.lang") == "en"
        assert page.evaluate("() => document.documentElement.scrollWidth") <= 360
    finally:
        ctx.close()


def _board_page(browser, base_url, query, view="panou", width=1280, height=800):
    ctx = browser.new_context(viewport={"width": width, "height": height}, service_workers="block")
    ctx.add_init_script("localStorage.setItem('tabela.view','%s');" % view)
    page = ctx.new_page()
    page.goto(base_url + "/" + query)
    page.wait_for_selector(".pnl-row" if view == "panou" else ".train:not(.skeleton)")
    return ctx, page


def test_board_in_english(browser, base_url):  # noqa: F811
    ctx, page = _board_page(browser, base_url, "?lang=en")
    try:
        assert "ARRIVALS" in page.text_content("#pnl-title")
        msgs = [m.strip() for m in page.locator(".pnl-row .c-msg").all_text_contents()]
        assert any(m.startswith("delayed") for m in msgs), msgs
        labels = page.eval_on_selector_all(".pnl-row .pnl-delay", "els => els.map(e => e.getAttribute('aria-label'))")
        assert any(l and l.startswith("Delayed ") and l.endswith(" minutes") for l in labels), labels
        page.click(".pnl-boardseg [data-board=departures]")
        assert "DEPARTURES" in page.text_content("#pnl-title")
        assert "trains shown" in page.text_content(".pnl-status")
        assert page.inner_text(".navbar [data-route=tabela]") == "Board"
    finally:
        ctx.close()


def test_board_in_romanian(browser, base_url):  # noqa: F811
    ctx, page = _board_page(browser, base_url, "?lang=ro")
    try:
        assert "SOSIRI" in page.text_content("#pnl-title")
        msgs = [m.strip() for m in page.locator(".pnl-row .c-msg").all_text_contents()]
        assert any(m.startswith("întârziat") for m in msgs), msgs
        labels = page.eval_on_selector_all(".pnl-row .pnl-delay", "els => els.map(e => e.getAttribute('aria-label'))")
        # Romanian plural: 5 -> "minute", 20 -> "de minute"
        assert any(l == "Întârziere 5 minute" for l in labels), labels
        assert any(l == "Întârziere 20 de minute" for l in labels), labels
        assert "trenuri afișate" in page.text_content(".pnl-status")
    finally:
        ctx.close()


def test_board_rerenders_on_language_change(browser, base_url):  # noqa: F811
    ctx, page = _board_page(browser, base_url, "?lang=ro")
    try:
        assert "SOSIRI" in page.text_content("#pnl-title")
        page.click(".navbar [data-lang-toggle]")
        page.wait_for_function("() => document.querySelector('#pnl-title').textContent.includes('ARRIVALS')")
        assert "Delayed" in page.eval_on_selector_all(
            ".pnl-row .pnl-delay", "els => els.map(e => e.getAttribute('aria-label')).join('|')")
        assert page.inner_text("#tab-departures") .strip().startswith("Departures")
        assert page.get_attribute("#panel-root .pnl-switch", "aria-label") == "Display mode"
        page.click(".navbar [data-lang-toggle]")
        page.wait_for_function("() => document.querySelector('#pnl-title').textContent.includes('SOSIRI')")
        assert page.inner_text("#tab-departures").strip().startswith("Plecări")
    finally:
        ctx.close()


@pytest.mark.parametrize("view", ["panou", "carduri"])
def test_board_english_fits_360(browser, base_url, view):  # noqa: F811
    ctx, page = _board_page(browser, base_url, "?lang=en", view=view, width=360, height=740)
    try:
        page.wait_for_timeout(300)
        width = page.evaluate("() => document.documentElement.scrollWidth")
        print("scrollWidth(en,%s,360px)=%s" % (view, width))
        assert width <= 360
        if view == "carduri":
            assert page.locator(".train:not(.skeleton) .follow span").first.text_content() == "follow"
    finally:
        ctx.close()
