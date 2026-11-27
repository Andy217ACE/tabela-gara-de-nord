# © 2026 Andy217Ace
"""Shared admin login form (web/admin_login.js) on #admin, #ocr, #ocr2 and #infofer: the 2FA code
field appears on "totp_required" (or session.totp) and the code is sent with the key. API mocked."""
import json
import re
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

WEB = Path(__file__).resolve().parent.parent / "web"
PAGES = [("admin", ".admin-login"), ("ocr", ".ocr-login"), ("ocr2", ".ocr2-login"), ("infofer", ".infofer-login")]


def test_static_single_login_implementation():
    for name, _ in PAGES:
        js = (WEB / f"{name}.js").read_text(encoding="utf-8")
        assert "TabelaApp.adminLogin(" in js and "/api/admin/login" not in js, name
    js = (WEB / "admin_login.js").read_text(encoding="utf-8")
    assert "/api/admin/login" in js and "totp_required" in js and "one-time-code" in js
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", ".style.", "cssText"):
        assert bad not in js, bad
    assert "admin_login" not in (WEB / "sw.js").read_text(encoding="utf-8")  # lazy, not precached
    for lang in ("ro", "en"):
        d = json.loads((WEB / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        assert not re.search(r"minut", d["admin.msg.tooMany"] + d["ocr.msg.tooMany"])


def _page(browser, base_url, route, totp_on):  # noqa: F811
    ctx = browser.new_context(service_workers="block")
    page = ctx.new_page()
    logins = []

    def handle(r):
        url = r.request.url
        if url.endswith("/api/admin/session"):
            body = {"enabled": True, "authenticated": False, "totp": totp_on}
            return r.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        if url.endswith("/api/admin/login"):
            sent = json.loads(r.request.post_data)
            logins.append(sent)
            if "code" not in sent:
                return r.fulfill(status=401, content_type="application/json", body='{"detail": "totp_required"}')
            return r.fulfill(status=401, content_type="application/json", body='{"detail": "x"}')
        return r.fulfill(status=401, content_type="application/json", body='{"detail": "x"}')
    page.route("**/api/admin/**", handle)
    page.goto(base_url + "/?lang=ro#" + route)
    return ctx, page, logins


@pytest.mark.parametrize("route,form", PAGES)
def test_code_field_appears_on_totp_required(browser, base_url, route, form):  # noqa: F811
    ctx, page, logins = _page(browser, base_url, route, totp_on=False)
    try:
        page.wait_for_selector(form + " input[type=password]")
        assert not page.is_visible(form + " input[name=code]")
        page.fill(form + " input[type=password]", "cheie-de-test-1234")
        page.click(form + " button[type=submit]")
        page.wait_for_selector(form + " input[name=code]", state="visible")
        assert page.input_value(form + " input[type=password]") == "cheie-de-test-1234"  # key kept
        page.fill(form + " input[name=code]", "123456")
        page.click(form + " button[type=submit]")
        page.wait_for_function("() => document.activeElement && document.activeElement.type === 'password'")
        assert logins == [{"token": "cheie-de-test-1234"}, {"token": "cheie-de-test-1234", "code": "123456"}]
    finally:
        ctx.close()


def test_code_field_shown_upfront_when_session_says_totp(browser, base_url):  # noqa: F811
    ctx, page, _ = _page(browser, base_url, "admin", totp_on=True)
    try:
        page.wait_for_selector(".admin-login input[name=code]", state="visible")
    finally:
        ctx.close()
