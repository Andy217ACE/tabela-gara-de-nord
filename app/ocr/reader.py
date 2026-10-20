# © 2026 Andy217Ace
"""Board reader: per-column Tesseract OCR on the preprocessed text mask.

For speed, every cell of one column (both boards, all rows) is pasted into a
single composite image, one cell per line, and Tesseract runs once per column
with a column-specific whitelist. Words are mapped back to rows by their line slot.

Numeric columns (number, time, delay, platform) are additionally read by glyph
template matching (``digits.py``), which is preferred when its match is trusted:
Tesseract alone misreads isolated digits and the board's "1" on this font.

The OCR call itself goes through an ``OcrEngine`` (``engine.py``; Tesseract by
default). Operator and station names are then canonicalised against the known
names (``app.canonical``); the text as read is kept in ``*_raw``.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

import cv2
import numpy as np
import pytesseract  # noqa: F401  (kept importable: tests patch reader.pytesseract)

from app import canonical
from app.models import Row
from app.normalize import (
    clean_station,
    normalize_type,
    parse_delay,
    parse_platform,
    parse_time,
    strip_flag,
)
from app.ocr import preprocess
from app.ocr.digits import DigitMatcher
from app.ocr.engine import TESSERACT_TIMEOUT, OcrEngine, OcrError, TesseractEngine

__all__ = ["OcrError", "TESSERACT_TIMEOUT", "read_board", "cell_grid", "COLUMNS"]

log = logging.getLogger(__name__)

BOARDS = ("arrival", "departure")
MIN_WIDTH, MIN_HEIGHT = 200, 60  # smaller images cannot hold the board layout

# Column extents as fractions of the blue panel width (calibrated on board_1.jpg;
# both panels share the same layout).
COLUMNS: dict[str, tuple[float, float]] = {
    "type": (0.000, 0.090),
    "no": (0.090, 0.200),
    "station": (0.200, 0.510),
    "operator": (0.510, 0.755),
    "time": (0.755, 0.866),
    "delay": (0.866, 0.946),
    "platform": (0.946, 1.000),
}
_ORDER = ("type", "no", "station", "operator", "time", "delay", "platform")

# Each inner column boundary may move per row by this share of the panel width,
# snapping to the emptiest pixel column (text sometimes nearly touches the next column).
SNAP = 0.012

_DIGITS = "0123456789"
_PSM = 6  # one uniform block of text: the composite, one cell per line
# Per column: (character whitelist or None, language).
_TESS: dict[str, tuple[str | None, str]] = {
    "type": ("*IRNECMD", "eng"),
    "no": (_DIGITS, "eng"),
    "station": (None, "ron+eng"),
    "operator": (None, "ron+eng"),
    "time": (_DIGITS + ":", "eng"),
    "delay": (_DIGITS + "+", "eng"),
    "platform": (_DIGITS, "eng"),
}

_PAD = 12  # white margin (px, in the x3 mask) around the composite

# Numeric columns are also read by glyph template matching (fixed board font).
_ALLOWED = {"no": "0123456789", "time": "0123456789:",
            "delay": "0123456789+", "platform": "0123456789"}


def _decode(image_bytes: bytes) -> np.ndarray:
    buf = np.frombuffer(image_bytes or b"", np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR) if buf.size else None
    if img is None:
        raise ValueError("image could not be decoded")
    h, w = img.shape[:2]
    if w < MIN_WIDTH or h < MIN_HEIGHT:
        raise ValueError(f"imagine prea mică ({w}x{h}, minim {MIN_WIDTH}x{MIN_HEIGHT})")
    return img


def _cell_edges(mask: np.ndarray, band: tuple[int, int]) -> list[int]:
    """Pixel x edges of the columns for one row, snapped to gaps between glyphs."""
    w = mask.shape[1]
    ink = (mask[band[0]:band[1]] == 0).sum(axis=0)
    win = max(1, int(SNAP * w))
    edges = [0]
    for name in _ORDER[1:]:
        nominal = int(round(COLUMNS[name][0] * w))
        lo, hi = max(1, nominal - win), min(w - 1, nominal + win + 1)
        seg = ink[lo:hi]
        best = np.flatnonzero(seg == seg.min()) + lo
        edges.append(int(best[np.argmin(np.abs(best - nominal))]))
    edges.append(w)
    return edges


class _Composite:
    """Cells of one column stacked one per line, with a fixed line pitch."""

    def __init__(self, cells: list[np.ndarray]):
        self.n = len(cells)
        line_h = max(c.shape[0] for c in cells)
        self.pitch = int(line_h * 1.5)
        width = max(c.shape[1] for c in cells) + 2 * _PAD
        canvas = np.full((self.n * self.pitch + 2 * _PAD, width), 255, np.uint8)
        for i, c in enumerate(cells):
            y = _PAD + i * self.pitch + (self.pitch - c.shape[0]) // 2
            canvas[y:y + c.shape[0], _PAD:_PAD + c.shape[1]] = c
        self.image = canvas

    def read(self, engine: OcrEngine, whitelist: str | None,
             lang: str) -> list[tuple[str, float | None]]:
        """(text, mean confidence or None) per line slot, words in reading order."""
        words: list[list[tuple[int, str, float]]] = [[] for _ in range(self.n)]
        for res in engine.read_cells(self.image, whitelist, lang, _PSM):
            text = (res.text or "").strip()
            if not text:
                continue
            left, top, _, height = res.bbox
            slot = int((top + height / 2 - _PAD) // self.pitch)
            if 0 <= slot < self.n:
                words[slot].append((int(left), text, float(res.conf)))
        out: list[tuple[str, float | None]] = []
        for ws in words:
            ws.sort()
            confs = [c for _, _, c in ws if c >= 0]
            out.append((" ".join(t for _, t, _ in ws),
                        sum(confs) / len(confs) if confs else None))
        return out


def _train_no(s: str) -> int:
    digits = "".join(c for c in (s or "") if c in _DIGITS)
    return int(digits) if digits else 0


def cell_grid(board_bgr: np.ndarray) -> list[dict[str, np.ndarray]]:
    """Per detected row of one board: {column name: binary cell image (x3)}."""
    mask = preprocess.board_mask(board_bgr)
    grid = []
    for band in preprocess.row_bands(mask):
        edges = _cell_edges(mask, band)
        strip = mask[band[0]:band[1]]
        grid.append({name: strip[:, x0:x1]
                     for name, x0, x1 in zip(_ORDER, edges[:-1], edges[1:])})
    return grid


_matcher: DigitMatcher | None = None
_matcher_loaded = False


def _get_matcher() -> DigitMatcher | None:
    global _matcher, _matcher_loaded
    if not _matcher_loaded:
        _matcher_loaded = True
        try:
            _matcher = DigitMatcher.load()
        except (OSError, KeyError, ValueError) as e:
            _matcher = None
            log.warning(
                "digit templates unavailable (%s: %s); numeric fields fall back to "
                "Tesseract only and accuracy will drop", type(e).__name__, e)
    return _matcher


def _numeric(name: str, cell: np.ndarray, tess: tuple[str, float | None],
             matcher: DigitMatcher | None) -> tuple[str, float | None]:
    """Pick the text of a numeric cell: glyph templates first, Tesseract as fallback.

    The returned confidence is Tesseract's when both readers agree; when the
    template reading overrides Tesseract it is the template's weakest glyph score.
    """
    t_text, t_conf = tess[0].replace(" ", ""), tess[1]
    if matcher is None:
        return t_text, t_conf
    m_text, m_score, trusted = matcher.read(cell, _ALLOWED[name])
    if not m_text:
        return "", None  # no ink in the cell: empty, whatever Tesseract hallucinated
    if not trusted:
        return t_text, t_conf
    if m_text == t_text and t_conf is not None:
        return m_text, t_conf
    return m_text, m_score * 100


def read_board(image_bytes: bytes, engine: OcrEngine | None = None, *,
               stations: Iterable[str] = ()) -> list[Row]:
    """Rows of both boards. `engine` defaults to Tesseract; `stations` are the
    station names learned from the history (added to the curated seed)."""
    img = _decode(image_bytes)
    if engine is None:
        engine = TesseractEngine()

    slots: list[tuple[str, dict[str, np.ndarray]]] = [
        (board, cells)
        for board, half in zip(BOARDS, preprocess.split_boards(img))
        for cells in cell_grid(half)
    ]
    if not slots:
        return []

    reads = {name: _Composite([c[name] for _, c in slots]).read(engine, *_TESS[name])
             for name in _ORDER}
    matcher = _get_matcher()
    seed = canonical.seed_stations()
    known_stations = set(stations) | seed

    rows: list[Row] = []
    for i, (board, cells) in enumerate(slots):
        cell = {name: reads[name][i] for name in _ORDER}
        for name in _ALLOWED:
            cell[name] = _numeric(name, cells[name], cell[name], matcher)
        type_text, flagged = strip_flag(cell["type"][0])
        train_type = normalize_type(type_text)
        sched = parse_time(cell["time"][0])
        if train_type is None or sched is None:
            continue
        confs = [c for _, c in cell.values() if c is not None]
        conf = sum(confs) / len(confs) / 100 if confs else 0.0
        station_raw = clean_station(cell["station"][0])
        operator_raw = canonical.clean_operator(cell["operator"][0])
        station, s_score = canonical.canonical_station(
            station_raw, known_stations, preferred=seed)
        operator, o_score = canonical.canonical_operator(operator_raw)
        rows.append(Row(
            board=board,
            train_type=train_type,
            train_no=_train_no(cell["no"][0]),
            station=station,
            operator=operator,
            sched_time=sched,
            delay_min=parse_delay(cell["delay"][0]),
            platform=parse_platform(cell["platform"][0]),
            flagged=flagged,
            confidence=min(1.0, max(0.0, conf)),
            operator_raw=operator_raw,
            station_raw=station_raw,
            uncertain=min(s_score, o_score) < canonical.DEFAULT_THRESHOLD,
        ))
    return rows
