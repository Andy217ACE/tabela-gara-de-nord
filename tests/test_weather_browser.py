# © 2026 Andy217Ace
"""Weather widget v2 in a real browser: compact header button, details popover (humidity,
pressure, wind + gusts, precipitation split, 24 h sparkline with min/max and "acum"), stale
state, keyboard, no horizontal overflow at 360 px, text contrast in both themes, and no call
to Open-Meteo from the browser (CSP connect-src 'self').
Skipped when Playwright (dev only) or its Chromium is unavailable."""
import json
import math
import socket
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn  # noqa: E402

from app import weather as wx  # noqa: E402
from app.api import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from app.store import Store  # noqa: E402
from scripts.contrast_audit import AUDIT_JS  # noqa: E402
from tests.test_footer_browser import browser  # noqa: E402,F401  (shared fixture)

UTC = timezone.utc


@pytest.fixture(scope="module")
def base_url(tmp_path_factory):
    """The app with weather ENABLED (widget visible) but no poller/weather task (no network);
    a real observation is stored, so /api/weather answers for real."""
    db = tmp_path_factory.mktemp("wxbrowser") / "w.db"
    s = Store(str(db))
    s.migrate()
    s.add_weather(wx.parse_observation(_payload(5), datetime.now(UTC)))
    s.close()
    cfg = wx.WeatherConfig(url="http://127.0.0.1:9/none", latitude=44.4323, longitude=26.1063,
                           interval_s=900)
    settings = Settings(db_path=str(db), source_url="http://127.0.0.1:9/none", vapid_private_key="",
                        vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract",
                        poller_enabled=False, last_image_path=None, weather=cfg)
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(settings, start_poller=False),
                                           host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


def _payload(minutes_ago=5, **cur):
    now = datetime.now(UTC)
    t = (now - timedelta(minutes=minutes_ago)).replace(second=0, microsecond=0)
    h0 = t.replace(minute=0) - timedelta(hours=3)
    times = [(h0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(48)]
    temps = [round(11 + 5 * math.sin((h0.hour + i - 9) / 24 * 2 * math.pi), 1) for i in range(48)]
    current = {"time": t.strftime("%Y-%m-%dT%H:%M"), "interval": 900, "temperature_2m": 12.4,
               "relative_humidity_2m": 78, "apparent_temperature": 10.1, "is_day": 1,
               "precipitation": 0.8, "rain": 0.6, "showers": 0.2, "snowfall": 0.0,
               "weather_code": 61, "surface_pressure": 1011.7, "wind_speed_10m": 18.0,
               "wind_direction_10m": 225, "wind_gusts_10m": 34.0}
    current.update(cur)
    return {"latitude": 44.42, "longitude": 26.07, "utc_offset_seconds": 0,
            "current": current, "hourly": {"time": times, "temperature_2m": temps}}


def answer(minutes_ago=5, **cur):
    """A /api/weather body built by the real parser + presenter (server shape)."""
    now = datetime.now(UTC)
    return wx.present(wx.parse_observation(_payload(minutes_ago, **cur), now), now)


def open_page(browser, base_url, body, w=1280, h=800, theme="dark", view="carduri", reduced=False):  # noqa: F811
    ctx = browser.new_context(viewport={"width": w, "height": h}, service_workers="block",
                              reduced_motion="reduce" if reduced else "no-preference")
    ctx.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}');"
                        f"localStorage.setItem('tabela.view', '{view}');")
    external = []

    def route(r):
        url = r.request.url
        if body is not None and url.startswith(base_url + "/api/weather"):
            r.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        elif url.startswith(base_url):
            r.continue_()
        else:
            external.append(url)
            r.abort()
    ctx.route("**/*", route)
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(base_url + "/")
    page.wait_for_function("document.querySelector('.wx[data-state=ok], .wx[data-state=stale],"
                           " .wx[data-state=unavailable]')")
    page.wait_for_timeout(150)
    return ctx, page, external, errors


def slot(view):
    return '[data-weather-slot="panel"]' if view == "panou" else '[data-weather-slot="header"]'


HSCROLL = "document.documentElement.scrollWidth > document.documentElement.clientWidth"
POP_TEXT = "(s) => document.querySelector(s + ' .wx-pop').innerText"


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("w,h", [(1280, 800), (360, 740)])
def test_popover_content_and_no_overflow(browser, base_url, theme, w, h):  # noqa: F811
    ctx, page, external, errors = open_page(browser, base_url, answer(), w, h, theme)
    try:
        sel = slot("carduri")
        btn = page.locator(sel + " .wx-btn")
        assert btn.get_attribute("aria-expanded") == "false"
        assert not page.evaluate(HSCROLL)                      # compact button: no overflow
        r = btn.bounding_box()
        assert r["x"] >= 0 and r["x"] + r["width"] <= w
        btn.click()
        assert btn.get_attribute("aria-expanded") == "true"
        txt = page.evaluate(POP_TEXT, sel)
        for needle in ("Condiții curente (model Open-Meteo)", "12,4°C", "Se simte ca 10,1°C",
                       "Umiditate", "78 %", "Presiune", "1012 hPa", "Vânt", "18 km/h SV",
                       "dinspre sud-vest", "Rafale", "34 km/h", "Precipitații", "0,8 mm",
                       "ploaie 0,6 mm", "averse 0,2 mm", "Următoarele 24 h", "min ", "max ",
                       "acum", "Open-Meteo.com", "CC BY 4.0", "nu măsurătoarea unei stații"):
            assert needle in txt, (needle, txt)
        assert "zăpadă" not in txt                              # only components > 0
        assert not page.evaluate(HSCROLL)
        box = page.locator(sel + " .wx-pop").bounding_box()
        assert box["x"] >= -0.5 and box["x"] + box["width"] <= w + 0.5
        assert box["y"] >= r["y"] + r["height"] - 1             # below the button, never over it
        spark = page.locator(sel + " .wx-spark")
        assert spark.get_attribute("role") == "img"
        assert "Temperatura în următoarele 24 de ore" in spark.get_attribute("aria-label")
        assert spark.locator("path.wx-sp-line").count() >= 1
        assert spark.locator("text.wx-sp-max").count() == 1 and spark.locator("text.wx-sp-min").count() == 1
        assert spark.locator("line.wx-sp-now").count() == 1
        sb = spark.bounding_box()
        assert sb["width"] > 200 and sb["x"] >= 0 and sb["x"] + sb["width"] <= w
        assert page.locator(sel + " .wx-btn").get_attribute("aria-label").startswith("Vremea în București: 12 grade")
        assert external == [] and errors == []                  # nothing leaves the site
    finally:
        ctx.close()


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("w", [1280, 360])
def test_popover_text_contrast(browser, base_url, theme, w):  # noqa: F811
    ctx, page, _, _ = open_page(browser, base_url, answer(), w, 800, theme)
    try:
        page.click(slot("carduri") + " .wx-btn")
        bad = [f for f in page.evaluate(AUDIT_JS) if f["text"] and
               page.evaluate("(t) => [...document.querySelectorAll('.wx-pop *')].some("
                             "e => e.textContent.trim().startsWith(t))", f["text"][:20])]
        assert not bad, bad
        # SVG text is not covered by the audit: check it against the popover background
        got = page.evaluate("""() => {
          const parse = c => c.match(/[\\d.]+/g).map(Number);
          const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
                             return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
          const bg = parse(getComputedStyle(document.querySelector('.wx-pop')).backgroundColor);
          return [...document.querySelectorAll('.wx-spark text')].map(t => {
            const fg = parse(getComputedStyle(t).fill), a = lum(fg), b = lum(bg);
            return [t.textContent, (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)];
          });
        }""")
        assert got and all(r >= 4.5 for _, r in got), got
    finally:
        ctx.close()


def test_precipitation_zero_is_real_and_missing_is_dash(browser, base_url):  # noqa: F811
    zero = answer(precipitation=0.0, rain=0.0, showers=0.0, snowfall=0.0)
    ctx, page, _, _ = open_page(browser, base_url, zero)
    try:
        page.click(slot("carduri") + " .wx-btn")
        t = page.evaluate(POP_TEXT, slot("carduri"))
        assert "Precipitații\n0,0 mm" in t and "ploaie" not in t and "averse" not in t
    finally:
        ctx.close()
    missing = answer(precipitation=None, rain=None, showers=None, snowfall=None,
                     relative_humidity_2m=None, surface_pressure=None, wind_gusts_10m=None)
    ctx, page, _, _ = open_page(browser, base_url, missing)
    try:
        page.click(slot("carduri") + " .wx-btn")
        t = page.evaluate(POP_TEXT, slot("carduri"))
        for label in ("Umiditate", "Presiune", "Rafale", "Precipitații"):
            assert f"{label}\n—" in t, (label, t)
        assert "0 %" not in t and "0 hPa" not in t and "0,0 mm" not in t
    finally:
        ctx.close()


def test_snow_component_shown_when_positive(browser, base_url):  # noqa: F811
    ctx, page, _, _ = open_page(browser, base_url, answer(
        weather_code=73, precipitation=0.4, rain=0.0, showers=0.0, snowfall=0.6))
    try:
        page.click(slot("carduri") + " .wx-btn")
        t = page.evaluate(POP_TEXT, slot("carduri"))
        assert "zăpadă 0,6 cm" in t and "ploaie" not in t
        assert "wx-i-snow" in page.locator(slot("carduri") + " .wx-btn svg").first.get_attribute("class")
    finally:
        ctx.close()


def test_night_and_day_icon_variants(browser, base_url):  # noqa: F811
    ctx, page, _, _ = open_page(browser, base_url, answer(is_day=0, weather_code=0))
    try:
        assert "wx-i-moon" in page.locator(slot("carduri") + " .wx-btn svg").first.get_attribute("class")
        assert page.locator(slot("carduri") + " .wx").get_attribute("data-daynight") == "night"
        assert "noapte" in page.locator(slot("carduri") + " .wx-btn").get_attribute("aria-label")
    finally:
        ctx.close()
    ctx, page, _, _ = open_page(browser, base_url, answer(is_day=1, weather_code=0))
    try:
        assert "wx-i-sun" in page.locator(slot("carduri") + " .wx-btn svg").first.get_attribute("class")
        assert page.locator(slot("carduri") + " .wx").get_attribute("data-daynight") == "day"
    finally:
        ctx.close()


@pytest.mark.parametrize("w", [1280, 360])
def test_stale_state_after_45_minutes(browser, base_url, w):  # noqa: F811
    ctx, page, _, _ = open_page(browser, base_url, answer(minutes_ago=75), w, 740)
    try:
        sel = slot("carduri")
        assert page.locator(sel + " .wx").get_attribute("data-state") == "stale"
        assert "date vechi" in page.locator(sel + " .wx-btn").inner_text()
        assert not page.evaluate(HSCROLL)
        page.click(sel + " .wx-btn")
        t = page.evaluate(POP_TEXT, sel)
        assert "Datele sunt vechi" in t and "observat" in t and "acum\n" not in t
        assert not page.evaluate(HSCROLL)
    finally:
        ctx.close()


def test_no_hourly_series_means_no_chart(browser, base_url):  # noqa: F811
    body = answer()
    body["hourly"] = None
    ctx, page, _, _ = open_page(browser, base_url, body)
    try:
        page.click(slot("carduri") + " .wx-btn")
        assert page.locator(slot("carduri") + " .wx-spark").count() == 0
        assert "Următoarele 24 h" not in page.evaluate(POP_TEXT, slot("carduri"))
    finally:
        ctx.close()


def test_keyboard_open_and_escape(browser, base_url):  # noqa: F811
    ctx, page, _, _ = open_page(browser, base_url, answer())
    try:
        sel = slot("carduri")
        page.locator(sel + " .wx-btn").focus()
        page.keyboard.press("Enter")
        assert page.locator(sel + " .wx-btn").get_attribute("aria-expanded") == "true"
        assert page.locator(sel + " .wx-pop").is_visible()
        page.keyboard.press("Tab")                              # next: the attribution link
        assert page.evaluate("document.activeElement.tagName") == "A"
        page.keyboard.press("Escape")
        assert page.locator(sel + " .wx-btn").get_attribute("aria-expanded") == "false"
        assert not page.locator(sel + " .wx-pop").is_visible()
        assert page.evaluate("document.activeElement.classList.contains('wx-btn')")
    finally:
        ctx.close()


def test_reduced_motion_has_no_animation(browser, base_url):  # noqa: F811
    ctx, page, _, _ = open_page(browser, base_url, answer(), reduced=True)
    try:
        page.click(slot("carduri") + " .wx-btn")
        names = page.evaluate("[...document.querySelectorAll('.wx, .wx *')]"
                              ".map(e => getComputedStyle(e).animationName).filter(n => n !== 'none')")
        assert names == []
    finally:
        ctx.close()


def test_panou_title_bar_widget_popover(browser, base_url):  # noqa: F811
    ctx, page, _, _ = open_page(browser, base_url, answer(), 1280, 800, "dark", "panou")
    try:
        sel = slot("panou")
        page.wait_for_selector(sel + " .wx-btn")
        page.click(sel + " .wx-btn")
        assert "Umiditate" in page.evaluate(POP_TEXT, sel)
        assert not page.evaluate(HSCROLL)
    finally:
        ctx.close()


def test_real_api_end_to_end_with_a_stored_observation(browser, base_url):  # noqa: F811
    """No mocking: the stored observation goes DB -> /api/weather -> widget, and nothing
    is requested from any other origin (CSP connect-src 'self')."""
    ctx, page, external, errors = open_page(browser, base_url, None, 360, 740)
    try:
        sel = slot("carduri")
        assert page.locator(sel + " .wx").get_attribute("data-state") == "ok"
        page.click(sel + " .wx-btn")
        t = page.evaluate(POP_TEXT, sel)
        assert "12,4°C" in t and "78 %" in t and "1012 hPa" in t and "Următoarele 24 h" in t
        assert not page.evaluate(HSCROLL)
        assert external == [] and errors == []
    finally:
        ctx.close()
