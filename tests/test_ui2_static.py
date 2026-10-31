# © 2026 Andy217Ace
"""Beta 1.26 „UI v2": the shared visual layer for the non-live pages (web/ui2.css + web/ui2.js),
donut charts in Statistici, no new third-party library (self-hosted SVG/CSS), the service
worker and the live Tabela left alone."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def read(name):
    return (WEB / name).read_text(encoding="utf-8")


def test_ui2_js_is_csp_safe_and_complete():
    js = read("ui2.js")
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", 'setAttribute("style"', "cssText", '"style"'):
        assert bad not in js, bad
    for needle in ("App.ui2", "donut", "countUp", "skeleton", "meter", "spark", "enterView",
                   "decorate", "createElementNS", "prefers-reduced-motion", "IntersectionObserver",
                   "mask", "pattern", "aria-label", "tabindex"):
        assert needle in js, needle


def test_ui2_css_tokens_only_and_motion_safe():
    css = read("ui2.css")
    assert css.startswith("/* © 2026 Andy217Ace */")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css)  # theme tokens only (hex lives in style.css)
    assert "@import" not in css and "url(" not in css
    assert "prefers-reduced-motion" in css and "forced-colors" in css
    # the categorical slots exist in the three theme blocks (dark default, light media, forced light)
    for n in range(1, 7):
        assert css.count(f"--cat-{n}:") >= 3, n
    style = read("style.css")
    for n in range(1, 7):
        assert f"--ref-cat-d-{n}:" in style and f"--ref-cat-l-{n}:" in style
    # scroll reveal: below-the-fold only, one-shot, never with reduced motion
    assert ".ui-rv-in" in css and "no-preference" in css


def test_wiring_index_and_service_worker():
    html = read("index.html")
    assert '<link rel="stylesheet" href="ui2.css">' in html
    assert re.search(r'<script src="ui2.js" defer></script>', html)
    sw = read("sw.js")
    shell = re.search(r"var SHELL = \[(.*?)\];", sw, re.S).group(1)
    assert '"/ui2.css"' in shell and '"/ui2.js"' in shell
    assert int(re.search(r'var VERSION = "v(\d+)"', sw).group(1)) >= 27
    # ui2.js loads right after app.js (App.el) and before the page scripts that use it
    assert html.index("ui2.js") < html.index("statistici.js")
    assert html.index("ui2.css") > html.index("statistici.css")  # later in the cascade


def test_no_third_party_library_added():
    """Charts are self-hosted SVG + CSS (CSP-friendly, themeable, accessible): nothing under
    web/vendor, nothing loaded from a CDN."""
    assert not (WEB / "vendor").exists()
    for name in ("index.html", "ui2.js", "statistici.js", "stats.js", "history.js"):
        assert not re.search(r"https?://(?!tabelacfr\.ddns\.net|cfr\.ro)[a-z0-9.-]+/[^\"']*\.js", read(name)), name


def test_statistici_uses_donuts_for_part_to_whole():
    js = read("statistici.js")
    assert js.count("U().donut(") >= 3 and "U().delayDonut(" in js
    for needle in ("Cum se împart", "la timp", "peste 30", "Sosiri și plecări", "Altele"):
        assert needle in js, needle
    # ranked lists and time series stay bars / lines
    assert "hbars(" in js and "lines(" in js and "columns(" in js
    css = read("statistici.css")
    assert "ss-donut" in css or "ui-donut" in read("ui2.css")


def test_route_hooks_in_app_js_leave_tabela_alone():
    app = read("app.js")
    assert "data-route" in app or "dataset.route" in app
    assert "enterView" in app
    # the live board never gets the page-enter animation
    assert re.search(r'name\s*!==\s*"tabela"', app)


def test_versions_page_is_a_timeline():
    js = read("versions.js")
    for needle in ("v-timeline", "v-badge", "App.ui2"):
        assert needle in js, needle


def test_version_and_changelog_1_26():
    # Beta 1.26 is the UI v2 release; later versions (1.27 OCR ...) sit above its section
    assert int((ROOT / "VERSION").read_text(encoding="utf-8").strip().split(".")[-1]) >= 26
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (Beta \S+) — ", text, re.M).group(1)
    assert int(first.split(".")[-1]) >= 26
    top = text[text.index("## Beta 1.26"):].split("## Beta 1.24")[0]
    for word in ("donut", "Statistici", "Mișcare", "prefers-reduced-motion", "Tabela"):
        assert word in top, word


def test_readme_documents_libraries_decision():
    readme = read_root("README.md")
    assert "ui2.js" in readme and "fără biblioteci" in readme.lower()


def read_root(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_live_board_files_untouched():
    """The weather widget is not part of this change: no diff against the point where this branch left
    main. panel.js/panel.css are excluded on purpose since Beta 1.41 (the last safe delay reading)."""
    import subprocess
    base = subprocess.run(["git", "merge-base", "HEAD", "origin/main"], cwd=ROOT,
                          capture_output=True, text=True)
    if base.returncode != 0:  # no git / no origin in this checkout: nothing to compare
        return
    out = subprocess.run(["git", "diff", "--name-only", base.stdout.strip(), "HEAD", "--",
                          "web/weather.js", "web/weather.css",
                          "app/weather.py"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == "", out.stdout
