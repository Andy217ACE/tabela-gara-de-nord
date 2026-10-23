# © 2026 Andy217Ace
"""Real browser: Istoric opened WITHOUT parameters shows every day (not only today): the
day field stays empty, „Toate zilele” is pressed, journeys of several days grouped by day,
200 per page + „Încarcă mai multe”; picking a day shows only that day; „Toate zilele”
brings every day back. 390×844 and 1280×800, no horizontal scroll, no console/CSP errors.
Skipped without Playwright/Chromium."""
from datetime import date, timedelta

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

import socket  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import uvicorn  # noqa: E402

from app.api import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.store import Store  # noqa: E402
from tests.test_history_all_browser import INSIDE, NO_HSCROLL, _journey, _open  # noqa: E402

expect = sync_api.expect

LAST = date(2026, 10, 20)
DAYS = 5
PER_DAY = 50  # 250 journeys > one page of 200


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    db = tmp_path_factory.mktemp("histnodate") / "h.db"
    s = Store(str(db))
    s.migrate()
    c = s._conn
    for i in range(DAYS):
        day = LAST - timedelta(days=i)
        for k in range(PER_DAY):
            board = "arrival" if k % 2 == 0 else "departure"
            _journey(c, board, 1500 + k, day, f"{6 + k // 4:02d}:{(k % 4) * 15:02d}", (k * 3) % 25,
                     read=k % 7 != 3, station="IASI" if k % 5 == 0 else "BRASOV")
    lq = c.execute("SELECT id FROM services WHERE service_date=? AND train_no=1500",
                   ((LAST - timedelta(days=4)).isoformat(),)).fetchone()[0]
    c.execute("INSERT INTO service_quality(service_id, low_quality, updated_at) VALUES (?,1,?)",
              (lq, "2026-10-22T00:00:00Z"))
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


@pytest.mark.parametrize("w,h", [(390, 844), (1280, 800)])
def test_open_without_params_shows_every_day(browser, base_url, w, h):
    ctx, page, errors = _open(browser, base_url, w, h, "light", "#istoric")
    try:
        page.wait_for_selector("#h-results .h-group")
        assert page.input_value("#h-date") == ""                 # never pre-filled with today
        assert page.get_attribute("#h-alldays", "aria-pressed") == "true"
        assert page.evaluate("location.hash") == "#istoric"
        assert page.locator("#h-results .h-group").count() >= 2  # several days
        first = page.text_content("#h-results .h-group-title")
        assert "20 octombrie 2026" in first                      # newest first
        count = page.text_content("#h-count")
        assert "250 de călătorii" in count and "perioada" in count and "(5 zile)" in count
        assert "afișate 200" in count and "Trenul" not in count
        assert page.locator("#h-results .h-row").count() == 200
        summary = page.text_content("#h-summary")
        assert "Sosiri" in summary and "Plecări" in summary and "N = " in summary
        assert "calitate redusă" in summary
        assert page.evaluate(NO_HSCROLL) and page.evaluate(INSIDE) == 0
        page.click("#h-more")
        expect(page.locator("#h-results .h-row")).to_have_count(250)
        expect(page.locator("#h-results .h-group")).to_have_count(5)
        assert not page.is_visible("#h-more")

        # pick a day: only that day
        page.fill("#h-date", "2026-10-18")
        expect(page.locator("#h-results .h-row")).to_have_count(PER_DAY)
        expect(page.locator("#h-results .h-group")).to_have_count(1)
        assert "18 octombrie" in page.text_content("#h-results .h-group-title")
        assert "date=2026-10-18" in page.evaluate("location.hash")
        assert page.get_attribute("#h-alldays", "aria-pressed") == "false"

        # „Toate zilele” brings every day back
        page.click("#h-alldays")
        expect(page.locator("#h-results .h-row")).to_have_count(200)
        assert page.input_value("#h-date") == ""
        assert page.locator("#h-results .h-group").count() >= 2
        assert page.evaluate("location.hash") == "#istoric"
        assert page.evaluate(NO_HSCROLL) and page.evaluate(INSIDE) == 0
        assert errors == []
    finally:
        ctx.close()


def test_filters_without_day_cover_every_day(browser, base_url):
    ctx, page, errors = _open(browser, base_url, 390, 844, "dark", "#istoric?station=iasi&board=arrival")
    try:
        page.wait_for_selector("#h-results .h-group")
        assert page.input_value("#h-date") == ""
        expect(page.locator("#h-results .h-group")).to_have_count(5)
        rows = page.locator("#h-results .h-row").count()
        assert rows == 5 * len([k for k in range(PER_DAY) if k % 5 == 0 and k % 2 == 0])
        assert page.evaluate(NO_HSCROLL) and errors == []
    finally:
        ctx.close()

