# © 2026 Andy217Ace
"""Beta 1.55: the admin/OCR/system/settings pages are not precached; the service worker caches them at runtime."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
LAZY = ("admin.js", "ocr.js", "sistem.js", "setari.js", "sezoane.js", "versions.js", "cum.js", "cum.css")


def _sw():
    return (WEB / "sw.js").read_text(encoding="utf-8")


def test_lazy_pages_not_in_shell():
    shell = re.search(r"var SHELL = \[(.*?)\];", _sw(), re.S).group(1)
    for name in LAZY:
        assert name not in shell, name
    assert "/i18n/ro.json" in shell and "en.json" not in shell


def test_runtime_path_for_same_origin_get():
    sw = _sw()
    assert "function runtimeNetworkFirst" in sw
    handler = sw[sw.index('addEventListener("fetch"'):]
    assert "runtimeNetworkFirst(event)" in handler
    # the generic path caches the response (put) and falls back to the cache offline
    body = sw[sw.index("function runtimeNetworkFirst"):]
    body = body[:body.index("\n}\n")]
    assert "c.put(" in body and "c.match(" in body
