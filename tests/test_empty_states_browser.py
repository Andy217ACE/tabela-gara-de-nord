# © 2026 Andy217Ace
"""Real browser: Trenuri (#trenuri) and Stații (#statii) with an empty API answer show the
explicit „Nu există încă date pentru …” message (no empty table, no NaN/undefined); with a
500 they show „Nu am putut încărca …” and a „Reîncearcă” button that refetches.
Skipped when Playwright (dev only) or its Chromium is unavailable."""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

EMPTY = {
    "#trenuri": ("/api/trains/stats", {"trains": [], "params": {"min_sample": 5}},
                 "#st-trenuri", "Nu există încă date pentru trenuri."),
    "#statii": ("/api/stations", {"stations": []},
                "#st-statii", "Nu există încă date pentru stații."),
}
ERROR = {
    "#trenuri": ("/api/trains/stats", "#st-trenuri", "Nu am putut încărca trenurile."),
    "#statii": ("/api/stations", "#st-statii", "Nu am putut încărca stațiile."),
}


def _open(browser, base_url, hash_, api, handler):  # noqa: F811
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    ctx.route("**" + api + "*", handler)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base_url + "/" + hash_)
    return ctx, page, errors


@pytest.mark.parametrize("hash_", ["#trenuri", "#statii"])
def test_empty_trains_and_stations_show_message(browser, base_url, hash_):  # noqa: F811
    api, body, root, text = EMPTY[hash_]
    ctx, page, errors = _open(browser, base_url, hash_, api, lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps(body)))
    try:
        page.wait_for_selector(root + " .empty")
        shown = page.text_content(root)
        assert text in shown
        assert page.locator(root + " table").count() == 0
        assert "NaN" not in shown and "undefined" not in shown
        assert errors == []
    finally:
        ctx.close()


@pytest.mark.parametrize("hash_", ["#trenuri", "#statii"])
def test_server_error_shows_message_and_retry(browser, base_url, hash_):  # noqa: F811
    api, root, text = ERROR[hash_]
    calls = []

    def handler(route):
        calls.append(1)
        route.fulfill(status=500, content_type="application/json", body='{"detail":"boom"}')

    ctx, page, errors = _open(browser, base_url, hash_, api, handler)
    try:
        page.wait_for_selector(root + " .notice-error")
        shown = page.text_content(root)
        assert text in shown and "NaN" not in shown and "undefined" not in shown
        assert page.locator(root + " table").count() == 0
        btn = page.get_by_role("button", name="Reîncearcă")
        assert btn.count() == 1
        before = len(calls)
        btn.click()
        page.wait_for_timeout(300)
        assert len(calls) > before
        assert errors == []
    finally:
        ctx.close()
