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


def _mock_admin(page, apply_status=422):
    """Pretend to be a signed-in admin; the dupes `apply` call fails with a Romanian API detail."""
    detail = "Confirmarea nu corespunde cererii (mesaj din API)."

    def handler(route):
        url = route.request.url
        if url.endswith("/api/admin/session"):
            body = {"enabled": True, "authenticated": True}
        elif url.endswith("/api/admin/csrf"):
            body = {"token": "t"}
        elif url.endswith("/api/admin/tools/dupes/apply"):
            route.fulfill(status=apply_status, content_type="application/json",
                          body='{"detail": "%s"}' % detail)
            return
        elif url.endswith("/api/admin/tools/dupes"):
            body = {"report": {"merge": {"list": []}}, "generated_at": None}
        else:
            body = {}
        route.fulfill(status=200, content_type="application/json", body=__import__("json").dumps(body))

    page.route("**/api/admin/**", handler)
    return detail


def test_admin_in_english_with_romanian_fallback(browser, base_url):  # noqa: F811
    ctx = browser.new_context(service_workers="block")
    page = ctx.new_page()
    try:
        detail = _mock_admin(page)
        page.goto(base_url + "/?lang=en#admin")
        page.wait_for_selector("#admin-dupes")
        assert page.inner_text("#admin-heading") == "Administration"
        assert page.inner_text("#admin-dupes h2") == "Duplicate train numbers"
        assert "Sign out" in page.inner_text("#admin-body")
        page.click("#admin-dupes .admin-actions button:nth-child(2)")  # "Apply the merge…"
        page.fill("#admin-confirm input", "APLICA")
        page.click("#admin-confirm button[type=submit]")
        page.wait_for_function("() => !document.getElementById('admin-msg').hidden")
        # the message from the API stays as the server sent it (Romanian), no raw key
        assert page.inner_text("#admin-msg") == detail
        assert page.evaluate(r"() => /admin\.[a-z]+\.[A-Za-z]+/.test(document.getElementById('view-admin').innerText)") is False
        # switching to Romanian rebuilds the page in Romanian
        page.evaluate("I18N.setLang('ro')")
        page.wait_for_function("() => document.getElementById('admin-heading') && document.getElementById('admin-heading').textContent === 'Administrare'")
    finally:
        ctx.close()


def test_ocr_and_system_titles_in_english(browser, base_url):  # noqa: F811
    ctx = browser.new_context(service_workers="block")
    page = ctx.new_page()
    try:
        _mock_admin(page)
        page.route("**/api/system", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body='{"stare": "live", "poller": {"last_ok_age_s": 30}, "ocr": {}, "disk": {}, "db": {}}'))
        page.goto(base_url + "/?lang=en#ocr")
        page.wait_for_selector("#ocr-heading")
        assert page.inner_text("#ocr-heading") == "OCR captures"
        page.goto(base_url + "/?lang=en#sistem")
        page.wait_for_selector("#sistem-heading")
        assert page.inner_text("#sistem-heading") == "System"
        page.wait_for_selector(".sys-badge")
        assert "Last successful read" in page.inner_text("#sys-body")
    finally:
        ctx.close()
