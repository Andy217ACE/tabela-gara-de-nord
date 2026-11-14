# © 2026 Andy217Ace
"""Statistici v3 sub-project 1: new dictionary keys exist in both languages and the front-end
code stays CSP-safe (no innerHTML, no inline style)."""
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
PARAM = re.compile(r"\{(\w+)\}")
PREFIXES = ("stats.sum.", "stats.reset", "stats.preset.", "stats.mobile.")


def _dict(lang):
    return json.loads((WEB / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))


def test_new_keys_in_both_languages_and_contiguous():
    ro, en = _dict("ro"), _dict("en")
    mine = [k for k in ro if k.startswith(PREFIXES)]
    assert mine, "sub-project 1 keys missing"
    assert set(mine) == {k for k in en if k.startswith(PREFIXES)}
    for k in mine:
        assert set(PARAM.findall(ro[k])) == set(PARAM.findall(en[k])), k
    keys = list(ro)
    idx = [keys.index(k) for k in mine]
    assert idx == list(range(idx[0], idx[0] + len(idx))), "keys are not one contiguous block"
    assert mine == sorted(mine), "block is not sorted"


def test_used_keys_exist():
    js = (WEB / "statistici.js").read_text(encoding="utf-8")
    ro = _dict("ro")
    used = set(re.findall(r'"(stats\.(?:sum|reset|preset|mobile)[\w.]*)"', js))
    assert used, "no sub-project 1 keys used"
    assert used <= set(ro), sorted(used - set(ro))


def test_no_unsafe_dom_in_statistici_js():
    js = (WEB / "statistici.js").read_text(encoding="utf-8")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "window.prompt", "prompt("):
        assert bad not in js, bad
