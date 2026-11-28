# © 2026 Andy217Ace
"""i18n parity: ro.json/en.json and ro.admin.json/en.admin.json must have the same keys and the same
{placeholders}; the two dictionaries of a language never share a key."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "web" / "i18n"
PARAM = re.compile(r"\{(\w+)\}")


def _load(name):
    return json.loads((I18N / name).read_text(encoding="utf-8"))


import pytest


@pytest.mark.parametrize("suffix", ["", ".admin"])
def test_same_keys_and_params(suffix):
    ro, en = _load(f"ro{suffix}.json"), _load(f"en{suffix}.json")
    assert ro and en, "dictionaries must be non-empty (files actually read)"
    assert set(ro) == set(en), (
        f"only in ro: {sorted(set(ro) - set(en))}; only in en: {sorted(set(en) - set(ro))}")
    for key in ro:
        assert isinstance(ro[key], str) and ro[key].strip(), f"empty ro value: {key}"
        assert isinstance(en[key], str) and en[key].strip(), f"empty en value: {key}"
        assert set(PARAM.findall(ro[key])) == set(PARAM.findall(en[key])), f"param mismatch: {key}"


def test_admin_dict_disjoint_from_main():
    for lang in ("ro", "en"):
        both = set(_load(f"{lang}.json")) & set(_load(f"{lang}.admin.json"))
        assert not both, f"{lang}: keys in both dictionaries: {sorted(both)}"
