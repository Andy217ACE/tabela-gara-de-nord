# © 2026 Andy217Ace
"""Real browser: Statistici v3, sub-project 2 — one color scale, metric tooltips, chart click ->
train list, high contrast, simple/expert mode, short texts with „Citește mai mult”.
Same fixtures as tests/test_statistici_browser.py (served page, seeded database)."""
import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from app import stats_overview  # noqa: E402
from tests.test_statistici_browser import NO_HSCROLL, _open, base_url, browser  # noqa: E402,F401

expect = sync_api.expect


def _go(browser, base_url, w=1280, h=800, hash_="#statistici", ready=".ss-quick .ss-card", theme="light"):
    stats_overview.clear_cache()
    ctx, page, errors = _open(browser, base_url, w, h, theme, hash_)
    if ready:
        page.wait_for_selector(ready)
    return ctx, page, errors


def test_scale_applied_to_summary_and_ranked_bars(browser, base_url):
    ctx, page, errors = _go(browser, base_url, ready=".ss-quick .ss-card")
    try:
        page.wait_for_selector(".ss-fig .ss-bar", state="attached")
        val = page.locator(".ss-quick .ss-card").first.locator(".ss-card-v")
        cls = val.get_attribute("class")
        assert any(f"ss-t-{k}" in cls for k in ("good", "mid", "bad")), cls
        ranked = page.locator('[data-key="care-operatori-sunt-cei-mai-punctu"] .ss-bar')
        assert ranked.count() > 0
        for c in ranked.evaluate_all("els => els.map(e => e.getAttribute('class'))"):
            assert any(f"ss-t-{k}" in c for k in ("good", "mid", "bad")), c
        # the tone is the same for the same number: green token color on good, red on bad
        probe = page.evaluate("""() => { const r = getComputedStyle(document.documentElement);
          return ['--ss-good','--ss-mid','--ss-bad'].map(k => r.getPropertyValue(k).trim()); }""")
        assert all(probe) and len(set(probe)) == 3, probe
        assert errors == []
    finally:
        ctx.close()


def _tip_text(page, key):
    import json
    from pathlib import Path
    ro = json.loads((Path(__file__).resolve().parent.parent / "web" / "i18n" / "ro.json").read_text(encoding="utf-8"))
    return ro[key]


def test_metric_tooltips_on_hover_and_keyboard_focus(browser, base_url):
    ctx, page, errors = _go(browser, base_url, ready=".ss-prob")
    try:
        helps = page.locator(".ss-prob").first.locator(".ss-help")
        assert helps.count() == 3  # severity, confidence, N
        first = helps.first
        tip = first.locator("[role=tooltip]")
        expect(tip).to_be_hidden()
        # keyboard focus (not only hover) shows the explanation
        first.focus()
        expect(tip).to_be_visible()
        assert tip.inner_text().strip() == _tip_text(page, "stats.sp2.help.sev")
        described = first.get_attribute("aria-describedby")
        assert described and page.locator("#" + described).count() == 1
        page.keyboard.press("Escape")
        expect(tip).to_be_hidden()
        # hover shows it too
        page.locator(".ss-prob").first.locator(".ss-help").nth(1).hover()
        expect(page.locator(".ss-prob").first.locator(".ss-help").nth(1).locator("[role=tooltip]")).to_be_visible()
        # median vs mean, on the summary card
        med = page.locator(".ss-quick .ss-card").nth(1).locator(".ss-help")
        med.focus()
        expect(med.locator("[role=tooltip]")).to_be_visible()
        assert errors == []
    finally:
        ctx.close()


def test_tooltips_do_not_overflow_at_360(browser, base_url):
    ctx, page, errors = _go(browser, base_url, 360, 740, ready=".ss-prob")
    try:
        last = page.locator(".ss-prob").first.locator(".ss-help").last
        last.focus()
        expect(last.locator("[role=tooltip]")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth") <= 360
        box = last.locator("[role=tooltip]").bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 360 + 0.5, box
    finally:
        ctx.close()


# ---- 3. click on a chart mark -> the trains behind it ---------------------------------------

def _rows(n, **kw):
    return [{"board": "arrival", "train": f"IR {1600 + i}", "train_no": 1600 + i, "type": "IR",
             "operator": "CFR Calatori", "route": "BRASOV", "date": "2026-10-20", "time": "12:10",
             "delay": i % 7, "state": "confirmed", **kw} for i in range(n)]


def _is_detail(url):
    return "/api/stats/overview" in url and "detail=train_list" in url


def _fake_detail(page, payload=None, status=200, seen=None):
    import json

    def handler(route):
        if seen is not None:
            seen.append(route.request.url)
        route.fulfill(status=status, content_type="application/json",
                      body=json.dumps(payload if payload is not None else {"detail": "boom"}))
    page.route(_is_detail, handler)


def _click_first_ranked_bar(page):
    page.wait_for_selector('[data-key="care-operatori-sunt-cei-mai-punctu"] .ss-bar', state="attached")
    page.locator('[data-key="care-operatori-sunt-cei-mai-punctu"] .ss-mark[data-drill-by]').first.click(force=True)


def test_click_on_bar_opens_the_train_list(browser, base_url):
    ctx, page, errors = _go(browser, base_url)
    try:
        seen = []
        _fake_detail(page, {"train_list": {"rows": _rows(3), "total": 3, "limit": 200, "truncated": False}}, seen=seen)
        _click_first_ranked_bar(page)
        dlg = page.locator("dialog.ss-drill")
        expect(dlg).to_be_visible()
        expect(dlg.locator("tbody tr")).to_have_count(3)
        assert "IR 1600" in dlg.inner_text()
        assert "by=operator" in seen[0] and "detail=train_list" in seen[0] and "key=" in seen[0]
        expect(dlg.locator(".ss-drill-trunc")).to_have_count(0)
        # closes with Escape and gives the focus back
        page.keyboard.press("Escape")
        expect(dlg).to_have_count(0)
        assert errors == []
    finally:
        ctx.close()


def test_train_list_truncation_message_over_200(browser, base_url):
    ctx, page, errors = _go(browser, base_url)
    try:
        _fake_detail(page, {"train_list": {"rows": _rows(200), "total": 350, "limit": 200, "truncated": True}})
        _click_first_ranked_bar(page)
        dlg = page.locator("dialog.ss-drill")
        expect(dlg.locator("tbody tr")).to_have_count(200)
        msg = dlg.locator(".ss-drill-trunc").inner_text()
        assert "200" in msg and "350" in msg
    finally:
        ctx.close()


def test_train_list_empty_and_error_states(browser, base_url):
    ctx, page, errors = _go(browser, base_url)
    try:
        _fake_detail(page, {"train_list": {"rows": [], "total": 0, "limit": 200, "truncated": False}})
        _click_first_ranked_bar(page)
        expect(page.locator("dialog.ss-drill .ss-empty")).to_be_visible()
        page.keyboard.press("Escape")
        page.unroute(_is_detail)
        _fake_detail(page, None, status=500)
        _click_first_ranked_bar(page)
        expect(page.locator("dialog.ss-drill [role=alert]")).to_be_visible()
    finally:
        ctx.close()


def test_heatmap_and_hourly_marks_are_clickable(browser, base_url):
    ctx, page, errors = _go(browser, base_url)
    try:
        page.wait_for_selector(".ss-cell", state="attached")
        assert page.locator(".ss-mark[data-drill-by=heat]").count() > 0
        assert page.locator(".ss-mark[data-drill-by=hour]").count() > 0
    finally:
        ctx.close()


def test_train_list_end_to_end_when_the_api_is_wired(browser, base_url):
    """Real endpoint: skipped until app/api.py passes `detail` (see docs/superpowers/plans/2026-11-17-sp2-integrare.md)."""
    import json
    import urllib.request
    stats_overview.clear_cache()
    with urllib.request.urlopen(base_url + "/api/stats/overview?detail=train_list&by=hour&key=8") as r:
        wired = "train_list" in json.loads(r.read())
    if not wired:
        pytest.skip("api.py nu trece încă parametrul detail către stats_overview (vezi lista de integrare)")
    ctx, page, errors = _go(browser, base_url)
    try:
        _click_first_ranked_bar(page)
        dlg = page.locator("dialog.ss-drill")
        expect(dlg.locator("tbody tr").first).to_be_visible()
        assert dlg.locator("tbody tr").count() >= 1
    finally:
        ctx.close()
