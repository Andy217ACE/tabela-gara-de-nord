# © 2026 Andy217Ace
"""Static checks: Statistici v3, sub-project 4 (export and performance): lazy layer outside the precache,
no new library, CSP-safe DOM, keys in both languages (one sorted contiguous block)."""
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
FILES = ("statistici.js", "stat_export.js")
PARAM = re.compile(r"\{(\w+)\}")


def _read(name):
    return (WEB / name).read_text(encoding="utf-8")


def _dict(lang):
    return json.loads((WEB / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))


def test_export_layer_is_lazy_and_not_precached():
    sw = _read("sw.js")
    html = _read("index.html")
    assert "stat_export" not in sw and "stat_export" not in html
    assert 'stat_export.js' in _read("statistici.js") and 'stat_export.css' in _read("statistici.js")


def test_no_new_library_or_external_loading():
    js = (_read("stat_export.js") + _read("stat_export.css")).replace("http://www.w3.org/2000/svg", "")   # the SVG namespace is not a request
    for bad in ("jspdf", "html2canvas", "canvg", "import(", "http://", "https://", "@import", "XMLHttpRequest"):
        assert bad not in js, bad
    assert not re.search(r"\bfetch\(", js)   # the export reads the page, never the network
    assert not any(p.name.startswith(("jspdf", "html2canvas", "canvg")) for p in WEB.glob("*.js"))


def test_no_unsafe_dom():
    for name in FILES:
        js = _read(name)
        assert ".innerHTML" not in js and "insertAdjacentHTML" not in js and "document.write" not in js, name
        assert "eval(" not in js and "new Function" not in js, name


def test_csv_rules_in_code():
    js = _read("stat_export.js")
    assert '"\\uFEFF"' in js and '","' in js and "\\r\\n" in js   # BOM, comma separator, CRLF
    assert "text/csv;charset=utf-8" in js


def test_png_from_serialized_svg_on_canvas():
    js = _read("stat_export.js")
    assert "XMLSerializer" in js and "toBlob" in js and "getContext(\"2d\")" in js


def test_sp4_keys_in_both_languages_and_contiguous():
    ro, en = _dict("ro"), _dict("en")
    mine = [k for k in ro if k.startswith("stats.sp4.")]
    assert mine, "sub-project 4 keys missing"
    assert set(mine) == {k for k in en if k.startswith("stats.sp4.")}
    for k in mine:
        assert set(PARAM.findall(ro[k])) == set(PARAM.findall(en[k])), k
    keys = list(ro)
    idx = [keys.index(k) for k in mine]
    assert idx == list(range(idx[0], idx[0] + len(idx))), "keys are not one contiguous block"
    assert mine == sorted(mine), "block is not sorted"


def test_used_keys_exist():
    ro, en = _dict("ro"), _dict("en")
    js = "".join(_read(n) for n in FILES)
    used = set(re.findall(r'"(stats\.sp4\.[\w.]*\w)"', js))
    assert used, "no sp4 key used"
    assert used <= set(ro) and used <= set(en), sorted(used - set(ro))
