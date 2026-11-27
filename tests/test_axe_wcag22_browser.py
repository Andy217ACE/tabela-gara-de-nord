# © 2026 Andy217Ace
"""axe-core (vendored in tests/vendor, pinned + SHA256-checked, MPL-2.0; never served by the app) on every
public route, light + dark, phone + desktop, with the WCAG 2.0/2.1/2.2 A/AA tag set. The app's strict CSP
is bypassed for the test context only (bypass_csp) so the script can be injected."""
import hashlib
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

AXE = Path(__file__).parent / "vendor" / "axe.min.js"
AXE_SHA256 = "b511cd9dec01c76f4b2ad1723b66b6db37d4c2eb4ed199076e1829d9ee7b75e3"
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
ROUTES = ["#", "#istoric", "#urmarite", "#trenuri", "#statii", "#statistici", "#clasamente",
          "#versiuni", "#sistem", "#setari", "#cum", "#admin"]
# Disabled rules, each justified:
DISABLED = {}


def test_vendored_axe_is_pinned():
    assert hashlib.sha256(AXE.read_bytes()).hexdigest() == AXE_SHA256


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width", [1280, 390])
def test_axe_wcag22_aa(browser, base_url, theme, width):  # noqa: F811
    ctx = browser.new_context(viewport={"width": width, "height": 844}, service_workers="block",
                              bypass_csp=True)
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    out = []
    try:
        for route in ROUTES:
            page = ctx.new_page()
            page.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}');")
            page.goto(base_url + "/" + route)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(300)
            page.add_script_tag(content=AXE.read_text(encoding="utf-8"))
            res = page.evaluate("([tags, rules]) => axe.run(document, {runOnly: {type: 'tag', values: tags},"
                                " rules})", [TAGS, {k: {"enabled": v} for k, v in DISABLED.items()}])
            for v in res["violations"]:
                out.append((route, v["id"], v["impact"], [n["target"] for n in v["nodes"][:3]]))
            page.close()
    finally:
        ctx.close()
    assert not out, "\n".join(map(str, out))


def test_axe_detects_violations_and_runs_target_size(browser, base_url):  # noqa: F811
    ctx = browser.new_context(service_workers="block", bypass_csp=True)
    page = ctx.new_page()
    page.goto(base_url + "/offline.html")
    page.add_script_tag(content=AXE.read_text(encoding="utf-8"))
    ids = page.evaluate("""([tags]) => { for (const x of [0, 12]) { const b = document.createElement('button'); b.style.cssText =
      'position:fixed;top:0;left:' + x + 'px;width:10px;height:10px'; document.body.append(b); }
      const c = document.createElement('img'); c.src = 'data:,'; document.body.append(c);
      return axe.run(document, {runOnly: {type: 'tag', values: tags}}).then(r => r.violations.map(v => v.id)); }""",
                        [TAGS])
    ctx.close()
    assert "button-name" in ids and "image-alt" in ids and "target-size" in ids, ids
