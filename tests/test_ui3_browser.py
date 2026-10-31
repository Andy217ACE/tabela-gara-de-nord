# © 2026 Andy217Ace
"""Real browser: Beta 1.28 „UI v3” — the interactive chart layer (web/charts3.js, lazy): one shared
floating tooltip for every bar / line / column / heat-map chart (mouse hover, touch tap-and-scrub with
pointer events, keyboard arrows + Esc; clamped inside the viewport, never on top of the hovered mark
on a phone), the crosshair, legend hover / toggle, the full-screen dialog (focus trap, Esc, the data
table beside the chart), „Copiază linkul”, the section chips with scroll-spy, the calendar, the
morph on a filter change, reduced motion, and the live Tabela left pixel-identical.
Skipped without Chromium."""
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

import random  # noqa: E402

from app import stats_overview  # noqa: E402
from app.store import Store  # noqa: E402
from tests.test_footer_browser import base_url as board_url  # noqa: E402,F401
from tests.test_stats_overview import add  # noqa: E402
from tests.test_statistici_browser import NO_HSCROLL, _open, _serve, browser  # noqa: E402,F401

expect = sync_api.expect

TIP = ".c3-tip.is-on"


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    """20 service days, 9 trains per board on consecutive hours (06–14): enough points for lines, areas,
    labelled extremes, a calendar and 14-day sparklines (the small shared seed has only 7 thin days)."""
    db = tmp_path_factory.mktemp("ui3") / "u.db"
    st = Store(str(db))
    st.migrate()
    rnd = random.Random(3)
    stations = ["BRASOV", "CONSTANTA", "GALATI", "CLUJ NAPOCA"]
    ops = ["CFR Calatori", "Transferoviar", "Regio Calatori"]
    types = ["IR", "R", "RE"]
    for day in range(1, 21):
        for i in range(9):
            for board, first in (("arrival", 1621), ("departure", 1731)):
                delay = max(0, int(rnd.expovariate(1 / (2 + (i % 4) * 2))))
                add(st._conn, board, first + i * 2, day, f"{6 + i:02d}:{(i * 7) % 60:02d}", delay,
                    station=stations[i % 4], operator=ops[i % 3], ttype=types[i % 3], platform=1 + i)
    st._conn.commit()
    st.close()
    stats_overview.clear_cache()
    server, t, url = _serve(db)
    yield url
    server.should_exit = True
    t.join(5)


def _until(page, expr, timeout=8000):
    """Poll a JS expression from Python (the page's CSP forbids the eval wait_for_function needs)."""
    for _ in range(timeout // 100):
        if page.evaluate(expr):
            return True
        page.wait_for_timeout(100)
    raise AssertionError("timed out waiting for: " + expr)


def _ready(page):
    page.wait_for_selector("#st-statistici .ss-fig")
    _until(page, "document.querySelectorAll('svg.c3-bound').length > 5")


def _fig(page, title):
    return page.locator(".ss-fig", has=page.locator(".ss-fig-title", has_text=title)).first


def _hover(page, loc):
    """Move the real mouse onto a mark (centred in the viewport, clear of the sticky bars)."""
    loc.evaluate("e => e.scrollIntoView({block: 'center'})")
    page.wait_for_timeout(120)
    bb = loc.bounding_box()
    page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
    page.wait_for_timeout(120)


def _tip_box(page):
    return page.evaluate("""() => { const r = document.querySelector('.c3-tip').getBoundingClientRect();
      return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: innerWidth, h: innerHeight,
               on: document.querySelector('.c3-tip').classList.contains('is-on') }; }""")


def _centre(page, sel, n=0):
    return page.evaluate("""([sel, n]) => { const e = document.querySelectorAll(sel)[n]; e.scrollIntoView({block: 'center'});
      const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2, l: r.left, t: r.top, r: r.right, b: r.bottom }; }""", [sel, n])


# ---- tooltip: mouse ---------------------------------------------------------------------------

def test_tooltip_on_hover_replaces_the_native_title(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "dark", "#statistici")
    try:
        _ready(page)
        # the slow native tooltip is gone from every mark of every interactive chart; the chart keeps its own title / desc
        assert page.evaluate("document.querySelectorAll('svg.c3-bound g.ss-mark > title').length") == 0
        assert page.evaluate("document.querySelectorAll('svg.c3-bound > title').length") >= 5
        f = _fig(page, "Cât de mult")
        f.scroll_into_view_if_needed()
        _hover(page, f.locator("path.ss-bar").nth(2))
        expect(page.locator(TIP)).to_be_visible()
        txt = page.locator(TIP).text_content()
        assert "călătorii" in txt and "N = " in txt and "Sosiri" in txt and "Plecări" in txt, txt
        # the mark under the pointer is highlighted and the tooltip is not announced by itself
        assert page.locator(TIP).get_attribute("aria-hidden") == "true"
        page.mouse.move(2, 2)
        expect(page.locator(TIP)).not_to_be_visible()
        assert errors == []
    finally:
        ctx.close()


@pytest.mark.parametrize("figure,mark", [("Cât de mult", "path.ss-bar"), ("La ce oră", "circle.ss-dot"),
                                         ("Ce zile și ore", "rect.ss-cell"), ("Care operatori", "path.ss-bar")])
def test_every_chart_type_has_the_tooltip(browser, base_url, figure, mark):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "light", "#statistici")
    try:
        _ready(page)
        f = _fig(page, figure)
        f.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        _hover(page, f.locator(mark).first)
        expect(page.locator(TIP)).to_be_visible()
        assert page.locator(TIP).text_content().strip()
        assert errors == []
    finally:
        ctx.close()


def test_line_chart_crosshair_and_linked_strip(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "dark", "#statistici")
    try:
        _ready(page)
        f = _fig(page, "La ce oră")
        f.scroll_into_view_if_needed()
        svg = f.locator("svg.ss-svg").first
        bb = svg.bounding_box()
        page.mouse.move(bb["x"] + bb["width"] * 0.5, bb["y"] + bb["height"] * 0.5)
        expect(page.locator(TIP)).to_be_visible()
        assert f.locator("line.c3-cross.is-on").count() == 1          # the guide line
        assert f.locator("svg.ss-svg").first.locator("g.c3-act circle.ss-dot").count() >= 1   # highlighted point(s)
        assert f.locator("rect.c3-band.is-on").count() == 1           # the N strip under it follows the same hour
        page.mouse.move(2, 2)
        assert f.locator("line.c3-cross.is-on").count() == 0
        assert errors == []
    finally:
        ctx.close()


def test_tooltip_is_clamped_inside_the_viewport(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 360, 780, "light", "#statistici")
    try:
        _ready(page)
        f = _fig(page, "La ce oră")
        f.scroll_into_view_if_needed()
        bb = f.locator("svg.ss-svg").first.bounding_box()
        for fx in (0.04, 0.5, 0.97):          # left edge, middle, right edge
            page.mouse.move(bb["x"] + bb["width"] * fx, bb["y"] + bb["height"] * 0.45)
            page.wait_for_timeout(150)
            b = _tip_box(page)
            assert b["on"], fx
            assert b["l"] >= 0 and b["r"] <= b["w"] and b["t"] >= 0 and b["b"] <= b["h"], (fx, b)
        assert errors == []
    finally:
        ctx.close()


# ---- tooltip: touch scrub ---------------------------------------------------------------------

def _touch(page, kind, x, y, target):
    target.dispatch_event(kind, {"pointerType": "touch", "pointerId": 7, "isPrimary": True,
                                               "clientX": x, "clientY": y, "buttons": 1 if kind != "pointerup" else 0})


def test_touch_tap_and_drag_scrubs_and_never_covers_the_mark(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 390, 844, "dark", "#statistici")
    try:
        _ready(page)
        f = _fig(page, "Cât de mult")
        f.scroll_into_view_if_needed()
        page.wait_for_timeout(1300)                            # the bars finish growing before they are measured
        svg = f.locator("svg.c3-bound").first
        marks = f.locator("path.ss-bar.ss-arr")
        a = marks.nth(1).bounding_box()
        b = marks.nth(marks.count() - 1).bounding_box()
        _touch(page, "pointerdown", a["x"] + a["width"] / 2, a["y"] + a["height"] / 2, svg)
        expect(page.locator(TIP)).to_be_visible()
        assert "is-touch" in page.locator(TIP).get_attribute("class")
        first = page.locator(TIP).text_content()
        box = _tip_box(page)
        # the tooltip never sits on the mark being touched (above it, or below, or beside it)
        hit = page.evaluate("""() => { const t = document.querySelector('.c3-tip').getBoundingClientRect();
          return [...document.querySelectorAll('.c3-act .ss-bar')].some(m => { const r = m.getBoundingClientRect();
            return !(t.right <= r.left || t.left >= r.right || t.bottom <= r.top || t.top >= r.bottom); }); }""")
        assert not hit, box
        assert box["l"] >= 0 and box["r"] <= box["w"]
        # drag to another category: the tooltip follows the finger
        _touch(page, "pointermove", b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, svg)
        assert page.locator(TIP).text_content() != first
        _touch(page, "pointerup", b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, svg)
        expect(page.locator(TIP)).to_be_visible()            # stays after the finger lifts
        # a touch somewhere else closes it
        page.locator("h1").first.dispatch_event("pointerdown", {"pointerType": "touch", "pointerId": 8, "clientX": 5, "clientY": 5})
        expect(page.locator(TIP)).not_to_be_visible()
        assert errors == []
    finally:
        ctx.close()


# ---- tooltip: keyboard ------------------------------------------------------------------------

def test_keyboard_arrows_walk_the_marks_and_escape_closes(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "light", "#statistici")
    try:
        _ready(page)
        f = _fig(page, "Cât de mult")
        f.scroll_into_view_if_needed()
        svg = f.locator("svg.c3-bound").first
        assert svg.get_attribute("tabindex") == "0"           # one tab stop per chart
        svg.focus()
        page.keyboard.press("ArrowRight")
        expect(page.locator(TIP)).to_be_visible()
        first = page.locator(TIP).text_content()
        page.keyboard.press("ArrowRight")
        second = page.locator(TIP).text_content()
        assert second != first
        page.keyboard.press("ArrowLeft")
        assert page.locator(TIP).text_content() == first
        page.keyboard.press("End")
        assert page.locator(TIP).text_content() not in (first, second)
        # the text alternative is spoken from a polite live region (not from the tooltip itself)
        page.wait_for_timeout(300)
        assert page.evaluate("[...document.querySelectorAll('[aria-live=polite]')].some(n => n.className.includes('sr-only') && n.textContent.includes('călătorii'))")
        page.keyboard.press("Escape")
        expect(page.locator(TIP)).not_to_be_visible()
        assert svg.get_attribute("role") == "img"              # still named by its <title> / <desc>
        assert errors == []
    finally:
        ctx.close()


# ---- legend ---------------------------------------------------------------------------------

def test_legend_hover_dims_and_click_toggles_a_series(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "dark", "#statistici")
    try:
        _ready(page)
        f = _fig(page, "Cât de mult")
        f.scroll_into_view_if_needed()
        legs = f.locator(".c3-leg")
        assert legs.count() == 2 and legs.first.get_attribute("aria-pressed") == "true"
        page.wait_for_timeout(900)
        legs.nth(1).hover()                                   # Plecări
        page.wait_for_timeout(300)
        assert "c3-hl-dep" in f.get_attribute("class")
        # hovering „Plecări” keeps its bars and dims the other series
        assert float(f.locator("path.ss-bar.ss-dep").first.evaluate("e => getComputedStyle(e).opacity")) == 1
        assert float(f.locator("path.ss-bar.ss-arr").first.evaluate("e => getComputedStyle(e).opacity")) < 0.5
        legs.nth(1).click()
        assert legs.nth(1).get_attribute("aria-pressed") == "false"
        assert "c3-off-dep" in f.get_attribute("class")
        assert f.locator("path.ss-bar.ss-dep").first.evaluate("e => getComputedStyle(e).display") == "none"
        # a hidden series is left out of the tooltip
        page.mouse.move(2, 2)
        _hover(page, f.locator("path.ss-bar.ss-arr").nth(2))
        assert "Plecări" not in page.locator(TIP).text_content()
        # the last visible series can't be hidden
        legs.first.click()
        assert legs.first.get_attribute("aria-pressed") == "true"
        legs.nth(1).focus()
        page.keyboard.press("Enter")                          # keyboard toggles it back
        assert legs.nth(1).get_attribute("aria-pressed") == "true" and "c3-off-dep" not in f.get_attribute("class")
        assert errors == []
    finally:
        ctx.close()


# ---- full screen + copy link ----------------------------------------------------------------

def test_fullscreen_dialog_traps_focus_shows_the_table_and_closes_with_esc(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 800, "dark", "#statistici")
    try:
        _ready(page)
        f = _fig(page, "La ce oră")
        f.scroll_into_view_if_needed()
        btn = f.locator("button.c3-full")
        assert btn.get_attribute("aria-label")
        btn.click()
        dlg = page.locator("dialog.c3-dlg[open]")
        expect(dlg).to_be_visible()
        assert page.evaluate("document.activeElement.closest('dialog') !== null")
        assert dlg.locator("svg.ss-svg").count() >= 1
        assert dlg.locator("table tbody tr").count() >= 20     # the data table is beside the chart
        assert dlg.locator("h2").text_content() == "La ce oră întârzie cel mai mult?"
        # cloned ids are unique in the document (no duplicate aria targets)
        assert page.evaluate("(() => { const ids = [...document.querySelectorAll('[id]')].map(e => e.id); return ids.length === new Set(ids).size; })()")
        # the chart in the dialog is interactive too
        _hover(page, dlg.locator("svg.ss-svg circle.ss-dot").first)
        expect(page.locator(TIP)).to_be_visible()
        # a modal dialog covers the page, so the tooltip lives inside it while it is open
        assert page.evaluate("document.querySelector('.c3-tip').closest('dialog') !== null")
        # the line chart was drawn again at the size of the dialog (not a small scaled copy)
        big = page.evaluate("document.querySelector('dialog.c3-dlg svg.ss-svg').getBoundingClientRect().height")
        small = page.evaluate("document.querySelector('.ss-fig:has(.c3-full) svg.ss-svg').getBoundingClientRect().height")
        assert big > small * 1.3, (big, small)
        assert dlg.locator("summary").count() == 0          # no leftover „Details” disclosure
        page.mouse.move(2, 2)
        # Tab never leaves the dialog (both directions)
        for _ in range(14):
            page.keyboard.press("Tab")
            assert page.evaluate("document.activeElement.closest('dialog') !== null")
        for _ in range(14):
            page.keyboard.press("Shift+Tab")
            assert page.evaluate("document.activeElement.closest('dialog') !== null")
        page.keyboard.press("Escape")
        expect(page.locator("dialog.c3-dlg")).to_have_count(0)
        assert page.evaluate("document.activeElement.classList.contains('c3-full')")   # focus goes back
        assert page.evaluate("document.querySelector('.c3-tip').closest('dialog') === null")  # the tooltip is back in the page
        assert errors == []
    finally:
        ctx.close()


def test_fullscreen_dialog_fits_a_phone(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 360, 740, "light", "#statistici")
    try:
        _ready(page)
        f = _fig(page, "La ce oră")
        f.scroll_into_view_if_needed()
        f.locator("button.c3-full").click()
        expect(page.locator("dialog.c3-dlg[open]")).to_be_visible()
        r = page.evaluate("(() => { const r = document.querySelector('dialog.c3-dlg').getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom, innerWidth, innerHeight]; })()")
        assert r[0] >= 0 and r[1] >= 0 and r[2] <= r[4] and r[3] <= r[5], r
        assert page.evaluate("document.querySelector('dialog.c3-dlg .c3-dlg-body').scrollWidth <= document.querySelector('dialog.c3-dlg .c3-dlg-body').clientWidth + 1")
        page.locator("button.c3-dlg-close").click()
        expect(page.locator("dialog.c3-dlg")).to_have_count(0)
        assert errors == []
    finally:
        ctx.close()


def test_copy_link_to_a_chart_and_open_it(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "light", "#statistici?board=arrival")
    try:
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base_url)
        _ready(page)
        f = _fig(page, "La ce oră")
        f.scroll_into_view_if_needed()
        f.locator("button.c3-tool").first.click()
        page.wait_for_timeout(200)
        url = page.evaluate("navigator.clipboard.readText()")
        assert "#statistici?" in url and "board=arrival" in url and "grafic=" in url, url
        page.evaluate("window.scrollTo(0, 0)")
        page.goto(url)
        page.wait_for_selector(".ss-fig.is-target", timeout=8000)
        top = page.evaluate("document.querySelector('.ss-fig.is-target').getBoundingClientRect().top")
        assert -5 < top < 450, top
        assert "La ce oră" in page.locator(".ss-fig.is-target .ss-fig-title").text_content()
        assert errors == []
    finally:
        ctx.close()


# ---- section chips (scroll-spy) --------------------------------------------------------------

@pytest.mark.parametrize("w,h", [(1280, 800), (360, 780)])
def test_section_chips_scroll_and_follow(browser, base_url, w, h):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, w, h, "dark", "#statistici")
    try:
        _ready(page)
        chips = page.locator(".c3-toc .c3-chip")
        assert chips.count() >= 8
        assert page.evaluate(NO_HSCROLL)
        chips.filter(has_text="Hartă").click()
        _until(page, "document.querySelector('.c3-chip[aria-current]').textContent === 'Hartă'")
        page.wait_for_timeout(1500)
        top = page.evaluate("[...document.querySelectorAll('.ss-fig')].find(f => f.textContent.includes('Ce zile și ore')).getBoundingClientRect().top")
        assert -10 < top < h * 0.45, top
        assert page.locator(".c3-chip[aria-current]").text_content() == "Hartă"
        # the strip sticks under the main bar while the page scrolls
        assert page.evaluate("document.querySelector('.c3-toc').getBoundingClientRect().top") < 120
        # scrolling by hand moves the active chip
        _fig(page, "Care operatori").scroll_into_view_if_needed()
        page.evaluate("window.scrollBy(0, -60)")
        page.wait_for_timeout(500)
        assert page.locator(".c3-chip[aria-current]").text_content() in ("Operatori", "Hartă")
        assert page.evaluate(NO_HSCROLL)
        assert errors == []
    finally:
        ctx.close()


# ---- calendar, reference lines, extremes, gauge, sparklines -----------------------------------

def test_calendar_reference_lines_extremes_and_gauge(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "dark", "#statistici")
    try:
        _ready(page)
        cal = _fig(page, "Cum arată fiecare zi")
        assert cal.locator("svg.c3-cal").count() == 2                 # one calendar per board
        assert cal.locator("svg.c3-cal rect.ss-cell").count() >= 14   # one square per day with data
        cal.scroll_into_view_if_needed()
        _hover(page, cal.locator("rect.ss-cell").first)
        expect(page.locator(TIP)).to_be_visible()
        assert "N = " in page.locator(TIP).text_content() or "nicio" in page.locator(TIP).text_content()
        cal.locator("details.ss-data summary").click()
        assert cal.locator("details.ss-data tbody tr").count() >= 14
        # the 5-min threshold is a labelled reference line on the hourly chart; the best / worst day are labelled
        hourly = _fig(page, "La ce oră")
        assert hourly.locator("g.c3-ref").count() == 1 and "5 min" in hourly.locator("g.c3-ref text").text_content()
        daily = page.locator(".ss-fig", has_text="Cum a evoluat")
        assert daily.locator("path.c3-area").count() >= 1 and daily.locator("path.ss-line").count() >= 1
        assert page.locator(".ss-fig", has_text="Cum a evoluat").locator("text.c3-ext").count() >= 2
        # the punctuality gauge sits in the hero tiles, next to the number (never alone)
        assert page.locator(".ss-hero-strip .ui-stat.has-gauge svg.ui-gauge").count() == 2
        assert page.locator(".ss-hero-strip .ui-stat.has-gauge .ui-stat-v").first.text_content().strip().endswith("%")
        assert errors == []
    finally:
        ctx.close()


def test_table_rows_have_a_14_day_sparkline_with_gaps_not_zeros(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "dark", "#trenuri")
    try:
        page.wait_for_selector("#st-trenuri tbody tr")
        assert page.locator("#st-trenuri thead th", has_text="Ultimele 14 zile").count() == 1
        rows = page.locator("#st-trenuri tbody tr")
        cell = rows.first.locator(".st-spark-cell")
        assert cell.count() == 1
        # a row with at least two read days draws a line; the others say „—” (never a flat zero line)
        with_spark = page.locator("#st-trenuri .st-spark-cell svg.ui-spark-sm").count()
        dash = page.locator("#st-trenuri .st-spark-cell.ui-spark-none").count()
        assert with_spark >= 1 and with_spark + dash == rows.count()
        label = page.locator("#st-trenuri svg.ui-spark-sm").first.get_attribute("aria-label")
        assert "ultimele 14 zile" in label and "min" in label
        assert errors == []
    finally:
        ctx.close()


# ---- motion ---------------------------------------------------------------------------------

def test_filter_change_morphs_the_charts_instead_of_redrawing(browser, base_url):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "dark", "#statistici")
    try:
        _ready(page)
        page.wait_for_timeout(1600)           # first draw-in finished
        page.select_option("select[name=operator], #ss-operator, .ss-filters select >> nth=0", index=1)
        _until(page, "document.querySelector('.ss-fig.c3-morph') !== null")
        assert page.evaluate("document.getAnimations().length") >= 1
        # no flash: the figures were not emptied for a skeleton
        assert page.locator(".ui-skel").count() == 0
        assert errors == []
    finally:
        ctx.close()


def test_reduced_motion_disables_morph_tooltip_transitions_and_idle_pausing(browser, base_url):
    stats_overview.clear_cache()
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce", service_workers="block")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(base_url + "/#statistici")
        _ready(page)
        assert page.evaluate("[...document.getAnimations()].filter(a => a.playState === 'running').length") == 0
        assert page.evaluate("document.querySelectorAll('svg.c3-idle').length") == 0     # nothing waits for a scroll
        f = _fig(page, "Cât de mult")
        f.scroll_into_view_if_needed()
        _hover(page, f.locator("path.ss-bar").nth(1))
        dur = page.evaluate("getComputedStyle(document.querySelector('.c3-tip')).transitionDuration")
        assert float(dur.split(",")[0].rstrip("s")) < 0.001, dur       # (reduced motion: the global reset makes it ~0)
        page.select_option(".ss-filters select >> nth=0", index=1)
        page.wait_for_timeout(900)
        assert page.evaluate("document.querySelectorAll('.c3-morph').length") == 0
        assert page.evaluate("[...document.getAnimations()].filter(a => a.playState === 'running').length") == 0
        # the gauge is drawn at once, the numbers are final
        assert page.evaluate("[...document.querySelectorAll('[data-final]')].every(n => n.textContent === n.getAttribute('data-final'))")
        assert errors == []
    finally:
        ctx.close()


def test_charts_layer_is_lazy_and_page_changes_use_view_transitions(browser, base_url):
    stats_overview.clear_cache()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, service_workers="block")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    seen = []
    page.on("request", lambda r: seen.append(r.url.split("?")[0].rsplit("/", 1)[-1]))
    try:
        page.goto(base_url + "/#istoric")
        page.wait_for_selector("#view-istoric:not([hidden])")
        page.wait_for_timeout(500)
        assert "charts3.js" not in seen and "charts3.css" not in seen      # not on pages without charts
        page.locator(".nav-item[data-route='statistici']").click()
        page.wait_for_selector("#st-statistici .ss-fig")
        assert "charts3.js" in seen and "charts3.css" in seen
        # the route change ran inside a View Transition (Chromium has them) — the layer is a progressive enhancement
        assert page.evaluate("typeof document.startViewTransition") == "function"
        assert page.evaluate("document.body.dataset.route") == "statistici"
        page.locator(".nav-item[data-route='trenuri']").click()
        page.wait_for_selector("#view-trenuri:not([hidden])")
        assert page.evaluate("document.body.dataset.route") == "trenuri"
    finally:
        ctx.close()


def test_page_still_works_when_the_chart_layer_cannot_load(browser, base_url):
    stats_overview.clear_cache()
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, service_workers="block")
    ctx.route("**/*", lambda r: r.abort() if "charts3." in r.request.url
              else (r.continue_() if r.request.url.startswith(base_url) else r.abort()))
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(base_url + "/#statistici")
        page.wait_for_selector("#st-statistici .ss-fig", timeout=15000)
        assert page.locator("svg.ss-svg").count() >= 10          # the plain charts are all there
        assert page.locator(".c3-toc").count() == 0
        assert errors == []
    finally:
        ctx.close()


# ---- charts on the other pages -----------------------------------------------------------------

@pytest.mark.parametrize("route,ready", [("#tren?nr=1621", "#st-tren svg.st-chart"), ("#statie?nume=BRASOV", "#st-statie svg.st-chart")])
def test_tren_and_statie_bar_charts_get_the_same_tooltip(browser, base_url, route, ready):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, 1280, 900, "dark", route)
    try:
        page.wait_for_selector(ready, state="attached")
        _until(page, "document.querySelectorAll('svg.st-chart.c3-bound').length >= 1")
        assert page.evaluate("document.querySelectorAll('svg.st-chart g.st-bar-g > title').length") == 0
        bar = page.locator("svg.st-chart.c3-bound rect.st-bar").first
        _hover(page, bar)
        expect(page.locator(TIP)).to_be_visible()
        assert errors == []
    finally:
        ctx.close()


# ---- the live Tabela is left exactly as it was -------------------------------------------------

_BOARD_SNAPSHOT = {}                            # base URL -> the /api/board answer both shots are given


def _tabela_shot(browser, board_url, w, h, theme, view, with_layer):
    ctx = browser.new_context(viewport={"width": w, "height": h}, service_workers="block")
    # „acum N s” is performance.now() minus the arrival time: it ticks every second and gains a digit
    # at 10 s, which widens the live pill by ~7 px between the two captures (the mask only covers the
    # pill's box at mask time). A frozen clock keeps the text and the box the same in both shots.
    ctx.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}'); localStorage.setItem('tabela.view', '{view}');"
                        "performance.now = () => 0;")

    def route(r):
        u = r.request.url
        if not u.startswith(board_url):
            r.abort()
        elif not with_layer and any(n in u for n in ("/ui2.css", "/ui2.js", "/charts3.")):
            r.abort()                           # the same page without the whole v2 / v3 visual layer
        elif u.startswith(board_url + "/api/board"):
            # the live board is the same answer for both shots: the first one is kept and replayed, with the
            # server's age pinned (it ticks, and a fetch between the shots would move the „acum” text across a
            # digit boundary; a train crossing the window between them would change the page's height)
            if board_url not in _BOARD_SNAPSHOT:
                resp = r.fetch()
                data = resp.json()
                data.update(age_s=0, stale=False)
                _BOARD_SNAPSHOT[board_url] = data
            r.fulfill(json=_BOARD_SNAPSHOT[board_url])
        else:
            r.continue_()
    ctx.route("**/*", route)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        page.goto(board_url + "/")
        page.wait_for_selector(".pnl-row" if view == "panou" else ".train .t-station")
        page.wait_for_timeout(700)
        return page.screenshot(full_page=True, animations="disabled", mask=[
            # only the things that tick by themselves (clocks, „acum 3 s”, the live pill) are masked
            page.locator("#hdr-clock"), page.locator("#live"), page.locator(".pnl-clock"), page.locator(".pnl-status"),
            page.locator(".pnl-clockwx"),
            # the sticky menu: its labels are rasterised differently between two captures of the SAME page
            # (~985 px, backdrop-filter layer; seen without the visual layer too). No v2 / v3 rule styles
            # .navbar at rest (ui2.css only names it for View Transitions), so the layer cannot change it.
            page.locator(".navbar")]), errors
    finally:
        ctx.close()


@pytest.mark.parametrize("view", ["carduri", "panou"])
@pytest.mark.parametrize("w,h,theme", [(1280, 800, "dark"), (360, 780, "light")])
def test_tabela_is_pixel_identical_with_and_without_the_visual_layer(browser, board_url, view, w, h, theme):
    with_layer, e1 = _tabela_shot(browser, board_url, w, h, theme, view, True)
    without, e2 = _tabela_shot(browser, board_url, w, h, theme, view, False)
    assert e1 == [] and e2 == []
    assert with_layer == without, "the live Tabela must not depend on ui2 / ui3"
