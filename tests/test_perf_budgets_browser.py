# © 2026 Andy217Ace
"""Frontend performance budgets per main route: phone viewport, 4x CPU throttling (CDP, Chromium only),
cold cache, no service worker. LCP / CLS / TBT (approximated: sum of PerformanceObserver long tasks
beyond 50 ms) / JS+CSS bytes on the wire / request count are asserted against tests/perf_budgets.json
(measured values + headroom; see the _note there). Set PERF_PRINT=1 to print the current measurements."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import ROOT, browser  # noqa: E402,F401  (shared fixture)
from tests.test_weather_browser import _serve, _store_observation  # noqa: E402

BUDGETS = json.loads((Path(__file__).parent / "perf_budgets.json").read_text(encoding="utf-8"))
ROUTES = [r for r in BUDGETS if not r.startswith("_")]

INIT = """(() => { window.__m = {lcp: 0, cls: 0, tbt: 0};
  const o = (t, f) => { try { new PerformanceObserver(l => l.getEntries().forEach(f)).observe({type: t, buffered: true}); } catch (e) {} };
  o('largest-contentful-paint', e => { window.__m.lcp = e.startTime; });
  o('layout-shift', e => { if (!e.hadRecentInput) window.__m.cls += e.value; });
  o('longtask', e => { window.__m.tbt += Math.max(0, e.duration - 50); });
})();"""


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    """Seeded trains + weather ENABLED with a stored observation, like production (a failing weather
    widget collapses and shifts the header, which would be a test-only layout shift)."""
    db = tmp_path_factory.mktemp("perf") / "p.db"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "dev_seed.py"), str(db)],
                   check=True, cwd=ROOT, capture_output=True)
    _store_observation(db)
    yield from _serve(db)


def measure(browser, base_url, route):  # noqa: F811
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, service_workers="block",
                              device_scale_factor=2, has_touch=True, is_mobile=True)
    ctx.add_init_script(INIT)
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
    cdp.send("Network.enable")
    kinds, done = {}, []
    cdp.on("Network.responseReceived", lambda e: kinds.__setitem__(e["requestId"], e["response"].get("mimeType", "")))
    cdp.on("Network.loadingFinished", lambda e: done.append((e["requestId"], e["encodedDataLength"])))
    try:
        page.goto(base_url + "/#" + ("" if route == "tabela" else route), wait_until="networkidle")
        page.wait_for_timeout(1500)  # late shifts / long tasks after the first paint
        m = page.evaluate("() => window.__m")
    finally:
        ctx.close()
    js = sum(n for i, n in done if "javascript" in kinds.get(i, ""))
    css = sum(n for i, n in done if "css" in kinds.get(i, ""))
    return {"lcp": round(m["lcp"]), "cls": round(m["cls"], 3), "tbt": round(m["tbt"]),
            "js_bytes": js, "css_bytes": css, "requests": len(done)}


@pytest.mark.parametrize("route", ROUTES)
def test_route_within_budget(browser, base_url, route):  # noqa: F811
    got = measure(browser, base_url, route)
    if os.environ.get("PERF_PRINT"):
        print("PERF", route, json.dumps(got))
    over = {k: (got[k], lim) for k, lim in BUDGETS[route].items() if got[k] > lim}
    assert not over, f"{route}: over budget (got, limit) {over}; all {got}"
