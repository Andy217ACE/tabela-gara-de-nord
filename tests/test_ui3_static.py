# © 2026 Andy217Ace
"""Beta 1.28 „UI v3": the interactive chart layer (web/charts3.js + charts3.css) is lazy-loaded, CSP-safe,
token-only, motion-safe and NOT in the service-worker precache; ui2.js gained the gauge, the empty state,
the View Transitions wrapper and the loader; the live Tabela files are untouched by this round."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PRECACHE_LIMIT = 650_000      # the budget set in Beta 1.26 (test_brand_theme); this round adds nothing to it


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


def test_charts3_js_is_csp_safe_and_complete():
    js = read("charts3.js")
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                'setAttribute("style"', "cssText", '"style"', "unsafe-inline"):
        assert bad not in js, bad
    # the only style writes are CSSOM properties (allowed by CSP): the tooltip position and two custom properties
    for m in re.finditer(r"\.style\.(\w+)", js):
        assert m.group(1) in ("transform", "setProperty"), m.group(0)
    for needle in ("App.charts3", "bind", "legend", "tools", "toc", "snapshot", "morph", "calendar", "smooth",
                   "showModal", "aria-live", "aria-pressed", "IntersectionObserver", "prefers-reduced-motion",
                   "pointerdown", "pointermove", "keydown", "Escape", "ArrowRight", "touch", "clipboard",
                   "aria-hidden", "createElementNS"):
        assert needle in js, needle


def test_charts3_css_tokens_only_motion_safe_and_no_endless_loops():
    css = read("charts3.css")
    assert css.startswith("/* © 2026 Andy217Ace */")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css.replace("url(#", "url("))   # theme tokens only (hex lives in style.css)
    assert "@import" not in css
    assert "prefers-reduced-motion" in css and "forced-colors" in css and "print" in css
    # no continuous animation anywhere in the visual layers (skeletons sweep three times, then stand still)
    for name in ("charts3.css", "ui2.css"):
        assert "infinite" not in read(name), name
    # only compositor-friendly properties are animated by the new motion
    for m in re.finditer(r"transition:\s*([^;]+);", css):
        assert not re.search(r"\b(width|height|left|top|margin|padding|box-shadow)\b", m.group(1)), m.group(0)


def test_lazy_not_in_precache_and_loader_matches_the_version():
    html = read("index.html")
    assert "charts3" not in html                                 # never a <script> / <link> in the page
    sw = read("sw.js")
    shell = re.search(r"var SHELL = \[(.*?)\];", sw, re.S).group(1)
    assert "charts3" not in shell
    assert int(re.search(r'var VERSION = "v(\d+)"', sw).group(1)) >= 28
    ui2 = read("ui2.js")
    assert "charts3.js?v=" in ui2 and "charts3.css?v=" in ui2
    ver = (ROOT / "VERSION").read_text(encoding="utf-8").strip().replace("Beta 1.", "1.")
    assert re.search(r'CHARTS_V = "%s"' % re.escape(ver), ui2), ver     # the cache-buster follows the release
    # only the pages with charts ask for it
    assert "charts: true" in read("stats.js") and ".charts()" not in read("history.js")
    sizes = sum((WEB / n.strip('"/')).stat().st_size for n in re.findall(r'"(/[^"]+)"', shell) if n != '"/"'
                and (WEB / n.strip('"/')).is_file())
    assert sizes <= PRECACHE_LIMIT, sizes


def test_ui2_js_new_helpers_stay_csp_safe():
    js = read("ui2.js")
    for bad in ("innerHTML", "eval(", "new Function", ".style.", 'setAttribute("style"', "cssText"):
        assert bad not in js, bad
    for needle in ("gauge", "empty", "startViewTransition", "charts3", "ui-seg-lab", "has-gauge"):
        assert needle in js, needle
    # the donut's pattern ids can no longer collide with its <desc> id (duplicate ids)
    assert 'id + "-pd"' in js and 'id + "-d"' in js


def test_statistici_and_stats_use_the_chart_layer_with_a_plain_fallback():
    js = read("statistici.js")
    for needle in ("C3()", "calendarSection", "refs:", "extFmt", "snapshot(", "morph(", "toc(", "enhance(", "grafic",
                   "data-key", "data-kind", "data-plot", "gauge: true", "chartUrl", "resetFilters"):
        assert needle in js, needle
    assert "App.charts3" in js and "if (c3" in js                 # every enhancement is optional
    st = read("stats.js")
    for needle in ("trendCell", "trendMax", "Ultimele 14 zile", "gauge: true", "enhance("):
        assert needle in st, needle


def test_route_change_runs_inside_a_view_transition_and_tabela_is_left_alone():
    app = read("app.js")
    assert "u.transition(route)" in app
    assert re.search(r'name\s*!==\s*"tabela"', app)               # the page-enter fallback never touches the board
    css = read("ui2.css")
    assert "view-transition" in css and "::view-transition-old(root)" in css
    # the live board's own files are not part of this round
    changed = subprocess.run(["git", "diff", "--name-only", "origin/main", "--", "web/panel.js", "web/panel.css",
                              "web/weather.js", "web/weather.css", "web/ocr.js", "web/ocr.css", "web/follows.js"],
                             cwd=ROOT, capture_output=True, text=True)
    if changed.returncode == 0:
        assert changed.stdout.strip() == "", changed.stdout


def test_no_third_party_library_added():
    """Own SVG + a ~35 KB lazy layer instead of a chart or tooltip library: a library would need CDN / inline
    styles / canvas (CSP, theming, per-mark accessibility). Nothing vendored, nothing from a CDN."""
    assert not (WEB / "vendor").exists()
    for name in ("index.html", "ui2.js", "charts3.js", "statistici.js", "stats.js"):
        assert not re.search(r"https?://(?!tabelacfr\.ddns\.net|cfr\.ro|www\.w3\.org)[a-z0-9.-]+/[^\"']*\.js", read(name)), name


def test_version_and_changelog_1_28():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert version >= "Beta 1.28" or re.fullmatch(r"Beta 1\.(\d+)", version) and int(version.split(".")[1]) >= 28
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (Beta 1\.\d+)", log, re.M).group(1)
    assert int(first.split(".")[1]) >= 28
    assert "## Beta 1.28" in log
    sec = log.split("## Beta 1.28", 1)[1].split("\n## ", 1)[0]
    for needle in ("tooltip", "calendar", "Ecran complet", "charts3", "ultimele 14 zile"):
        assert needle.lower() in sec.lower(), needle
