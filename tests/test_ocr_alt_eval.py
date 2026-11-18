# © 2026 Andy217Ace
"""Utilitarele scriptului scripts/ocr_alt_eval.py (fara Tesseract)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "ocr_alt_eval", Path(__file__).resolve().parents[1] / "scripts" / "ocr_alt_eval.py")
ev = importlib.util.module_from_spec(_spec)
sys.modules["ocr_alt_eval"] = ev
_spec.loader.exec_module(ev)


def test_verdict_separates_ok_wrong_and_unverifiable():
    lab = {"no": 3021, "time": "05:28", "platform": "?"}
    assert ev._verdict(lab, "no", "3021") == "ok"      # numarul din alt_reader e text
    assert ev._verdict(lab, "no", 3022) == "wrong"
    assert ev._verdict(lab, "time", "05:28") == "ok"
    assert ev._verdict(lab, "platform", 4) == "skip"   # "?" nu se poate verifica
    assert ev._verdict(None, "no", "1") == "skip"


def test_p95_and_label_lookup():
    assert ev.p95([]) == 0.0
    assert ev.p95([1.0, 2.0, 3.0, 4.0, 100.0]) == 100.0
    tf = {"f": {"arrival": [{"no": 1}]}}
    assert ev._label(tf, "f", "arrival", 0) == {"no": 1}
    assert ev._label(tf, "f", "arrival", 5) is None and ev._label(tf, "x", "arrival", 0) is None


def test_criteria_match_the_spec():
    assert ev.CRITERIA == {"recuperate_min": 0.60, "gresite_max": 0.005,
                           "valori_min": 300, "buget_s": 4.0}
