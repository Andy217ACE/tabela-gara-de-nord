# © 2026 Andy217Ace
"""Real browser: Statistici v2 (#statistici) at 1280×800 and 390×844, light/dark — summary
in words, the charts with legend / N / „Vezi datele”, filters in the URL, no console/CSP
errors, no horizontal scroll, nothing outside the viewport, exactly one footer; an empty
database shows the explicit „date insuficiente” message. Skipped without Chromium."""
import socket
import threading
import time

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

import uvicorn  # noqa: E402

from app import stats_overview  # noqa: E402
from app.api import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.store import Store  # noqa: E402
from tests.test_footer_browser import COUNT_JS  # noqa: E402
from tests.test_stats_overview import seed, weather  # noqa: E402

expect = sync_api.expect


def _serve(db):
    settings = Settings(db_path=str(db), source_url="http://127.0.0.1:9/none",
                        vapid_private_key="", vapid_public_key="", vapid_subject="mailto:a@b.c",
                        tesseract_cmd="tesseract", poller_enabled=False, last_image_path=None)
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings, start_poller=False),
                                           host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server, t, f"http://127.0.0.1:{port}"


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    db = tmp_path_factory.mktemp("stats2") / "s.db"
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


@pytest.fixture(scope="module")
def empty_url(tmp_path_factory):
    db = tmp_path_factory.mktemp("stats2e") / "e.db"
    s = Store(str(db))
    s.migrate()
    s.close()
    server, t, url = _serve(db)
    yield url
    server.should_exit = True
    t.join(5)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as e:  # browser binaries missing
            pytest.skip(f"Chromium indisponibil: {e}")
        yield b
        b.close()


def _open(browser, base_url, w, h, theme, hash_):
    ctx = browser.new_context(viewport={"width": w, "height": h}, service_workers="block")
    ctx.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}');")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("requestfailed", lambda r: errors.append("failed " + r.url)
            if r.url.startswith(base_url) else None)
    page.goto(base_url + "/" + hash_)
    return ctx, page, errors


NO_HSCROLL = "() => document.documentElement.scrollWidth <= window.innerWidth"
# (wide data tables scroll inside their own .st-scroll / .ss-cmp-wrap box: the box must fit,
# its rows may not)
INSIDE = """() => [...document.querySelectorAll('#view-statistici *')].filter(e => {
  const box = e.parentElement && e.parentElement.closest('.st-scroll, .ss-cmp-wrap');
  if (box) return false;
  const r = e.getBoundingClientRect(); return r.width > 0 && (r.right > innerWidth + 0.5 || r.left < -0.5);
}).map(e => e.tagName + '.' + (e.getAttribute('class') || '') + ':' + (e.textContent || '').slice(0, 30))"""


@pytest.mark.parametrize("w,h", [(1280, 800), (390, 844)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_statistici_page(browser, base_url, w, h, theme):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, w, h, theme, "#statistici")
    try:
        page.wait_for_selector(".ss-summary .ss-insights li")
        summary = page.text_content(".ss-summary")
        assert "Sosiri: din 8 călătorii încheiate cu întârziere citită" in summary
        assert "7 zile cu date" in summary and "Date insuficiente" not in summary
        assert page.locator(".ss-kpi").count() == 2
        assert page.locator("svg.ss-svg").count() >= 10
        # 11 detail charts + 7 „Problemele în detaliu” cards; + the „Probleme” intro
        assert page.locator(".ss-fig").count() == 18
        assert page.locator(".ss-how").count() == 19
        assert page.locator("details.ss-data").count() >= 10
        assert page.locator(".ss-legend").count() >= 5
        assert "în curs de adunare" in page.text_content("#st-statistici")
        assert "Corelație, nu cauzalitate" in page.text_content("#st-statistici")
        assert "linie necitită" in page.text_content("#st-statistici")
        assert page.locator("a.ss-csv[href*='set=hourly']").count() == 1
        assert page.locator(".ss-glossary dt").count() >= 8
        # the accessible table opens and holds the hourly data
        page.locator(".ss-fig", has_text="La ce oră").locator("details.ss-data summary").click()
        assert page.locator(".ss-fig", has_text="La ce oră").locator("tbody tr").count() == 24
        assert page.evaluate(NO_HSCROLL)
        assert page.evaluate(INSIDE) == []
        assert page.evaluate(COUNT_JS) == 1
        assert errors == []
    finally:
        ctx.close()


def test_filters_go_to_url_and_reload(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 800, "dark", "#statistici")
    try:
        page.wait_for_selector(".ss-kpi")
        page.locator(".ss-seg-opt", has_text="Sosiri").click()
        expect(page.locator(".ss-kpi")).to_have_count(1)
        assert "board=arrival" in page.evaluate("location.hash")
        page.select_option("#ss-operator", "Transferoviar")
        expect(page.locator(".ss-summary")).to_contain_text("doar 2")
        assert "operator=Transferoviar" in page.evaluate("location.hash")
        assert "Eșantion mic" in page.text_content(".ss-kpi")
        page.locator(".ss-seg-opt", has_text="7 zile").click()
        expect(page.locator(".ss-summary")).to_contain_text("Perioada")
        assert "perioada=7" in page.evaluate("location.hash")
        # a shared link restores the selection
        page.goto(page.url.split("#")[0] + "#statistici?board=departure&tip=IR")
        page.reload()
        page.wait_for_selector(".ss-kpi")
        assert page.is_checked(".ss-seg-opt:has-text('Plecări') input")
        assert page.input_value("#ss-tip") == "IR"
        assert errors == []
    finally:
        ctx.close()


@pytest.mark.parametrize("w", [390, 1280])
def test_empty_database_explains(browser, empty_url, w):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, empty_url, w, 800, "light", "#statistici")
    try:
        page.wait_for_selector(".ss-summary")
        text = page.text_content("#st-statistici")
        assert "Date insuficiente încă — 0 zile de istoric" in text
        assert "Nu există încă date" in text and "Încă nu există" in text
        assert page.evaluate(NO_HSCROLL) and errors == []
    finally:
        ctx.close()


@pytest.fixture(scope="module")
def weather_url(tmp_path_factory):
    from tests.test_stats_overview import add
    db = tmp_path_factory.mktemp("stats2w") / "w.db"
    s = Store(str(db))
    s.migrate()
    for day in range(10, 20):
        wet = day % 2 == 0
        weather(s._conn, day, 12, 8.0 if day < 15 else 18.0, 1.2 if wet else 0.0)
        add(s._conn, "arrival", 100 + day, day, "12:00", 20 if wet else 1)
    s.close()
    server, t, url = _serve(db)
    yield url
    server.should_exit = True
    t.join(5)


@pytest.mark.parametrize("w", [390, 1280])
def test_weather_section_per_board(browser, weather_url, w):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, weather_url, w, 800, "dark", "#statistici")
    try:
        page.wait_for_selector(".ss-summary")
        fig = page.locator(".ss-fig", has_text="Vremea și întârzierile")
        assert fig.locator("svg.ss-svg").count() == 2  # arrivals: precipitation + temperature
        text = fig.text_content()
        assert "Sosiri" in text and "Plecări" in text and "analizate separat" in text
        assert "Corelație, nu cauzalitate" in text
        assert page.evaluate(NO_HSCROLL) and page.evaluate(INSIDE) == [] and errors == []
    finally:
        ctx.close()


# ---- „Probleme” (Beta 1.19) -------------------------------------------------------------------

@pytest.fixture(scope="module")
def problems_url(tmp_path_factory):
    from tests.test_stats_overview import add
    db = tmp_path_factory.mktemp("stats3p") / "p.db"
    s = Store(str(db))
    s.migrate()
    c = s._conn
    for day in range(14, 21):  # 7 days
        for k, base in enumerate((30, 40, 45, 60)):  # Pitești: late every day
            add(c, "arrival", 9250 + 2 * k, day, f"1{5 + k}:0{k}", base + (day % 3) * 5,
                station="PITESTI", ttype="RE")
        for k in range(6):  # Brașov: punctual
            add(c, "arrival", 1600 + k, day, f"0{6 + k % 3}:1{k}", 0 if k % 2 else 5)
            add(c, "departure", 1700 + k, day, f"1{k}:20", 0, station="CONSTANTA")
    s.close()
    stats_overview.clear_cache()
    server, t, url = _serve(db)
    yield url
    server.should_exit = True
    t.join(5)


@pytest.mark.parametrize("w,h", [(1280, 800), (390, 844)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_problems_first(browser, problems_url, w, h, theme):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, problems_url, w, h, theme, "#statistici")
    try:
        page.wait_for_selector(".ss-problems .ss-prob")
        # the page starts with „Probleme”, then „Ce merge bine”, then the details
        first = page.evaluate("document.querySelector('.ss-body').firstElementChild.className")
        assert first == "ss-problems"
        order = page.evaluate("""() => [...document.querySelector('.ss-body').children]
            .map(e => e.className.split(' ')[0])""")
        assert order.index("ss-problems") < order.index("ss-good") < order.index("ss-summary")
        prob = page.locator(".ss-problems")
        text = prob.text_content()
        assert "Acoperirea datelor: bună" in text and "7 zile de istoric" in text
        items = prob.locator(".ss-prob")
        assert 1 <= items.count() <= 10
        top = items.first.text_content()
        assert "Gravitate:" in top and "Încredere:" in top and "N = " in top
        assert "De ce contează:" in top
        assert prob.locator("a[href^='#statie?nume=PITESTI']").count() >= 1
        assert prob.locator("a[href^='#tren?nr=925']").count() >= 1
        rec = page.locator(".ss-fig", has_text="Ce trenuri întârzie zi de zi")
        assert rec.locator(".ss-ptrain").count() == 4
        assert "7 din 7 zile întârziat" in rec.text_content()
        assert "%" not in rec.locator(".ss-ptrain").first.text_content()
        trend = page.locator(".ss-fig", has_text="Se îmbunătățește")
        assert "Istoric insuficient" not in trend.text_content()
        assert page.locator(".ss-good li").count() >= 1
        # sample links of the problems are in-app routes
        hrefs = page.evaluate("[...document.querySelectorAll('.ss-problems a')].map(a => a.getAttribute('href'))")
        assert hrefs and all(x.startswith("#") for x in hrefs)
        assert page.evaluate(NO_HSCROLL)
        assert page.evaluate(INSIDE) == []
        assert page.evaluate(COUNT_JS) == 1
        assert errors == []
    finally:
        ctx.close()


def test_problems_below_minimum_sample(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 390, 844, "dark",
                              "#statistici?operator=Transferoviar")
    try:
        page.wait_for_selector(".ss-problems")
        text = page.text_content(".ss-problems")
        assert "Date insuficiente" in text and page.locator(".ss-prob").count() == 0
        assert page.locator(".ss-part", has_text="Problemele în detaliu").count() == 0
        assert page.evaluate(NO_HSCROLL) and errors == []
    finally:
        ctx.close()
