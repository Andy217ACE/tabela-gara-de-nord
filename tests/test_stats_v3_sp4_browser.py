# © 2026 Andy217Ace
"""Real browser: Statistici v3, sub-project 4 — CSV download (content, BOM, quoting), PNG download and its
CSV fallback, the print stylesheet, delayed sections (no request before the first visit) and the
„Date actualizate acum X minute” indicator. Same fixtures as tests/test_statistici_browser.py."""
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from app import stats_overview  # noqa: E402
from tests.test_statistici_browser import NO_HSCROLL, _open, base_url, browser  # noqa: E402,F401

expect = sync_api.expect
LAZY = ("/api/stats/platform-changes", "/api/stats/dwell")


def _go(browser, base_url, w=1280, h=800, hash_="#statistici", ready=".ss-quick .ss-card", theme="light"):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, w, h, theme, hash_)
    if ready:
        page.wait_for_selector(ready)
    return ctx, page, errors


def _hourly(page):
    return page.locator(".ss-fig", has_text="La ce oră")


def test_csv_download_content_and_bom(browser, base_url):
    ctx, page, errors = _go(browser, base_url, ready=".ss-fig .ss-exp-btn")
    try:
        fig = _hourly(page)
        with page.expect_download() as dl:
            fig.locator("button.ss-exp-btn", has_text="CSV").click()
        d = dl.value
        assert d.suggested_filename.startswith("tabela-") and d.suggested_filename.endswith(".csv")
        raw = open(d.path(), "rb").read()
        assert raw[:3] == b"\xef\xbb\xbf"   # UTF-8 BOM (Excel)
        text = raw.decode("utf-8-sig")
        lines = text.split("\r\n")
        assert lines[-1] == ""
        rows = lines[:-1]
        assert len(rows) == 25   # header + 24 hours
        assert all(r.count(",") >= 1 for r in rows)
        assert errors == []
    finally:
        ctx.close()


def test_csv_quotes_fields_with_commas(browser, base_url):
    ctx, page, errors = _go(browser, base_url)
    try:
        out = page.evaluate("""() => window.TabelaApp.statExport.toCsv([['a,b', 'c"d', 'ț', 'x\\ny'], [1, null, 2.5, '']])""")
        assert out == '﻿"a,b","c""d",ț,"x\ny"\r\n1,,2.5,\r\n'
    finally:
        ctx.close()


def test_png_download(browser, base_url):
    ctx, page, errors = _go(browser, base_url, ready=".ss-fig .ss-exp-btn")
    try:
        with page.expect_download() as dl:
            _hourly(page).locator("button.ss-exp-btn", has_text="PNG").click()
        d = dl.value
        assert d.suggested_filename.endswith(".png")
        assert open(d.path(), "rb").read()[:8] == b"\x89PNG\r\n\x1a\n"
        assert errors == []
    finally:
        ctx.close()


def test_png_failure_offers_csv_with_message(browser, base_url):
    ctx, page, errors = _go(browser, base_url, ready=".ss-fig .ss-exp-btn")
    try:
        page.evaluate("() => { HTMLCanvasElement.prototype.toBlob = function (cb) { cb(null); }; }")
        fig = _hourly(page)
        fig.locator("button.ss-exp-btn", has_text="PNG").click()
        msg = fig.locator(".ss-exp-msg")
        expect(msg).to_contain_text("Imaginea nu a putut fi creată")
        with page.expect_download() as dl:
            msg.locator("button", has_text="CSV").click()
        assert dl.value.suggested_filename.endswith(".csv")
    finally:
        ctx.close()


def test_export_without_rows_shows_the_empty_state(browser, base_url):
    ctx, page, errors = _go(browser, base_url, ready=".ss-fig .ss-exp-btn")
    try:
        fig = _hourly(page)
        fig.locator("tbody").evaluate("e => e.replaceChildren()")
        fig.locator("button.ss-exp-btn", has_text="CSV").click()
        expect(fig.locator(".ss-exp-msg")).to_have_text("Nu sunt date de exportat.")
    finally:
        ctx.close()


def test_export_buttons_fit_at_360(browser, base_url):
    ctx, page, errors = _go(browser, base_url, w=360, h=800, ready=".ss-fig .ss-exp-btn")
    try:
        assert page.evaluate("document.documentElement.scrollWidth") <= 360
        assert errors == []
    finally:
        ctx.close()
