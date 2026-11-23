# © 2026 Andy217Ace
"""Admin page #ocr2 („Alternativa OCR"): static checks + a real-browser run with the API mocked."""
import base64
import json
import re
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def test_static_route_lazy_and_i18n():
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert '"#ocr2": "ocr2"' in app and '"ocr2.js", "ocr2.css"' in app
    for name in ("VIEWS", "TITLES"):  # registered as a view and with a page title
        assert '"ocr2"' in re.search(r"var %s = \[[^\]]*\]" % name, app).group(0)
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "ocr2" not in html
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    assert "ocr2" not in sw
    js = (WEB / "ocr2.js").read_text(encoding="utf-8")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", ".style.", "cssText"):
        assert bad not in js, bad
    assert "X-CSRF-Token" in js and "TabelaApp.views.ocr2" in js
    css = (WEB / "ocr2.css").read_text(encoding="utf-8")
    assert "var(--surface)" in css and "@import" not in css and "url(" not in css
    ro = json.loads((WEB / "i18n" / "ro.json").read_text(encoding="utf-8"))
    en = json.loads((WEB / "i18n" / "en.json").read_text(encoding="utf-8"))
    keys = lambda d: {k for k in d if k.startswith("ocr2.") or k == "title.ocr2"}  # noqa: E731
    assert keys(ro) == keys(en) and len(keys(ro)) > 30
    used = set(re.findall(r'T\("(ocr2\.[A-Za-z.]*[A-Za-z])"', js)) | {"ocr2.verdict." + v for v in ("correct", "wrong", "unclear")}
    assert used <= keys(ro)


def _event(i, verdict=None):
    return {"id": "20261123T0%d0000-arrival-%d" % (i, i), "ts": "2026-11-23T10:0%d:00Z" % i, "shadow": True,
            "board": "arrival" if i % 2 else "departure", "row_index": i, "cols": ["no", "time"],
            "values": {"no": "158%d" % i, "time": "18:4%d" % i}, "prob": 0.9931,
            "context": {"type": "IR", "station": "CONSTANTA", "operator": "CFR Calatori"},
            "verdict": verdict,
            "crops": {"no": "/api/admin/ocr-alt/crop/e%d/no" % i, "time": "/api/admin/ocr-alt/crop/e%d/time" % i}}


class Api:
    def __init__(self):
        self.events = [_event(1, "correct"), _event(2), _event(3, "wrong")]
        self.posts = []
        self.fail_post = False
        self.queries = []
        self.empty = False

    def totals(self):
        c = sum(e["verdict"] == "correct" for e in self.events)
        w = sum(e["verdict"] == "wrong" for e in self.events)
        u = sum(e["verdict"] == "unclear" for e in self.events)
        return {"events": len(self.events), "verified": c + w + u, "correct": c, "wrong": w, "unclear": u,
                "precision": c / (c + w) if c + w else None, "n_precision": c + w}

    def handle(self, route):
        req = route.request
        url = req.url
        ok = lambda b, s=200: route.fulfill(status=s, content_type="application/json", body=json.dumps(b))  # noqa: E731
        if "/crop/" in url:
            return route.fulfill(status=200, content_type="image/png", body=PNG)
        if url.endswith("/api/admin/session"):
            return ok({"enabled": True, "authenticated": True})
        if url.endswith("/api/admin/csrf"):
            return ok({"token": "tok"})
        if url.endswith("/verdict"):
            self.posts.append((req.post_data_json, req.headers.get("x-csrf-token")))
            return ok({"detail": "x"}, 500) if self.fail_post else ok({"ok": True})
        if "/api/admin/ocr-alt" in url:
            self.queries.append(url.split("?", 1)[1])
            evs = [] if self.empty else [e for e in self.events if "only=unverified" not in url or not e["verdict"]]
            nxt = None
            if "before=" not in url and not self.empty and "only=unverified" not in url:
                nxt, evs = "cursor1", evs[:2]
            elif "before=" in url:
                evs = evs[2:]
            return ok({"state": {"enabled": False, "shadow": True, "model_path": "/m/alt.onnx", "model_loaded": True,
                                 "since_start": {"frames": 10, "tried": 4, "recovered": 3}},
                       "totals": self.totals(), "events": evs, "next": nxt})
        return ok({})


def _page(browser, base_url, api, scheme="light", width=1280, hash_="#ocr2", lang="ro"):  # noqa: F811
    ctx = browser.new_context(service_workers="block", viewport={"width": width, "height": 900}, color_scheme=scheme)
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.route("**/api/admin/**", api.handle)
    page.goto(base_url + "/?lang=" + lang + hash_)
    return ctx, page, errors


def test_renders_state_totals_events(browser, base_url):  # noqa: F811
    api = Api()
    ctx, page, errors = _page(browser, base_url, api)
    try:
        page.wait_for_selector(".ocr2-ev")
        assert page.inner_text("#ocr2-heading") == "Alternativa OCR"
        txt = page.inner_text("#ocr2-summary")
        assert "/m/alt.onnx" in txt and "cadre 10" in txt and "50.0%" in txt and "N = 2" in txt
        assert page.locator(".ocr2-ev").count() == 2  # first page of 2 + "next"
        first = page.locator(".ocr2-ev").first
        assert "158" in first.inner_text() and "99%" in first.inner_text() and "CONSTANTA" in first.inner_text()
        assert page.locator(".ocr2-ev").first.locator("button[aria-pressed=true]").inner_text() == "Corect"
        img = first.locator("img").first
        assert "Decupaj" in img.get_attribute("alt")
        page.wait_for_function("() => document.querySelector('.ocr2-crop').naturalWidth > 0")
        # no nav entry, no console/CSP errors
        assert page.locator('.nav-item[data-route="ocr2"]').count() == 0
        assert not errors
    finally:
        ctx.close()


def _wait_posts(page, api, n):
    # the page updates optimistically, so the summary can change before the mocked POST is handled
    for _ in range(100):
        if len(api.posts) >= n:
            return
        page.wait_for_timeout(50)
    raise AssertionError(f"expected {n} verdict POSTs, got {len(api.posts)}")


def test_verdict_post_csrf_toggle_and_error_revert(browser, base_url):  # noqa: F811
    api = Api()
    ctx, page, _ = _page(browser, base_url, api)
    try:
        page.wait_for_selector(".ocr2-ev")
        second = page.locator(".ocr2-ev").nth(1)
        second.get_by_role("button", name="Greșit").click()
        page.wait_for_function("() => document.getElementById('ocr2-summary').innerText.includes('33.3%')")
        _wait_posts(page, api, 1)
        assert api.posts[-1] == ({"verdict": "wrong"}, "tok")
        assert second.get_by_role("button", name="Greșit").get_attribute("aria-pressed") == "true"
        # clicking the active verdict clears it
        second.get_by_role("button", name="Greșit").click()
        page.wait_for_function("() => document.getElementById('ocr2-summary').innerText.includes('50.0%')")
        _wait_posts(page, api, 2)
        assert api.posts[-1][0] == {"verdict": None}
        assert second.get_by_role("button", name="Greșit").get_attribute("aria-pressed") == "false"
        # failure: reverts, shows an inline error
        api.fail_post = True
        second.get_by_role("button", name="Corect").click()
        page.wait_for_selector(".ocr2-err:not([hidden])")
        assert "Verdictul nu s-a salvat" in second.inner_text()
        assert second.get_by_role("button", name="Corect").get_attribute("aria-pressed") == "false"
        assert "50.0%" in page.inner_text("#ocr2-summary")
    finally:
        ctx.close()


def test_filter_load_more_and_empty(browser, base_url):  # noqa: F811
    api = Api()
    ctx, page, _ = _page(browser, base_url, api)
    try:
        page.wait_for_selector("#ocr2-more:not([hidden])")
        page.click("#ocr2-more")
        page.wait_for_function("() => document.querySelectorAll('.ocr2-ev').length === 3")
        assert any("before=cursor1" in q for q in api.queries)
        page.check("#ocr2-only")
        page.wait_for_function("() => document.querySelectorAll('.ocr2-ev').length === 1")
        assert any("only=unverified" in q for q in api.queries)
        api.empty = True
        page.uncheck("#ocr2-only")
        page.wait_for_selector(".ocr2-empty")
        assert "1–4 rânduri" in page.inner_text("#ocr2-events")
        assert page.is_hidden("#ocr2-more")
    finally:
        ctx.close()


def test_precision_dash_when_nothing_verified(browser, base_url):  # noqa: F811
    api = Api()
    api.events = [_event(1)]
    ctx, page, _ = _page(browser, base_url, api)
    try:
        page.wait_for_selector(".ocr2-ev")
        assert "nicio verificare încă" in page.inner_text(".ocr2-precision")
        assert page.inner_text(".ocr2-precision dd") == "—"
    finally:
        ctx.close()


@pytest.mark.parametrize("scheme", ["light", "dark"])
def test_360px_no_horizontal_scroll(browser, base_url, scheme):  # noqa: F811
    api = Api()
    ctx, page, _ = _page(browser, base_url, api, scheme=scheme, width=360, lang="en")
    try:
        page.wait_for_selector(".ocr2-ev")
        page.wait_for_function("() => document.querySelector('.ocr2-crop').complete")
        assert page.evaluate("document.documentElement.scrollWidth") <= 360
        assert page.inner_text("#ocr2-heading") == "OCR alternative"
    finally:
        ctx.close()


def test_link_from_ocr_page(browser, base_url):  # noqa: F811
    api = Api()
    ctx, page, _ = _page(browser, base_url, api, hash_="#ocr")
    try:
        page.wait_for_selector("#ocr-heading")
        page.click("#view-ocr a[href='#ocr2']")
        page.wait_for_selector("#ocr2-heading")
    finally:
        ctx.close()
