# © 2026 Andy217Ace
"""Weather widget: static files, CSP-safety, wiring next to the clocks, SW, attribution."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from tests.test_api import settings

WEB = Path(__file__).resolve().parent.parent / "web"
ROOT = WEB.parent


@pytest.fixture
def client():
    with TestClient(create_app(settings(), start_poller=False)) as c:
        yield c


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


def test_files_served_with_copyright_header(client):
    js, css = client.get("/weather.js"), client.get("/weather.css")
    assert js.status_code == 200 and css.status_code == 200
    assert js.text.startswith("// © 2026 Andy217Ace")
    assert css.text.startswith("/* © 2026 Andy217Ace */")
    assert js.headers.get("cache-control") == "no-cache"
    assert (ROOT / "app" / "weather.py").read_text(encoding="utf-8").startswith(
        "# © 2026 Andy217Ace")


def test_weather_js_is_csp_safe():
    js = read("weather.js")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", 'setAttribute("style"', "cssText"):
        assert bad not in js, bad
    assert "textContent" in js and "createElementNS" in js
    assert "/api/weather" in js
    assert "open-meteo.com" not in js.replace("https://open-meteo.com/", "")  # no API calls
    assert "api.open-meteo.com" not in js


def test_weather_js_behaviour_markers():
    js = read("weather.js")
    for needle in ("Europe/Bucharest", "visibilitychange", "Escape", "aria-expanded",
                   "date vechi", "meteo indisponibilă", "se simte",
                   "Condiții curente (model Open-Meteo)", "noopener noreferrer", "_blank",
                   "CC BY 4.0", "Vremea în București", "setInterval", "dinspre",
                   "TabelaApp", "data-weather-slot"):
        assert needle in js, needle
    # Romanian cardinal names for the aria summary
    for name in ("nord", "nord-est", "est", "sud-est", "sud", "sud-vest", "vest", "nord-vest"):
        assert f'"{name}"' in js, name
    # ten icon kinds, drawn with SVG
    for kind in ("sun", "moon", "partly", "cloud", "fog", "drizzle", "rain", "freezing",
                 "snow", "showers", "thunder"):
        assert re.search(rf"\b{kind}\b", js), kind


def test_weather_js_v2_details_chart_and_fields():
    js = read("weather.js")
    for needle in ("Umiditate", "Presiune", "hPa", "Rafale", "Precipitații", "relative_humidity_pct",
                   "surface_pressure_hpa", "wind_gusts_kmh", "rain_mm", "showers_mm", "snowfall_cm",
                   "hourly", "temperature_c", "Următoarele 24 h", '"acum"', "observat", "is_day",
                   "dataset.daynight", "wx-spark", 'role: "img"', "aria-label",
                   "ploaie", "averse", "zăpadă", "Europe/Bucharest"):
        assert needle in js, needle
    # the sparkline is drawn only from real values: nulls break the line, never become 0
    assert "isNum(v)" in js and "isNum(c[1]) && c[1] > 0" in js
    # no chart without a series (never a flat line)
    assert "box.hidden = true" in js


def test_weather_css_v2_has_chart_tiles_and_stale_variants():
    css = read("weather.css")
    for sel in (".wx-spark", ".wx-tiles", ".wx-tile", ".wx-chart", ".wx-sp-line", ".wx-sp-area",
                ".wx-sp-now", ".wx-sp-max", ".wx-sp-min", '[data-daynight="night"]',
                ".wx-chart.is-stale"):
        assert sel in css, sel
    assert "max-width: 599px" in css and "100vw - 32px" in css       # phone popover, no overflow
    assert "style=" not in read("weather.js")
    # chart colours come from the theme tokens, never raw colours
    block = css[css.index(".wx-spark"):css.index("/* ---------- atribuire")]
    assert not re.search(r"#[0-9a-fA-F]{3,8}|rgba?\(", block)


def test_weather_css_theme_motion_and_contrast():
    css = read("weather.css")
    assert "prefers-reduced-motion" in css
    assert "var(--text" in css and "var(--surface" in css   # theme-aware tokens
    assert '[data-state="stale"]' in css and '[data-state="loading"]' in css
    assert ":focus-visible" in css
    assert "tabular-nums" in css
    # header clock is hidden while the Panou (with its own clock) is shown
    assert 'html[data-view="panou"]' in css


def test_index_wires_header_clock_and_weather():
    html = read("index.html")
    assert '<link rel="stylesheet" href="weather.css">' in html
    assert re.search(r'<script src="weather.js" defer></script>', html)
    # weather.js runs after panel.js so the Panou slot exists
    assert html.index('src="panel.js"') < html.index('src="weather.js"')
    head = re.search(r'<header class="topbar">(.*?)</header>', html, re.S).group(1)
    assert 'id="hdr-clock"' in head and 'data-weather-slot="header"' in head
    assert head.index('id="hdr-clock"') < head.index('data-weather-slot="header"')


def test_panel_has_weather_slot_beside_clock():
    js = read("panel.js")
    assert 'setAttribute("data-weather-slot", "panel")' in js
    assert "pnl-clockwx" in js


def test_footer_and_panel_credit_carry_open_meteo_attribution():
    html = read("index.html")
    footer = re.search(r'<footer class="footer">(.*?)</footer>', html, re.S).group(1)
    span = re.search(r'<span class="footer-meteo"[^>]*>(.*?)</span>', footer, re.S)
    assert span, "separate span"
    assert "Meteo: " in span.group(1) and "Open-Meteo.com" in span.group(1)
    a = re.search(r'<a [^>]*href="https://open-meteo.com/"[^>]*>', span.group(1)).group(0)
    assert 'rel="noopener noreferrer"' in a and 'target="_blank"' in a
    # after the CFR line
    assert footer.index("neafiliat CFR") < footer.index("footer-meteo")
    js = read("panel.js")
    assert "Meteo: " in js and "https://open-meteo.com/" in js and "wx-credit" in js


def test_service_worker_precaches_weather_files_and_bumped_version():
    js = read("sw.js")
    shell = re.search(r"var SHELL = \[(.*?)\];", js, re.S).group(1)
    assert '"/weather.js"' in shell and '"/weather.css"' in shell
    v = re.search(r'var VERSION = "v(\d+)"', js).group(1)
    assert int(v) >= 26          # bumped with the weather v2 files (Beta 1.25)
    # /api/weather is never cached by the SW (the widget keeps the last value in memory
    # and marks it "date vechi" when a refresh fails)
    assert "/api/weather" not in js


def test_readme_documents_weather():
    md = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Meteo" in md
    for needle in ("WEATHER_ENABLED", "WEATHER_INTERVAL_S", "WEATHER_LAT", "WEATHER_LON",
                   "WEATHER_URL", "CC BY 4.0", "Open-Meteo", "model"):
        assert needle in md, needle


def test_readme_documents_weather_v2_fields_and_schema_v8():
    md = (ROOT / "README.md").read_text(encoding="utf-8")
    for needle in ("umiditate", "presiune", "rafale", "schema v8", "hourly=temperature_2m",
                   "timezone=UTC", "forecast_days=2", "relative_humidity_pct", "wind_gusts_kmh",
                   "hourly_json", "NULL"):
        assert needle in md, needle


def test_changelog_and_version_for_weather_v2():
    assert (ROOT / "VERSION").read_text(encoding="utf-8").strip() == "Beta 1.25"
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = log.index("## Beta 1.25")
    assert first < log.index("## Beta 1.24")                   # newest on top
    section = log[first:log.index("## Beta 1.24")]
    for needle in ("schema DB v8", "umiditate", "grafic", "date vechi", "CC BY 4.0", "backup"):
        assert needle.lower() in section.lower(), needle


def test_every_clock_shows_seconds_with_tabular_digits():
    wjs = (WEB / "weather.js").read_text(encoding="utf-8")
    m = re.search(r"var fmtClock = new Intl\.DateTimeFormat\((.*?)\);", wjs, re.S)
    assert m and 'second: "2-digit"' in m.group(1) and 'timeZone: TZ' in m.group(1)
    assert "setInterval(tickClock, 1000)" in wjs
    pjs = (WEB / "panel.js").read_text(encoding="utf-8")
    m = re.search(r"var fmtTime = new Intl\.DateTimeFormat\((.*?)\);", pjs, re.S)
    assert m and 'second: "2-digit"' in m.group(1)
    assert "setInterval(tickClock, 1000)" in pjs
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<span class="hdr-clock-time">--:--:--</span>' in html
    for css, sel in (("weather.css", ".hdr-clock-time"), ("panel.css", ".pnl-clock-time")):
        block = re.search(re.escape(sel) + r"\s*\{(.*?)\}", (WEB / css).read_text(encoding="utf-8"),
                          re.S).group(1)
        assert "font-variant-numeric: tabular-nums" in block
