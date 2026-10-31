# © 2026 Andy217Ace
"""Real-browser checks for the top menu (bug Beta 1.05: on a phone with „Site pentru desktop”
the page is laid out ~980 px wide, below the old 1024 px breakpoint, so the menu was a fixed
BOTTOM bar shown zoomed out — tiny or off screen; no menu at the top). The menu must be a
sticky bar at the top at every width, with all sections reachable, ≥44 px targets, the active
item visible inside the bar, no horizontal page scroll and no console/CSP errors.
Skipped when Playwright (dev only) or its Chromium is unavailable."""
import re

import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

ANDROID_DESKTOP_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/130.0.0.0 Safari/537.36")
IOS_DESKTOP_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                  "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")
NAV = [("#", "Tabelă"), ("#istoric", "Istoric"), ("#urmarite", "Urmărite"),
       ("#trenuri", "Trenuri"), ("#statistici", "Statistici"), ("#clasamente", "Clasamente"),
       ("#statii", "Stații"), ("#sistem", "Sistem")]

# name: (context options, desktop_site) — desktop_site drops <meta name=viewport>, which is
# what Chrome Android / Safari iOS do in „desktop site” mode (layout viewport 980 px).
PHONE = dict(is_mobile=True, has_touch=True)
CASES = {
    "android-desktop-site": (dict(viewport={"width": 412, "height": 915}, device_scale_factor=2.625,
                                  user_agent=ANDROID_DESKTOP_UA, **PHONE), True),
    "ios-desktop-site": (dict(viewport={"width": 390, "height": 844}, device_scale_factor=3,
                              user_agent=IOS_DESKTOP_UA, **PHONE), True),
    "android-desktop-site-landscape": (dict(viewport={"width": 915, "height": 412},
                                            device_scale_factor=2.625,
                                            user_agent=ANDROID_DESKTOP_UA, **PHONE), True),
    "phone-390": (dict(viewport={"width": 390, "height": 844}, device_scale_factor=3, **PHONE), False),
    "phone-430": (dict(viewport={"width": 430, "height": 932}, device_scale_factor=3, **PHONE), False),
    "landscape-844": (dict(viewport={"width": 844, "height": 390}, device_scale_factor=3, **PHONE), False),
    "landscape-915": (dict(viewport={"width": 915, "height": 412}, device_scale_factor=2.625, **PHONE), False),
    "tablet-768": (dict(viewport={"width": 768, "height": 1024}, device_scale_factor=2, **PHONE), False),
    "tablet-820": (dict(viewport={"width": 820, "height": 1180}, device_scale_factor=2, **PHONE), False),
    "desktop-1024": (dict(viewport={"width": 1024, "height": 768}), False),
    "desktop-1440": (dict(viewport={"width": 1440, "height": 900}), False),
}

STATE = """() => {
  const bar = document.querySelector('.navbar'), nav = document.querySelector('.mainnav');
  const r = bar.getBoundingClientRect(), vv = window.visualViewport;
  const items = [...nav.querySelectorAll('.nav-item')];
  return {
    top: r.top, bottom: r.bottom, vvTop: vv.offsetTop, vvH: vv.height, ih: innerHeight, iw: innerWidth,
    pos: getComputedStyle(bar).position, display: getComputedStyle(bar).display,
    items: items.map(a => [a.getAttribute('href'), a.textContent.trim(),
                           a.getBoundingClientRect().height]),
    hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    zoomed: document.documentElement.classList.contains('zoomed-out'),
    inHeader: !!document.querySelector('header .mainnav'),
  };
}"""

REACH = """(href) => {
  const nav = document.querySelector('.mainnav');
  const a = nav.querySelector('.nav-item[href="' + href + '"]');
  a.scrollIntoView({block: 'nearest', inline: 'nearest'});
  const r = a.getBoundingClientRect(), n = nav.getBoundingClientRect();
  const x = Math.min(Math.max(r.left + r.width / 2, n.left + 1), n.right - 1);
  const hit = document.elementFromPoint(x, r.top + r.height / 2);
  return {inside: r.left >= n.left - 1 && r.right <= n.right + 1,
          hit: !!hit && (hit === a || a.contains(hit)), sy: scrollY,
          hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1};
}"""

ACTIVE_VISIBLE = """() => {
  const nav = document.querySelector('.mainnav');
  const a = nav.querySelector('.nav-item[aria-current="page"]');
  if (!a) return null;
  const r = a.getBoundingClientRect(), n = nav.getBoundingClientRect();
  return {href: a.getAttribute('href'), inside: r.left >= n.left - 1 && r.right <= n.right + 1};
}"""


def _open(browser, base_url, case, theme):  # noqa: F811
    opts, desktop_site = CASES[case]
    ctx = browser.new_context(service_workers="block", **opts)
    ctx.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}');")

    def route(r):
        url = r.request.url
        if not url.startswith(base_url):  # Google Fonts etc.: offline in tests, no console noise
            return r.fulfill(status=200, content_type="text/css", body="")
        path = url[len(base_url):].split("#")[0]
        if desktop_site and path in ("", "/", "/index.html"):
            resp = r.fetch()
            body = re.sub(r'<meta name="viewport"[^>]*>', "", resp.text())
            return r.fulfill(response=resp, body=body)
        return r.continue_()
    ctx.route("**/*", route)
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base_url + "/")
    page.wait_for_selector(".nav-item[aria-current='page']")
    page.wait_for_timeout(250)
    return ctx, page, errors


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("case", list(CASES))
def test_top_menu_visible_and_reachable(browser, base_url, case, theme):  # noqa: F811
    ctx, page, errors = _open(browser, base_url, case, theme)
    try:
        desktop_site = CASES[case][1]
        s = page.evaluate(STATE)
        if desktop_site and case != "android-desktop-site-landscape":
            assert s["iw"] >= 960, s  # the emulation really lays the page out like a desktop
        assert not s["inHeader"] and s["pos"] == "sticky" and s["display"] != "none", s
        # at the top of the visual viewport, fully on screen
        assert 0 <= s["top"] - s["vvTop"] < s["vvH"] * 0.5 and s["bottom"] <= s["vvTop"] + s["vvH"], s
        assert [(h, t) for h, t, _ in s["items"]] == NAV, s["items"]
        assert all(hgt >= 44 for _, _, hgt in s["items"]), s["items"]
        assert not s["hscroll"], s
        # „Site pentru desktop” in portrait → bigger menu; never on a real desktop
        portrait_ds = desktop_site and case != "android-desktop-site-landscape"
        assert s["zoomed"] == portrait_ds, s

        # sticky: after scrolling the page the bar is still at the top
        page.evaluate("window.scrollTo(0, 2000)")
        page.wait_for_timeout(100)
        s2 = page.evaluate(STATE)
        sy = page.evaluate("scrollY")
        # stuck at the top once the page scrolled past the header; before that it moves with it
        assert abs(s2["top"] - max(0, s["top"] - sy)) <= 1, (sy, s["top"], s2["top"])
        page.evaluate("window.scrollTo(0, 0)")

        for href, label in NAV:
            r = page.evaluate(REACH, href)
            assert r["inside"] and r["hit"] and not r["hscroll"], (href, r)
        # every link navigates; the active one is visible inside the bar
        for href, label in reversed(NAV):
            page.locator(f'.mainnav .nav-item[href="{href}"]').click()
            page.wait_for_timeout(120)
            act = page.evaluate(ACTIVE_VISIBLE)
            assert act and act["href"] == href and act["inside"], (href, act)
            assert not page.evaluate(STATE)["hscroll"], href
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("hash_, active", [("#statie?nume=BRASOV", "#statii"),
                                           ("#tren?nr=1636", "#trenuri"),
                                           ("#clasamente", "#clasamente")])
def test_deep_link_highlights_parent_and_reveals_it(browser, base_url, hash_, active):  # noqa: F811
    ctx, page, errors = _open(browser, base_url, "phone-390", "dark")
    try:
        page.goto(base_url + "/" + hash_)
        page.wait_for_timeout(400)
        act = page.evaluate(ACTIVE_VISIBLE)
        assert act and act["href"] == active and act["inside"], act
        assert not errors, errors
    finally:
        ctx.close()
