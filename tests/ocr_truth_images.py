# © 2026 Andy217Ace
"""Imaginile setului de adevar OCR (truth.json).

Capturile reale din ``tests/fixtures/ocr_truth/`` nu sunt in git (repo public). Cheile
``ocr_truth/<cale>`` din truth.json se citesc din ``OCR_TRUTH_DIR`` (implicit
``tests/fixtures/ocr_truth/private/``, ignorat de git) ca ``<cale>.jpg``. Daca fisierul
lipseste, testul care il foloseste sare cu motiv. Celelalte chei (``ocr13/...``,
``glare/...``) raman in ``tests/fixtures/`` si se citesc ca inainte.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"
TRUTH_PREFIX = "ocr_truth/"
PRIVATE = Path(os.environ.get("OCR_TRUTH_DIR") or FIX / "ocr_truth" / "private")


def frame_path(frame: str) -> Path:
    if frame.startswith(TRUTH_PREFIX):
        return PRIVATE / (frame[len(TRUTH_PREFIX):] + ".jpg")
    return FIX / f"{frame}.jpg"


def read_frame(frame: str) -> bytes:
    path = frame_path(frame)
    if frame.startswith(TRUTH_PREFIX) and not path.is_file():
        pytest.skip(f"captura privata lipsa: {path} (seteaza OCR_TRUTH_DIR)")
    return path.read_bytes()
