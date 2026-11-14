# © 2026 Andy217Ace
"""Real-browser checks for the i18n module (web/i18n/i18n.js). The script is injected into a
plain served page (offline.html) so the tests do not depend on index.html wiring."""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)


def _open(browser, base_url, query="", stored=None):  # noqa: F811
    ctx = browser.new_context(service_workers="block")
    if stored:
        ctx.add_init_script(f"localStorage.setItem('tabela-lang', '{stored}');")
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
