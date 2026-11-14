# © 2026 Andy217Ace
"""Real-browser checks for the i18n module (web/i18n/i18n.js). The script is injected into a
plain served page (offline.html) so the tests do not depend on index.html wiring."""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)
import pytest as _pytest
from app import stats_overview
from app.store import Store
from tests.test_stats_overview import seed, weather
from tests.test_statistici_browser import _serve


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



RO_DIACRITICS = "ăîâșțĂÎÂȘȚşţŞŢ"


@_pytest.fixture(scope="module")
def stats_url(tmp_path_factory):
    db = tmp_path_factory.mktemp("i18n_stats") / "s.db"
    s = Store(str(db))
    s.migrate()
    seed(s._conn)
    for day in range(14, 21):
        weather(s._conn, day, 12, 9.0, 0.0)
    s.close()
    stats_overview.clear_cache()
    server, t, url = _serve(db)
    yield url
    server.should_exit = True
    t.join(5)


def _stats_page(browser, url, lang):
    stats_overview.clear_cache()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, service_workers="block")
    page = ctx.new_page()
    page.goto(url + "/?lang=" + lang + "#statistici")
    page.wait_for_selector(".ss-fig .ss-fig-title")
    page.evaluate("() => window.I18N.ready")
    return ctx, page


def test_stats_labels_and_decimal_separator(browser, stats_url):  # noqa: F811
    ctx, page = _stats_page(browser, stats_url, "en")
    try:
        titles = page.eval_on_selector_all(".ss-fig .ss-fig-title", "els => els.map(e => e.textContent.trim())")
        assert "How late are the trains?" in titles, titles
        assert "At what hour are trains the most late?" in titles, titles
        # every chart title that we own is English (server-sent texts stay Romanian, see the spec)
        own = [t for t in titles if any(c in t for c in RO_DIACRITICS)]
        assert not own, own
        assert page.locator(".ss-filters legend").first.text_content().strip() == "Period"
        assert page.locator(".ss-fig .ss-how strong").first.text_content().strip() == "How to read:"
        # decimals: English dot, via Intl (statistici formatters + charts3 formatter)
        assert page.evaluate("TabelaApp.stats.numFmt.format(12.5)") == "12.5"
        assert page.evaluate("TabelaApp.charts3.fmt.format(12.5)") == "12.5"
        assert page.evaluate("TabelaApp.stats.pl(1, 'stats.w.journey')") == "1 journey"
        assert page.evaluate("TabelaApp.stats.pl(3, 'stats.w.journey')") == "3 journeys"
        # chart-legend / table labels are English too
        assert "Arrivals" in page.text_content(".ss-legend")
        assert page.locator(".c3-chip").count() >= 3
    finally:
        ctx.close()
    ctx, page = _stats_page(browser, stats_url, "ro")
    try:
        titles = page.eval_on_selector_all(".ss-fig .ss-fig-title", "els => els.map(e => e.textContent.trim())")
        assert "Cât de mult întârzie trenurile?" in titles, titles
        assert page.evaluate("TabelaApp.stats.numFmt.format(12.5)") == "12,5"
        assert page.evaluate("TabelaApp.charts3.fmt.format(12.5)") == "12,5"
        assert page.evaluate("TabelaApp.stats.pl(1, 'stats.w.journey')") == "1 călătorie"
        assert "Sosiri" in page.text_content(".ss-legend")
    finally:
        ctx.close()


def test_stats_switch_language_redraws_charts(browser, stats_url):  # noqa: F811
    ctx, page = _stats_page(browser, stats_url, "ro")
    try:
        assert "Cât de mult întârzie trenurile?" in page.text_content("#st-statistici")
        page.evaluate("I18N.setLang('en')")
        page.wait_for_function("() => document.querySelector('.ss-filters legend') && document.querySelector('.ss-filters legend').textContent === 'Period'")
        page.wait_for_selector(".ss-fig .ss-fig-title")
        assert "How late are the trains?" in page.text_content("#st-statistici")
        # the share link of a chart keeps the same (Romanian-derived) key in both languages
        keys = page.eval_on_selector_all(".ss-fig", "els => els.map(e => e.getAttribute('data-key'))")
        assert "cat-de-mult-intarzie-trenurile" in keys, keys
    finally:
        ctx.close()


def _journeys(n):
    js = [{"id": i + 1, "board": "arrival", "train_type": "IR", "train_no": 1636 + i, "station": "BRASOV",
           "sched_time": "10:0%d" % i, "service_date": "2026-11-10", "max_read_delay": 0, "platform": "3",
           "result": {"state": "unknown"}} for i in range(n)]
    return {"total": n, "journeys": js, "next": "x" if n == 2 else None,
            "period": {"first": "2026-11-10", "last": "2026-11-10", "days": 1}, "params": {}, "summary": {}}


def test_history_and_follows_in_english(browser, base_url):  # noqa: F811
    import json
    ctx = browser.new_context(service_workers="block", viewport={"width": 1100, "height": 800})
    try:
        page = ctx.new_page()
        state = {"n": 1}
        page.route("**/api/history?**", lambda r: r.fulfill(
            status=200, content_type="application/json", body=json.dumps(_journeys(state["n"]))))
        page.goto(base_url + "/?lang=en#istoric")
        page.evaluate("() => window.I18N.ready")
        page.wait_for_function("() => document.querySelector('#h-count').textContent.includes('journey')")
        assert page.locator("#istoric-heading").inner_text() == "History"
        assert page.locator("#h-more").text_content() == "Load more"
        assert page.locator("#h-count").inner_text().startswith("1 journey")
        assert "1 journeys" not in page.locator("#h-count").inner_text()
        state["n"] = 2
        page.fill("#h-train", "1636")
        page.wait_for_function("() => document.querySelector('#h-count').textContent.startsWith('Train 1636: 2 journeys')")
        # follows: plural keys picked by Intl.PluralRules
        assert page.evaluate("() => TabelaApp.follows.countLabel(1)") == "1 train followed"
        assert page.evaluate("() => TabelaApp.follows.countLabel(2)") == "2 trains followed"
        page.evaluate("() => { location.hash = '#urmarite'; }")
        page.wait_for_function("() => document.querySelector('#urmarite-heading').textContent === 'Followed trains'")
        # Romanian stays the default and keeps its own plural forms
        page.goto(base_url + "/?lang=ro#urmarite")
        page.evaluate("() => window.I18N.ready")
        assert page.evaluate("() => TabelaApp.follows.countLabel(2)") == "2 trenuri urmărite"
        assert page.evaluate("() => TabelaApp.follows.countLabel(1)") == "1 tren urmărit"
    finally:
        ctx.close()


def test_invalid_stored_value_falls_back_to_ro(browser, base_url):  # noqa: F811
    ctx, page = _open(browser, base_url, init="localStorage.setItem('tabela-lang','xx');")
    try:
        assert page.evaluate("I18N.lang()") == "ro"
    finally:
        ctx.close()


def test_offline_page_in_english_from_cache(browser, base_url):  # noqa: F811
    ctx = browser.new_context(service_workers="allow")
    ctx.add_init_script("localStorage.setItem('tabela-lang','en');")
    try:
        page = ctx.new_page()
        page.goto(base_url + "/offline.html")
        page.evaluate("navigator.serviceWorker.register('/sw.js', {scope: '/'})")
        page.evaluate("navigator.serviceWorker.ready.then(() => 0)")
        page.reload()  # now controlled by the service worker
        page.evaluate("fetch('/i18n/en.json').then(r => r.status)")  # runtime-cached by the SW
        import re
        from pathlib import Path
        sw = (Path(__file__).resolve().parent.parent / "web" / "sw.js").read_text(encoding="utf-8")
        sw_version = re.search(r'var VERSION = "([^"]+)"', sw).group(1)
        page.wait_for_function(
            "v => caches.open('tabela-shell-' + v).then(c => c.match('/i18n/en.json')).then(Boolean)", arg=sw_version)
        ctx.set_offline(True)
        page.goto(base_url + "/offline.html")
        page.wait_for_function("document.documentElement.lang === 'en'")
        assert page.inner_text("h1") == "You are offline"
        assert page.inner_text(".offline-retry") == "Try again"
        assert page.title() == "Offline · Tabela Gara de Nord"
        assert "Sigla" not in page.get_attribute(".logo-offline", "alt")
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
