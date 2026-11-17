# © 2026 Andy217Ace
"""Statistici v3 sub-project 2 (claritate vizuală): static checks — one color scale (one
definition, thresholds in one place), dictionary keys in both languages, CSP-safe code."""
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
PARAM = re.compile(r"\{(\w+)\}")
FILES = ("statistici.js", "stat_sp2.js", "theme-init.js")


def _dict(lang):
    return json.loads((WEB / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))


def _read(name):
    p = WEB / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_color_scale_has_one_definition():
    css = _read("statistici.css")
    # the three tokens are defined once on :root (the high-contrast block only overrides them)
    for tok in ("--ss-good", "--ss-mid", "--ss-bad"):
        base = re.findall(r"^\s*" + tok + r":", css, re.M)
        assert 1 <= len(base) <= 2, (tok, "one base definition (+ at most the high-contrast override)")
    assert len(re.findall(r"^\s*:root\s*\{[^}]*--ss-good", css, re.M)) == 1
    # thresholds: one constant, in statistici.js only
    owners = [n for n in sorted(p.name for p in WEB.glob("*.js")) if re.search(r"\bvar SCALE\s*=", _read(n))]
    assert owners == ["statistici.js"], owners
    js = _read("statistici.js")
    assert len(re.findall(r"\bvar SCALE\s*=", js)) == 1
    assert len(re.findall(r"\bfunction tone\(", js)) == 1


def test_heat_cells_use_the_scale_not_the_sequential_hue():
    css = _read("statistici.css")
    for sel in (r"\.ss-key\.ss-q[0-4]", r"\.ss-cell\.ss-q[0-4]"):
        for m in re.finditer(sel + r"\s*\{([^}]*)\}", css):
            assert "--c-seq" not in m.group(1), m.group(0)
            assert "--ss-" in m.group(1), m.group(0)


def test_tone_classes_follow_the_tokens():
    css = _read("statistici.css")
    for k in ("good", "mid", "bad"):
        assert re.search(r"\.ss-t-" + k + r"[^{]*\{[^}]*var\(--ss-" + k + r"\)", css), k


def test_new_keys_in_both_languages_and_contiguous():
    ro, en = _dict("ro"), _dict("en")
    mine = [k for k in ro if k.startswith("stats.sp2.")]
    assert mine, "sub-project 2 keys missing"
    assert set(mine) == {k for k in en if k.startswith("stats.sp2.")}
    for k in mine:
        assert set(PARAM.findall(ro[k])) == set(PARAM.findall(en[k])), k
    keys = list(ro)
    idx = [keys.index(k) for k in mine]
    assert idx == list(range(idx[0], idx[0] + len(idx))), "keys are not one contiguous block"
    assert mine == sorted(mine), "block is not sorted"


def test_used_keys_exist():
    ro, en = _dict("ro"), _dict("en")
    js = "".join(_read(n) for n in FILES)
    used = set(re.findall(r'"(stats\.(?:sp2|gl)\.[\w.]*\w)"', js))
    assert any(k.startswith("stats.sp2.") for k in used)
    assert used <= set(ro) and used <= set(en), sorted(used - set(ro))


def test_no_unsafe_dom():
    for name in FILES:
        js = _read(name)
        assert ".innerHTML" not in js and "insertAdjacentHTML" not in js and "document.write" not in js, name
        assert 'setAttribute("style"' not in js and ".style.cssText" not in js, name
