# © 2026 Andy217Ace
"""Val 5: reguli statice pentru stratul lazy (CSP, header, dicționar, fără SHELL)."""
import json
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"


def test_val5_js_csp_safe_and_lazy():
    js = (WEB / "val5_seasons.js").read_text(encoding="utf-8")
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", 'setAttribute("style"', "cssText"):
        assert bad not in js, bad
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    assert "val5_seasons.js" not in sw.split("SHELL")[1].split("]")[0]


def test_val5_keys_in_both_dictionaries():
    ro = json.loads((WEB / "i18n" / "ro.json").read_text(encoding="utf-8"))
    en = json.loads((WEB / "i18n" / "en.json").read_text(encoding="utf-8"))
    js = (WEB / "val5_seasons.js").read_text(encoding="utf-8")
    import re
    for k in set(re.findall(r'"(val5\.[\w.]+)"', js)):
        assert k in ro and k in en, k
