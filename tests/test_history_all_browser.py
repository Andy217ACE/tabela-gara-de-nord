# © 2026 Andy217Ace
"""Real browser: Istoric with a train number shows ALL days of that train (grouped by day,
summary, „Încarcă mai multe”), 1280×800 and 390×844, light/dark: no horizontal scroll,
no console/CSP errors, exactly one footer. Skipped without Playwright/Chromium."""
import socket
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

import uvicorn  # noqa: E402

from app.api import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.store import Store  # noqa: E402
from tests.test_footer_browser import COUNT_JS  # noqa: E402

expect = sync_api.expect  # polls from Python: no eval under the page's CSP

BUC = ZoneInfo("Europe/Bucharest")
LAST = date(2026, 10, 20)
DAYS = 210  # > one page of 200


def _journey(c, board, no, day, t, delay, *, read=True, gone=True, station="BRASOV"):
    hh, mm = (int(x) for x in t.split(":"))
    sched = datetime(day.year, day.month, day.day, hh, mm, tzinfo=BUC)
    sid = c.execute(
        "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
        " sched_time, first_seen, last_seen, last_delay, status, uncertain, delay_read_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,0,?)",
        (board, day.isoformat(), "IR", no, station, "CFR Calatori", t,
         (sched - timedelta(hours=1)).isoformat(), (sched + timedelta(minutes=delay)).isoformat(),
         delay if read else 0, "gone" if gone else "listed",
         (sched + timedelta(minutes=delay - 2)).isoformat() if read else None)).lastrowid
    c.execute("INSERT INTO events(service_id, ts, kind) VALUES (?,?,'appeared')",
              (sid, (sched - timedelta(hours=1)).isoformat()))
    if gone:
        c.execute("INSERT INTO events(service_id, ts, kind) VALUES (?,?,'gone')",
                  (sid, (sched + timedelta(minutes=delay + 3)).isoformat()))


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    db = tmp_path_factory.mktemp("histall") / "h.db"
    s = Store(str(db))
    s.migrate()
    c = s._conn
    for i in range(DAYS):
        day = LAST - timedelta(days=i)
        _journey(c, "arrival", 1621, day, "12:10", (i * 7) % 40, read=i % 9 != 4,
                 station="CHISINAU TRIAJ INTERNATIONAL NORD" if i % 5 == 0 else "BRASOV")
        if i < 3:
            _journey(c, "departure", 1621, day, "18:40", 2, station="CONSTANTA")
    _journey(c, "arrival", 1731, LAST, "08:15", 0)
    c.commit()
    s.close()
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
    yield f"http://127.0.0.1:{port}"
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
    # external requests are aborted on purpose (offline test): their "Failed to load
    # resource" is expected; any same-origin failure, script error or CSP error is not
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("requestfailed", lambda r: errors.append("failed " + r.url)
            if r.url.startswith(base_url) else None)
    page.goto(base_url + "/" + hash_)
    return ctx, page, errors


NO_HSCROLL = "() => document.documentElement.scrollWidth <= window.innerWidth"


@pytest.mark.parametrize("w,h", [(1280, 800), (390, 844)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_all_days_view(browser, base_url, w, h, theme):
    ctx, page, errors = _open(browser, base_url, w, h, theme, "#istoric?train=1621")
    try:
        page.wait_for_selector("#h-results .h-group")
        assert page.input_value("#h-scope") == "all" and page.is_visible("#h-scope")
        assert not page.is_visible("#h-date")
        count = page.text_content("#h-count")
        assert "213 călătorii" in count and "perioada" in count and "afișate 200" in count
        summary = page.text_content("#h-summary")
        assert "Sosiri" in summary and "Plecări" in summary and "N = " in summary
        assert "nu sunt 0" in summary
        assert page.locator("#h-results .h-row").count() == 200
        first = page.text_content("#h-results .h-group-title")
        assert "20 octombrie 2026" in first
        assert page.locator("#h-results a[href='#tren?nr=1621']").count() == 200
        assert page.locator("#h-results .res-badge").count() == 200
        assert page.locator("#h-results .delay-unread").count() > 0  # unknown is not 0
        assert page.evaluate(NO_HSCROLL)
        assert page.evaluate(COUNT_JS) == 1
        page.click("#h-more")
        expect(page.locator("#h-results .h-row")).to_have_count(213)
        assert not page.is_visible("#h-more")
        assert "afișate" not in page.text_content("#h-count")
        assert page.evaluate(NO_HSCROLL)
        # detail (chart) opens from a row
        page.locator("#h-results .h-act", has_text="Grafic").first.click()
        page.wait_for_selector("#h-detail[open] .res")
        assert errors == []
    finally:
        ctx.close()


def test_scope_switch_and_day_mode(browser, base_url):
    ctx, page, errors = _open(browser, base_url, 1280, 800, "light", "#istoric?date=2026-10-20")
    try:
        page.wait_for_selector("#h-results .h-row")
        assert not page.is_visible("#h-scope") and page.is_visible("#h-date")
        assert page.locator("#h-results .h-group").count() == 0  # no train: one day, as before
        page.fill("#h-train", "1621")
        page.wait_for_selector("#h-results .h-group")
        assert page.input_value("#h-scope") == "all"
        assert "date=" not in page.evaluate("location.hash")
        page.select_option("#h-scope", "day")
        assert page.is_visible("#h-date")
        page.fill("#h-date", "2026-10-19")
        expect(page.locator("#h-results .h-row")).to_have_count(2)
        assert page.locator("#h-results .h-group").count() == 1
        assert "date=2026-10-19" in page.evaluate("location.hash")
        # combinable with the board/station filters
        page.select_option("#h-board", "departure")
        expect(page.locator("#h-results .h-row")).to_have_count(1)
        page.select_option("#h-scope", "all")
        expect(page.locator("#h-results .h-row")).to_have_count(3)
        assert errors == []
    finally:
        ctx.close()


def test_unknown_train_message(browser, base_url):
    ctx, page, errors = _open(browser, base_url, 390, 844, "dark", "#istoric?train=4242")
    try:
        page.wait_for_selector("#h-empty:not([hidden])")
        assert "nu a fost observat" in page.text_content("#h-empty")
        assert page.evaluate(NO_HSCROLL) and errors == []
    finally:
        ctx.close()
