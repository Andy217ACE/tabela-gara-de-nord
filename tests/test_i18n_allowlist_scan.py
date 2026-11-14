# © 2026 Andy217Ace
"""Scan web/ JS and HTML for Romanian literals that are not in tests/i18n_allowlist.txt."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
ALLOWLIST = Path(__file__).resolve().parent / "i18n_allowlist.txt"
PATTERN = re.compile("[ăîâșțĂÎÂȘȚşţŞŢ]|Încarc|Trenuri|Plecări|Sosiri")


def _allowed():
    allowed = set()
    for raw in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        path, lineno, _reason = line.split(":", 2)
        allowed.add((path, int(lineno)))
    return allowed


@pytest.mark.xfail(strict=False, reason="until Task 8: Romanian literals removed from web/ files in tasks 5-8")
def test_no_romanian_literals_outside_allowlist():
    allowed = _allowed()
    hits = []
    files = sorted(list(WEB.rglob("*.js")) + list(WEB.rglob("*.html")))
    assert files, "no web files scanned"
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        for n, text in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if PATTERN.search(text) and (rel, n) not in allowed:
                hits.append(f"{rel}:{n}: {text.strip()[:100]}")
    assert not hits, f"{len(hits)} Romanian literal lines:\n" + "\n".join(hits[:50])
