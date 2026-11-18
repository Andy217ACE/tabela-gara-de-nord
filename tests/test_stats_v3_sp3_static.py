# © 2026 Andy217Ace
"""Statistici v3 sp3: static checks — dictionary keys used by stat_sp3.js exist in both languages with
the same parameters, the layer is lazy (not in the service-worker shell), CSP-safe code, no library."""
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
PARAM = re.compile(r"\{(\w+)\}")


def _dict(lang):
    return json.loads((WEB / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))


def _js():
    return (WEB / "stat_sp3.js").read_text(encoding="utf-8")


def test_keys_exist_in_both_languages_with_the_same_params():
    ro, en = _dict("ro"), _dict("en")
    keys = {k for k in ro if k.startswith("stats.sp3.")}
    assert keys == {k for k in en if k.startswith("stats.sp3.")}
    for k in keys:
        assert set(PARAM.findall(ro[k])) == set(PARAM.findall(en[k])), k


def test_every_literal_key_in_the_layer_is_defined():
    ro = _dict("ro")
    used = set(re.findall(r'"(stats\.[a-z0-9_.]+?)"', _js()))
    # keys built from a prefix + variable (kind, board, weekday, compare row)
    for pre, parts in (("stats.sp3.kind.", ("route", "operator")), ("stats.sp3.compare.", ("on_time", "mean", "trains", "journeys")),
                       ("stats.board.", ("arrival", "departure")), ("stats.wd.", range(7)), ("stats.wds.", range(7))):
        used |= {f"{pre}{x}" for x in parts}
    missing = sorted(k for k in used if k not in ro and not k.endswith("."))
    assert missing == []
    # the server's message key
    assert "stats.sp3.insufficient" in ro and "stats.sp3.reliable.empty" in ro


def test_layer_is_lazy_and_csp_safe():
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    assert "stat_sp3" not in sw, "the layer loads at runtime, never in the precache shell"
    js = _js()
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js and "eval(" not in js
    assert 'setAttribute("style"' not in js
    css = (WEB / "stat_sp3.css").read_text(encoding="utf-8")
    assert "@import" not in css and "url(http" not in css
    # statistici.js loads the layer and mounts it, nothing else of sp3
    main = (WEB / "statistici.js").read_text(encoding="utf-8")
    assert 'layer("statSp3", "stat_sp3")' in main and "App.statSp3.enhance" in main
    assert re.findall(r"https?://[^\"]+", js) == ["http://www.w3.org/2000/svg"]   # only the SVG namespace: no CDN, no library


def test_threshold_is_a_code_constant_not_an_interface_setting():
    from app import stats_changes
    assert stats_changes.ALERT_MEDIAN_MIN == 15 and stats_changes.RELIABLE_MIN_JOURNEYS == 10
    assert "localStorage" not in _js()   # nothing configurable on the page
