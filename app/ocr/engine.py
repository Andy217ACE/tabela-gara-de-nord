# © 2026 Andy217Ace
"""OCR engine interface.

The reader does all preprocessing (panel split, text mask, row bands, column
cells, one composite image per column) and all parsing; an engine only turns a
binary composite image into positioned text fragments. Swapping the engine never
touches preprocessing or parsing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pytesseract

from app.config import get_settings

TESSERACT_TIMEOUT = 10  # seconds per Tesseract call


class OcrError(Exception):
    """The OCR engine failed or timed out (the image itself was fine)."""


@dataclass(frozen=True)
class CellResult:
    """One recognised text fragment: text, confidence 0-100 (-1 unknown), bbox x, y, w, h."""

    text: str
    conf: float
    bbox: tuple[int, int, int, int]


class OcrEngine(Protocol):
    def read_cells(self, image: np.ndarray, whitelist: str | None, lang: str,
                   psm: int) -> list[CellResult]:
        """Recognise the text fragments of `image` (black text on white).

        `whitelist` restricts the characters (None: any), `lang` is a Tesseract-style
        language spec ("eng", "ron+eng"), `psm` the page segmentation mode. Fragment
        bboxes are in `image` pixels; the caller maps them back to cells. Raises
        OcrError on failure.
        """
        ...


class TesseractEngine:
    """Tesseract through pytesseract (the production engine)."""

    def __init__(self, cmd: str | None = None, timeout: float = TESSERACT_TIMEOUT):
        self.cmd = cmd if cmd is not None else get_settings().tesseract_cmd
        self.timeout = timeout

    def read_cells(self, image: np.ndarray, whitelist: str | None, lang: str,
                   psm: int) -> list[CellResult]:
        if self.cmd:
            pytesseract.pytesseract.tesseract_cmd = self.cmd
        config = f"--psm {psm}"
        if whitelist:
            config += f" -c tessedit_char_whitelist={whitelist}"
        try:
            data = pytesseract.image_to_data(
                image, lang=lang, config=config,
                output_type=pytesseract.Output.DICT, timeout=self.timeout)
        except (RuntimeError, pytesseract.TesseractError, OSError) as e:
            # pytesseract signals a timeout with RuntimeError; a missing binary
            # (TesseractNotFoundError) is an OSError.
            raise OcrError(f"tesseract failed: {e}") from e
        out: list[CellResult] = []
        for text, left, top, width, height, conf in zip(
                data["text"], data["left"], data["top"], data["width"],
                data["height"], data["conf"]):
            text = (text or "").strip()
            if text:
                out.append(CellResult(text, float(conf),
                                      (int(left), int(top), int(width), int(height))))
        return out
