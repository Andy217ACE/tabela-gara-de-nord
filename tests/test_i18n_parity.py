# © 2026 Andy217Ace
"""i18n parity: ro.json and en.json must have the same keys and the same {placeholders}."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "web" / "i18n"
PARAM = re.compile(r"\{(\w+)\}")


def _load(name):
    return json.loads((I18N / name).read_text(encoding="utf-8"))


def test_same_keys_and_params():
    ro, en = _load("ro.json"), _load("en.json")
    assert ro and en, "dictionaries must be non-empty (files actually read)"
    assert set(ro) == set(en), (
        f"only in ro: {sorted(set(ro) - set(en))}; only in en: {sorted(set(en) - set(ro))}")
    for key in ro:
        assert isinstance(ro[key], str) and ro[key].strip(), f"empty ro value: {key}"
        assert isinstance(en[key], str) and en[key].strip(), f"empty en value: {key}"
        assert set(PARAM.findall(ro[key])) == set(PARAM.findall(en[key])), f"param mismatch: {key}"
