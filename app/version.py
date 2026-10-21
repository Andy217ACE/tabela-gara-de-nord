# © 2026 Andy217Ace
"""Application version (file `VERSION`) and the Romanian changelog (`CHANGELOG.md`).

Scheme: "Beta 1.NN" — NN grows by one at every deploy (see README, „Deploy”).
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"
VERSION_RE = re.compile(r"^Beta 1\.\d{2}$")

_HEAD = re.compile(r"^## (?P<version>.+?)\s+[—-]\s+(?P<date>\d{4}-\d{2}-\d{2})\s*$")


def _read_version() -> str:
    try:
        v = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "necunoscută"
    return v or "necunoscută"


__version__ = _read_version()


@lru_cache(maxsize=1)
def changelog() -> list[dict]:
    """CHANGELOG.md as [{version, date, groups: [{title, items: [str]}]}], newest first.

    Only `## <versiune> — <data>`, `### <grup>` and `- <punct>` lines are kept; the
    text is returned verbatim (the client renders it with textContent)."""
    try:
        text = CHANGELOG_FILE.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict] = []
    for line in text.splitlines():
        m = _HEAD.match(line)
        if m:
            out.append({"version": m["version"], "date": m["date"], "groups": []})
            continue
        if not out:
            continue
        if line.startswith("### "):
            out[-1]["groups"].append({"title": line[4:].strip(), "items": []})
        elif line.startswith("- "):
            if not out[-1]["groups"]:
                out[-1]["groups"].append({"title": "", "items": []})
            out[-1]["groups"][-1]["items"].append(line[2:].strip())
    return out
