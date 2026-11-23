# © 2026 Andy217Ace
"""requirements.lock pins every package of requirements.txt at the same version."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pins(path):
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==(\S+)", line)
        if m:
            out[re.sub(r"[-_.]+", "-", m.group(1)).lower()] = m.group(2)
    return out


def test_lock_pins_match_requirements():
    req, lock = _pins(ROOT / "requirements.txt"), _pins(ROOT / "requirements.lock")
    assert req
    assert {k: lock.get(k) for k in req} == req
