# © 2026 Andy217Ace
"""Beta 1.67 (F): phones (≤ 700 px) get a bottom bar (Tabelă/Istoric/Trenuri/Statistici + „Mai mult”),
collapsible filters on Istoric/Trenuri, a two-level Statistici page and a denser Istoric.
Desktop/tablet keep the sticky top bar. Skipped without Playwright/Chromium."""
import pytest

pytest.importorskip("playwright.sync_api")

from tests.test_footer_browser import base_url, browser  # noqa: E402,F401  (shared fixtures)

PHONE = dict(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
DESKTOP = dict(viewport={"width": 1280, "height": 800})
BAR = ["tabela", "istoric", "trenuri", "statistici"]

BAR_STATE = """() => {
  const vis = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden';
  const bar = document.querySelector('.navbar'), r = bar.getBoundingClientRect();
  return {pos: getComputedStyle(bar).position, top: r.top, bottom: r.bottom, ih: innerHeight,
          items: [...document.querySelectorAll('.mainnav .nav-item')].filter(vis).map(a => a.dataset.route),
          more: vis(document.getElementById('nav-more-btn')),
          heights: [...document.querySelectorAll('.mainnav .nav-item, #nav-more-btn')].filter(vis)
                     .map(e => e.getBoundingClientRect().height),
          padBottom: parseFloat(getComputedStyle(document.body).paddingBottom),
          hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1};
}"""


def _open(browser, base_url, opts, hash_="", theme="light"):  # noqa: F811
    ctx = browser.new_context(service_workers="block", **opts)
    ctx.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}');")
    ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base_url) else r.abort())
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource") else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base_url + "/" + hash_)
    page.wait_for_selector(".nav-item[aria-current='page'], .nav-more-link[aria-current='page']", state="attached")
    page.wait_for_timeout(200)
    return ctx, page, errors


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_phone_bottom_bar(browser, base_url, theme):  # noqa: F811
    ctx, page, errors = _open(browser, base_url, PHONE, theme=theme)
    try:
        s = page.evaluate(BAR_STATE)
        assert s["pos"] == "fixed" and abs(s["bottom"] - s["ih"]) <= 1, s
        assert s["items"] == BAR and s["more"], s
        assert all(h >= 44 for h in s["heights"]), s
        assert s["padBottom"] >= s["bottom"] - s["top"] - 1, s   # content never hidden under the bar
        assert not s["hscroll"], s
        for route in reversed(BAR):
            page.locator(f".mainnav .nav-item[data-route='{route}']").click()
            page.wait_for_timeout(120)
            assert page.get_attribute(f".mainnav .nav-item[data-route='{route}']", "aria-current") == "page"
            assert page.locator(".mainnav .nav-item[aria-current='page']").count() == 1
        assert not errors, errors
    finally:
        ctx.close()


def test_desktop_keeps_top_bar(browser, base_url):  # noqa: F811
    ctx, page, errors = _open(browser, base_url, DESKTOP)
    try:
        s = page.evaluate(BAR_STATE)
        assert s["pos"] == "sticky" and s["top"] < 200, s
        assert len(s["items"]) == 8 and not s["more"], s
        assert page.locator(".navbar > [data-lang-toggle]").is_visible()
        assert not page.locator(".filt-toggle").first.is_visible()
        assert not errors, errors
    finally:
        ctx.close()


def test_more_menu_keyboard(browser, base_url):  # noqa: F811
    ctx, page, errors = _open(browser, base_url, PHONE)
    try:
        btn = page.locator("#nav-more-btn")
        menu = page.locator("#nav-more-menu")
        assert btn.get_attribute("aria-expanded") == "false" and not menu.is_visible()
        btn.focus()
        page.keyboard.press("Enter")
        assert btn.get_attribute("aria-expanded") == "true" and menu.is_visible()
        routes = menu.locator(".nav-more-link").evaluate_all("as => as.map(a => a.dataset.route)")
        assert routes == ["urmarite", "clasamente", "statii", "sistem", "versiuni", "setari", "cum"], routes
        assert menu.locator("[data-lang-toggle]").is_visible()   # the language switch lives here on phones
        # Tab walks into the menu; Escape closes it and gives the focus back to the button
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.closest('#nav-more-menu') !== null")
        page.keyboard.press("Escape")
        assert btn.get_attribute("aria-expanded") == "false" and not menu.is_visible()
        assert page.evaluate("document.activeElement.id") == "nav-more-btn"
        # a link of the menu: navigates, closes the menu, marks itself and the „Mai mult” button
        btn.click()
        menu.locator(".nav-more-link[data-route='clasamente']").click()
        page.wait_for_function("location.hash === '#clasamente'")
        assert not menu.is_visible()
        # (the page stylesheet loads first, then route() marks the item)
        page.wait_for_selector("#nav-more-menu .nav-more-link[data-route='clasamente'][aria-current='page']", state="attached")
        assert page.locator(".mainnav .nav-item[aria-current='page']").count() == 0 or \
            not page.locator(".mainnav .nav-item[aria-current='page']").is_visible()
        # deep link to a child route: its parent (Stații) is the current one in the menu
        page.goto(base_url + "/#statie?nume=BRASOV")
        page.wait_for_selector("#nav-more-menu .nav-more-link[data-route='statii'][aria-current='page']", state="attached")
        # a click outside closes it
        btn.click()
        page.mouse.click(200, 300)
        assert not menu.is_visible()
        assert not errors, errors
    finally:
        ctx.close()


@pytest.mark.parametrize("hash_,form", [("#istoric", "#h-form"), ("#trenuri", "#st-trenuri .st-filters")])
def test_filters_collapse_on_phone(browser, base_url, hash_, form):  # noqa: F811
    ctx, page, errors = _open(browser, base_url, PHONE, hash_)
    try:
        tog = page.locator(f"#view-{hash_[1:]} .filt-toggle")
        tog.wait_for()
        assert tog.get_attribute("aria-expanded") == "false" and not page.locator(form).is_visible()
        assert tog.text_content() == "Filtre (0)"
        tog.click()
        assert tog.get_attribute("aria-expanded") == "true" and page.locator(form).is_visible()
        page.locator(form).locator("input[type=search], input[name=train]").first.fill("1")
        page.wait_for_timeout(100)
        assert tog.text_content() == "Filtre (1)"
        tog.click()
        assert not page.locator(form).is_visible()
        assert not errors, errors
    finally:
        ctx.close()

    ctx, page, errors = _open(browser, base_url, DESKTOP, hash_)
    try:
        page.locator(form).wait_for()
        assert page.locator(form).is_visible() and not page.locator(f"#view-{hash_[1:]} .filt-toggle").is_visible()
    finally:
        ctx.close()


def test_statistici_two_levels(browser, base_url):  # noqa: F811
    ctx, page, errors = _open(browser, base_url, PHONE, "#statistici")
    try:
        page.wait_for_selector(".ss-acc-btn")
        btns = page.locator(".ss-acc-btn")
        assert btns.count() >= 3   # at least Probleme, a part, Glosar (seed data)
        assert all(b == "false" for b in btns.evaluate_all("bs => bs.map(b => b.getAttribute('aria-expanded'))"))
        assert page.locator(".ss-fig").evaluate_all("fs => fs.filter(f => f.getClientRects().length).length") == 0
        # the chart part opens on tap; its lazy sections and charts are built then
        part = page.locator(".ss-part .ss-acc-btn").last
        part.click()
        assert part.get_attribute("aria-expanded") == "true"
        part.evaluate("b => b.scrollIntoView()")   # still lazy inside the open group: built near the screen
        page.wait_for_function("""() => [...document.querySelectorAll('.ss-fig svg.ss-svg')]
          .some(s => s.getClientRects().length > 0)""")
        part.click()
        assert part.get_attribute("aria-expanded") == "false"
        assert not errors, errors
    finally:
        ctx.close()

    ctx, page, errors = _open(browser, base_url, DESKTOP, "#statistici")
    try:
        page.wait_for_selector(".ss-problems, .ss-summary")
        assert page.locator(".ss-acc-btn").count() == 0
    finally:
        ctx.close()
