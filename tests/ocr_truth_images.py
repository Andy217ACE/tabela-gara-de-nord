# © 2026 Andy217Ace
"""Capturile reale folosite de teste (imagini JPG ale tabelei CFR).

Nicio captura reala nu e in git (repo public): ``tests/fixtures/**/*.jpg`` e ignorat si
fisierele stau doar pe masina locala. Cheile ``ocr_truth/<cale>`` din truth.json se citesc
din ``OCR_TRUTH_DIR`` (implicit ``tests/fixtures/ocr_truth/private/``) ca ``<cale>.jpg``;
celelalte (``ocr13/...``, ``glare/...``, ``board_1.jpg``) din ``tests/fixtures/``.
Daca imaginea lipseste (de ex. intr-o clona proaspata), testul care o foloseste sare cu
motiv, prin ``capture()`` sau ``read_frame()``.
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


def capture(path: Path) -> Path:
    """`path`, daca imaginea exista; altfel testul sare cu motiv."""
    if not path.is_file():
        hint = " (seteaza OCR_TRUTH_DIR)" if PRIVATE in path.parents else ""
        pytest.skip(f"captura reala lipsa: {path}{hint}; capturile nu sunt in repo")
    return path


def read_frame(frame: str) -> bytes:
    return capture(frame_path(frame)).read_bytes()
