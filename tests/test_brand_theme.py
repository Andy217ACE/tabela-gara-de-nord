# © 2026 Andy217Ace
"""Logo everywhere (icons, favicons, og image), theme toggle, and the cross-branch glue
(Panou ↔ Istoric link, /api/config single source, `uncertain` marker, follow button)."""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.api import create_app
from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


@pytest.fixture
def client():
    s = Settings(db_path=":memory:", source_url="https://example.com/x",
                 vapid_private_key="", vapid_public_key="", vapid_subject="mailto:a@b.c",
                 tesseract_cmd="tesseract")
    with TestClient(create_app(s, start_poller=False)) as c:
        yield c


def html():
    return (WEB / "index.html").read_text(encoding="utf-8")


# -- logo assets ---------------------------------------------------------------------

ICON_SIZES = {
    "icons/logo.png": (512, 512),
    "icons/logo-96.png": (96, 96),
    "icons/logo-192.png": (192, 192),
    "icons/icon-192.png": (192, 192),
    "icons/icon-512.png": (512, 512),
    "icons/icon-maskable-512.png": (512, 512),
    "icons/apple-touch-icon.png": (180, 180),
    "icons/favicon-32.png": (32, 32),
    "icons/favicon-16.png": (16, 16),
    "icons/og-image.png": (1200, 630),
}


@pytest.mark.parametrize("path,size", sorted(ICON_SIZES.items()))
def test_icon_files_exist_with_sizes(client, path, size):
    with Image.open(WEB / path) as im:
        assert im.size == size, path
    assert client.get("/" + path).status_code == 200


def test_brand_source_kept_and_placeholders_gone():
    with Image.open(ROOT / "docs" / "brand" / "logo-source.png") as im:
        assert im.size == (1254, 1254) and im.mode == "RGBA"
    for old in ("icons/logo.svg", "icons/icon.svg", "icons/icon-32.png"):
        assert not (WEB / old).exists(), old
    for f in ("index.html", "offline.html", "manifest.webmanifest", "sw.js", "app.js",
              "panel.js"):
        text = (WEB / f).read_text(encoding="utf-8")
        assert not re.search(r'[\w/-]+\.svg', text), f
        assert not re.search(r'[/"]icon-32\.png', text), f


def test_logo_png_is_clean_and_centered():
    with Image.open(WEB / "icons" / "logo.png") as im:
        a = im.convert("RGBA").getchannel("A")
        box = a.getbbox()
    left, top, right, bottom = box
    # consistent transparent margin, centred (the shadow slab under the tile is gone)
    assert abs(left - (512 - right)) <= 2 and abs(top - (512 - bottom)) <= 12
    assert 10 <= min(left, top) <= 40
    assert a.getpixel((256, 4)) == 0 and a.getpixel((256, 508)) == 0


def test_opaque_icons_have_no_transparency():
    for name in ("apple-touch-icon.png", "icon-maskable-512.png"):
        with Image.open(WEB / "icons" / name) as im:
            rgba = im.convert("RGBA")
            assert rgba.getchannel("A").getextrema() == (255, 255), name
    with Image.open(WEB / "icons" / "icon-maskable-512.png") as im:
        r, g, b = im.convert("RGB").getpixel((4, 4))
        assert b > r + 60 and b > g  # solid logo blue behind the safe zone


def test_favicon_ico_sizes(client):
    with Image.open(WEB / "favicon.ico") as im:
        assert im.ico.sizes() >= {(16, 16), (32, 32), (48, 48)}
    r = client.get("/favicon.ico")
    assert r.status_code == 200 and r.content[:4] == b"\x00\x00\x01\x00"


def test_manifest_icons_and_colours():
    m = json.loads((WEB / "manifest.webmanifest").read_text(encoding="utf-8"))
    srcs = {i["src"]: i for i in m["icons"]}
    assert srcs["icons/icon-maskable-512.png"]["purpose"] == "maskable"
    for src, i in srcs.items():
        with Image.open(WEB / src) as im:
            assert f"{im.width}x{im.height}" == i["sizes"]
    assert m["theme_color"] == "#0a0d12" and m["background_color"] == "#0a0d12"


def test_og_and_twitter_tags():
    h = html()
    want = {
        'property="og:image" content="https://tabelacfr.ddns.net/icons/og-image.png"',
        'property="og:url" content="https://tabelacfr.ddns.net/"',
        'property="og:locale" content="ro_RO"',
        'name="twitter:card" content="summary_large_image"',
    }
    for w in want:
        assert w in h, w
    assert re.search(r'property="og:title" content="[^"]+"', h)
    assert re.search(r'property="og:description" content="[^"]+"', h)


def test_logo_used_everywhere():
    h = html()
    assert re.search(r'<img id="logo" [^>]*src="icons/logo-96.png" srcset="icons/logo-96.png 1x, '
                     r'icons/logo-192.png 2x"[^>]*width="46" height="46"', h)
    assert 'class="logo logo-boot"' in h            # loading screen
    assert 'class="logo logo-footer"' in h          # footer mark
    off = (WEB / "offline.html").read_text(encoding="utf-8")
    assert 'class="logo logo-offline" src="/icons/logo-96.png"' in off
    assert "logo-96.png" in (WEB / "panel.js").read_text(encoding="utf-8")  # Panou title bar
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(r'<img [^>]*src="web/icons/logo.png"[^>]*width="96"', readme.split("\n## ")[0])


@pytest.mark.parametrize("name", ["index.html", "offline.html"])
def test_pages_have_no_inline_style_or_script(name):
    h = (WEB / name).read_text(encoding="utf-8")
    assert h.startswith("<!doctype html>\n<!-- © 2026 Andy217Ace -->")
    assert not re.search(r"<style\b", h, re.I)
    assert not re.search(r"\sstyle\s*=", h, re.I)
    assert not re.search(r"\son[a-z]+\s*=", h, re.I)
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", h, re.I | re.S):
        assert "src=" in m.group(1) and m.group(2).strip() == ""


def test_offline_page_served(client):
    r = client.get("/offline.html")
    assert r.status_code == 200 and "Ești offline" in r.text


# -- theme toggle --------------------------------------------------------------------

def test_theme_init_script_in_head_before_styles(client):
    h = html()
    head = h.split("</head>")[0]
    m = re.search(r'<script src="theme-init.js"></script>', head)
    assert m, "theme-init.js must load synchronously (no defer) in <head>"
    assert m.start() < head.index('<link rel="stylesheet"')
    js = client.get("/theme-init.js")
    assert js.status_code == 200 and js.text.startswith("// © 2026 Andy217Ace")
    for needle in ("localStorage", "dataset.theme", 'meta[name="theme-color"]', "try {",
                   "tabela:theme"):
        assert needle in js.text, needle
    for bad in ("innerHTML", ".style.", "eval("):
        assert bad not in js.text


def test_theme_button_present_and_labelled():
    h = html()
    m = re.search(r'<button class="theme-btn" type="button" id="theme-btn"([^>]*)>', h)
    assert m
    # a 3-state cycle: the label carries the state; no aria-pressed (reads as on/off)
    assert 'aria-label="Temă: automată"' in m.group(1) and "aria-pressed" not in m.group(1)
    app = (WEB / "app.js").read_text(encoding="utf-8")
    theme_fn = app.split("function renderThemeButtons")[1].split("function initTheme")[0]
    assert "aria-pressed" not in theme_fn
    for needle in ('"Temă: "', "TabelaTheme"):
        assert needle in app, needle
    panel = (WEB / "panel.js").read_text(encoding="utf-8")
    assert "data-theme-toggle" in panel  # reachable in Panou fullscreen too
    theme = (WEB / "theme-init.js").read_text(encoding="utf-8")
    for label in ("automată", "luminoasă", "întunecată"):
        assert label in theme


def test_css_supports_both_forced_themes():
    css = (WEB / "style.css").read_text(encoding="utf-8")
    pcss = (WEB / "panel.css").read_text(encoding="utf-8")
    assert ':root[data-theme="light"] {' in css and ':root[data-theme="dark"]' in css
    assert ':root:not([data-theme="dark"])' in css  # media query yields to a forced dark
    assert ':root[data-theme="light"] .pnl {' in pcss
    assert ':root:not([data-theme="dark"]) .pnl' in pcss
    # every token the light theme sets is also set for the default (dark) theme
    dark = set(re.findall(r"(--[\w-]+):", re.search(r":root \{(.*?)\}", css, re.S).group(1)))
    light = set(re.findall(r"(--[\w-]+):", re.search(r':root\[data-theme="light"\] \{(.*?)\}',
                                                       css, re.S).group(1)))
    assert light <= dark
    assert ".theme-btn" in css and "min-width" not in css.split(".theme-btn {")[1][:20]
    assert re.search(r"\.theme-btn \{[^}]*width: 44px;[^}]*height: 44px;", css, re.S)


# -- cross-branch glue -----------------------------------------------------------------

def test_history_link_from_panel_is_understood_by_history_view():
    panel = (WEB / "panel.js").read_text(encoding="utf-8")
    hist = (WEB / "history.js").read_text(encoding="utf-8")
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert '"#istoric?train=" + ' in panel and '"&date=" + ' in panel
    fields = re.search(r"var FIELDS = \[([^\]]+)\]", hist).group(1)
    assert '"train"' in fields and '"date"' in fields
    assert '"#istoric": "istoric"' in app and "new URLSearchParams" in app


def test_config_single_source():
    app = (WEB / "app.js").read_text(encoding="utf-8")
    panel = (WEB / "panel.js").read_text(encoding="utf-8")
    assert app.count('fetch("/api/config"') == 1
    assert "refresh_s" in app and "stale_after_s" in app
    assert "REFRESH_MS" not in app and "STALE_S = 180" not in app
    assert "/api/config" not in panel.replace("GET /api/config", "")


def test_uncertain_marker_in_cards_panel_history():
    css = (WEB / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.is-uncertain \{[^}]*dotted", css, re.S)
    for f in ("app.js", "panel.js", "history.js"):
        js = (WEB / f).read_text(encoding="utf-8")
        assert "citire nesigură" in js or "UNSURE" in js, f
        assert "uncertain" in js and "is-uncertain" in js, f


def test_board_rows_expose_uncertain(client):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.models import Row
    t0 = datetime.now(ZoneInfo("Europe/Bucharest")).replace(hour=12, minute=0)
    rows = [Row("arrival", "IR", 1621, "Brasov", "CFR Calatori", "12:10", 5, 3,
                station_raw="BRASOY", operator_raw="CFR Calatori", uncertain=True),
            Row("arrival", "R", 3001, "Pitesti", "CFR Calatori", "12:20", 0, None),
            Row("departure", "IR", 1622, "Brasov", "CFR Calatori", "12:30", 0, 5),
            Row("departure", "R", 3002, "Pitesti", "CFR Calatori", "12:40", 0, 2)]
    client.app.state.store.ingest(rows, t0)
    b = client.get("/api/board").json()
    flags = {r["train_no"]: r["uncertain"] for r in b["arrivals"] + b["departures"]}
    assert flags == {1621: True, 3001: False, 1622: False, 3002: False}
    assert all("service_date" in r for r in b["arrivals"])


def test_panel_follow_button_uses_app_on_follow():
    panel = (WEB / "panel.js").read_text(encoding="utf-8")
    assert "pnl-follow" in panel and "TabelaApp.onFollow(found.t, fol)" in panel
    assert "followState" in panel and "tabela:follows" in panel
    assert "Favorite (local)" in panel
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'new CustomEvent("tabela:follows")' in app


# -- delay_read: never "la timp" without a delay actually read --------------------------

NODE = __import__("shutil").which("node")


@pytest.mark.skipif(NODE is None, reason="needs node")
def test_panel_level_never_green_without_read_delay():
    import subprocess
    harness = r"""
    global.window = global;
    global.document = { readyState: 'complete', addEventListener(){}, getElementById(){ return null; },
                        documentElement: { dataset: {} }, querySelectorAll(){ return []; } };
    require(process.argv[1]);
    const L = window.TabelaPanel.levelOf;
    const out = {
      unread0: L({ delay_min: 0, delay_read: false }),
      missing0: L({ delay_min: 0 }),
      read0: L({ delay_min: 0, delay_read: true }),
      read20: L({ delay_min: 20, delay_read: true }),
      unreadUncertain: L({ delay_min: 0, delay_read: false, uncertain: true }),
    };
    console.log(JSON.stringify(out));
    """
    r = subprocess.run([NODE, "-e", harness, str(WEB / "panel.js")], capture_output=True,
                       text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out == {"unread0": "unknown", "missing0": "unknown", "read0": "ok",
                   "read20": "mid", "unreadUncertain": "unknown"}


def test_cards_never_green_without_read_delay():
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert 'var read = t.delay_read === true;' in app
    assert 'var level = read ? delayLevel(d) : "unread";' in app
    panel = (WEB / "panel.js").read_text(encoding="utf-8")
    assert 'if (t.delay_read !== true) return "unknown";' in panel
    assert "necitit" in panel and "necitit" in app
    assert "confidence" not in panel  # dead check removed


def test_icon_weights_and_precache_budget(client):
    for name in ("icon-512.png", "icon-maskable-512.png", "logo.png", "og-image.png"):
        assert (WEB / "icons" / name).stat().st_size <= 90_000, name
    assert (WEB / "icons" / "logo-96.png").stat().st_size <= 10_000
    js = (WEB / "sw.js").read_text(encoding="utf-8")
    shell = re.search(r"var SHELL = \[(.*?)\];", js, re.S).group(1)
    assert "icon-512" not in shell and "icon-maskable" not in shell
    paths = re.findall(r'"(/[^"]*)"', shell) + ["/offline.html"]
    total = sum(len(client.get(p).content) for p in set(paths))
    # 400 KB until Beta 1.05 (~396 KB); +~14 KB of JS/CSS for the all-days Istoric
    # +~60 KB (uncompressed; ~15 KB gzip) for Statistici v2 (statistici.js/.css): the page
    # stays usable offline as a shell with an explicit „offline” message
    # +~25 KB (uncompressed; ~6 KB gzip) for „Probleme” on #statistici (Beta 1.19)
    assert total <= 500_000, total


def test_offline_page_uses_root_absolute_urls():
    off = (WEB / "offline.html").read_text(encoding="utf-8")
    for m in re.finditer(r'(?:src|href|srcset)="([^"]+)"', off):
        for url in m.group(1).split(","):
            u = url.strip().split()[0]
            assert u.startswith(("/", "https://")), u
