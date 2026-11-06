# © 2026 Andy217Ace
"""Reguli statice pentru coloana „Peron estimat": CSP, fără stiluri inline, SHELL din sw.js."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def test_peron_est_js_static_rules():
    js = (WEB / "peron_est.js").read_text(encoding="utf-8")
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", 'setAttribute("style"', "cssText"):
        assert bad not in js, bad
    assert "/api/predict/peron" in js and "textContent" in js and "try {" in js
    assert "nu informație oficială CFR" in js


def test_index_has_off_by_default_toggle_and_lazy_layer():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'id="pe-toggle"' in html and "Arată peron estimat" in html
    assert re.search(r'id="pe-toggle"[^>]*checked', html) is None  # implicit oprit
    assert "peron_est" not in html          # stratul e lazy, nu în pagină
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert "peron_est.js?v=" in app and "peron_est.css?v=" in app and "peronEstLoad" in app


def test_lazy_layer_not_in_sw_shell_and_version_bumped():
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    shell = re.search(r"var SHELL = \[(.*?)\];", sw, re.S).group(1)
    assert "peron_est" not in shell         # buget de precache (vezi test_brand_theme)
    assert int(re.search(r'var VERSION = "v(\d+)"', sw).group(1)) >= 39


def test_css_has_no_important_override_of_hidden_state():
    css = (WEB / "peron_est.css").read_text(encoding="utf-8")
    assert ".pe-cell[hidden]" in (WEB / "style.css").read_text(encoding="utf-8")
    assert "style=" not in css
