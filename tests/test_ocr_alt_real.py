# © 2026 Andy217Ace
"""Alternativa OCR pe capturi reale (sar daca capturile lipsesc): zero interferenta.

Cititorul ruleaza cu bugetul larg (budget_s=60), ca test_ocr14: testele OCR sunt sensibile la
timp. Modelul e cel de sabloane din test_ocr_alt_reader (nu un model antrenat): proprietatea
verificata e a ALTERNATIVEI, nu a modelului: pe un cadru citit complet iesirea ramane identica,
iar pe unul cu linii necitite nicio celula citita de cititor nu se schimba."""
from __future__ import annotations

import copy

import pytest

from app.ocr import alt_reader as alt
from app.ocr.reader import read_board_debug
from tests.ocr_truth_images import read_frame
from tests.test_ocr_alt_reader import MODEL

UNREAD = "ocr13/2026_10_22_070049-e2db40a5"  # o linie necitita (numarul, plecari 2)
CLEAN = "ocr13/2026_10_21_143006-c3f9a8b7"   # citit complet


def _debug(frame):
    data = read_frame(frame)
    return data, read_board_debug(data, budget_s=60.0)[1]


def _cells_of(entries):
    return [(e["board"], e["row_index"], e["row"], e["state"],
             {n: (f["raw"], f["norm"]) for n, f in e["fields"].items()}) for e in entries]


def test_unread_line_never_alters_read_cells():
    data, es = _debug(UNREAD)
    before = copy.deepcopy(es)
    todo = alt.eligible(es)
    assert todo, "cadrul de test trebuie sa aiba o linie necitita eligibila"
    alt.recover(data, es, MODEL)
    for i, (a, b) in enumerate(zip(before, es)):
        if i in todo:
            for col in alt.ALT_COLS:  # o celula citita de cititor ramane a lui
                if a["fields"][col]["norm"] is not None:
                    assert b["fields"][col]["norm"] == a["fields"][col]["norm"]
        else:
            assert _cells_of([a]) == _cells_of([b])  # nicio alta linie nu se schimba


def test_fully_read_frame_is_identical_with_alt_on(monkeypatch):
    monkeypatch.setenv("OCR_ALT", "1")
    data, es = _debug(CLEAN)
    if alt.unread_lines(es):
        pytest.skip("cadrul are linii necitite pe aceasta masina")
    before = copy.deepcopy(es)
    info = alt.apply(data, es, MODEL)
    assert info["reason"] == "no_eligible_lines" and es == before
