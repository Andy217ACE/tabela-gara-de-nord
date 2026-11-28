# © 2026 Andy217Ace
"""Pagina admin #infofer („Colectare Infofer (intern)"): rută privată (lazy, nu în nav/precache/index),
CSP, paritate i18n, plus o rulare în browser cu API-ul simulat."""
import json
import re
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from app import perf  # noqa: E402
from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def test_static_private_route_and_i18n():
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert '"#infofer": "infofer"' in app and '"infofer.js", "infofer.css"' in app
    for name in ("VIEWS", "TITLES"):  # last before #cum (test_cum_page keeps #cum last)
        assert re.search(r'var %s = \[[^\]]*"infofer", "cum"\];' % name, app)
    for f in ("index.html", "sw.js"):  # not linked publicly, not precached
        assert "infofer" not in (WEB / f).read_text(encoding="utf-8").lower(), f
    assert "/api/admin/infofer".startswith(perf.PRIVATE_ROUTES)  # hidden from public perf
    js = (WEB / "infofer.js").read_text(encoding="utf-8")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", ".style.", "cssText"):
        assert bad not in js, bad
    assert "TabelaApp.views.infofer" in js and "no-store" in js
    css = (WEB / "infofer.css").read_text(encoding="utf-8")
    assert "var(--surface)" in css and "@import" not in css and "url(" not in css
    assert '"#infofer"' in (WEB / "admin.js").read_text(encoding="utf-8")
    # main dictionary + the private pages' one (Beta 1.76: <lang>.admin.json, loaded by I18N.loadExtra)
    ro, en = ({**json.loads((WEB / "i18n" / f"{lang}.json").read_text(encoding="utf-8")),
               **json.loads((WEB / "i18n" / f"{lang}.admin.json").read_text(encoding="utf-8"))} for lang in ("ro", "en"))
    keys = lambda d: {k for k in d if k.startswith(("infofer.", "admin.infofer.")) or k == "title.infofer"}  # noqa: E731
    assert keys(ro) == keys(en) and len(keys(ro)) > 40
    used = set(re.findall(r'T\("(infofer\.[A-Za-z0-9.]*[A-Za-z0-9])"', js))
    used |= {"infofer.problem.stale", "infofer.problem.failures"}  # built from the API's problem codes
    assert used <= keys(ro), used - keys(ro)


DATA = {
    "enabled": True, "now": "2026-11-28T10:00:00+00:00",
    "health": {"ok": False, "problems": ["failures"], "runs_total": 400, "runs_24h": 30, "failed_24h": 9,
               "fail_pct_24h": 30.0, "avg_markers_24h": 812.4,
               "last_run": {"at": "2026-11-28T09:57:00+00:00", "http_status": 200, "n_markers": 820,
                            "bytes": 512000, "error": None},
               "last_ok_at": "2026-11-28T09:57:00+00:00", "first_run_at": "2026-11-27T10:00:00+00:00",
               "days_elapsed": 1.0, "days_target": 7},
    "hourly": [{"hour": "2026-11-28T09:00:00+00:00", "runs": 20, "failed": 2, "avg_markers": 800.0}],
    "live": {"fetched_at": "2026-11-28T09:57:00+00:00", "trains": [
        {"train_no": 1641, "train_type": "IR", "category": "IR", "station": "Iasi", "service_date": "2026-11-28",
         "sched_time": "12:30", "board_delay": 7, "infofer_delay": 12, "report_hhmm": "11:50",
         "passed_time": 3, "stale": False},
        {"train_no": 555, "train_type": "R", "category": "R", "station": "Ploiesti", "service_date": "2026-11-28",
         "sched_time": "13:00", "board_delay": 0, "infofer_delay": 4, "report_hhmm": "11:20",
         "passed_time": 20, "stale": True}]},
    "accuracy": {"period": ["a", "b"], "computed_at": "2026-11-28T09:58:00+00:00", "horizons": {
        "60": {"eligible": 40, "covered": 30, "coverage_pct": 75.0, "infofer_better_pct": 60.0,
               "infofer": {"mae": 3.1, "bias": -1.2}, "tabela": {"mae": 5.0, "bias": -4.0},
               "model": {"mae": 4.2, "bias": 0.5}}}},
}


def _page(browser, base_url, status=200, body=None, lang="ro", width=1280):  # noqa: F811
    ctx = browser.new_context(service_workers="block", viewport={"width": width, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    calls = []

    def handle(route):
        calls.append(route.request.url)
        if route.request.url.endswith("/api/admin/infofer"):
            return route.fulfill(status=status, content_type="application/json", body=json.dumps(body or DATA))
        return route.fulfill(status=200, content_type="application/json", body="{}")
    page.route("**/api/admin/**", handle)
    page.goto(base_url + "/?lang=" + lang + "#infofer")
    return ctx, page, errors, calls


def test_renders_cards(browser, base_url):  # noqa: F811
    ctx, page, errors, _ = _page(browser, base_url)
    try:
        page.wait_for_selector("#infofer-live table")
        assert page.inner_text("#infofer-heading") == "Colectare Infofer (intern)"
        assert page.inner_text("#infofer-badge") == "Problemă"
        assert "Peste 20%" in page.inner_text("#infofer-health")
        live = page.inner_text("#infofer-live")
        assert "IR 1641" in live and "12 min" in live and "7 min" in live and "poziție veche (20 min)" in live
        acc = page.inner_text("#infofer-accuracy")
        assert "05.12" in acc and "3.1 / -1.2" in acc and "30/40 (75%)" in acc
        assert page.locator("#infofer-hourly meter").count() == 1
        assert page.locator('.nav-item[data-route="infofer"]').count() == 0
        assert not errors, errors
    finally:
        ctx.close()


def test_login_when_unauthenticated_and_disabled(browser, base_url):  # noqa: F811
    ctx, page, _, _ = _page(browser, base_url, status=401, body={"detail": "x"}, lang="en")
    try:
        page.wait_for_selector(".infofer-login input[type=password]")
    finally:
        ctx.close()
    ctx, page, _, _ = _page(browser, base_url, body={"enabled": False}, lang="en", width=360)
    try:
        page.wait_for_selector("#infofer-body .infofer-note")
        assert "does not exist" in page.inner_text("#infofer-body")
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    finally:
        ctx.close()
