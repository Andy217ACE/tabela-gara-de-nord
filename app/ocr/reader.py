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

__all__ = ["OcrError", "TESSERACT_TIMEOUT", "read_board", "read_board_debug", "cell_grid",
           "COLUMNS"]

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
    return [cells for cells, _ in _cell_grid_geo(board_bgr)]


def _cell_grid_geo(board_bgr: np.ndarray) -> list[tuple[dict[str, np.ndarray], dict]]:
    """cell_grid plus each cell's box (x, y, w, h) in board pixels (not the x3 mask)."""
    mask, layout = preprocess.board_masks(board_bgr)
    s = preprocess.SCALE
    grid = []
    for band in preprocess.row_bands(layout):
        edges = _cell_edges(layout, band)
        strip = mask[band[0]:band[1]]
        y, hgt = band[0] // s, max(1, -(-(band[1] - band[0]) // s))
        grid.append((
            {name: strip[:, x0:x1] for name, x0, x1 in zip(_ORDER, edges[:-1], edges[1:])},
            {name: (x0 // s, y, max(1, (x1 - x0) // s), hgt)
             for name, x0, x1 in zip(_ORDER, edges[:-1], edges[1:])},
        ))
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


def _time_colon(s: str) -> str:
    """The board always prints H:MM / HH:MM; a 3-digit reading lost its colon."""
    return f"{s[0]}:{s[1:]}" if len(s) == 3 and s.isdigit() else s


def _numeric(name: str, cell: np.ndarray, tess: tuple[str, float | None],
             matcher: DigitMatcher | None) -> tuple[str, float | None]:
    """Pick the text of a numeric cell: glyph templates first, Tesseract as fallback.

    The returned confidence is Tesseract's when both readers agree; when the
    template reading overrides Tesseract it is the template's weakest glyph score.
    """
    t_text, t_conf = tess[0].replace(" ", ""), tess[1]
    if name == "time":
        t_text = _time_colon(t_text)
    if matcher is None:
        return t_text, t_conf
    m_text, m_score, trusted = matcher.read(cell, _ALLOWED[name])
    if not m_text:
        return "", None  # no ink in the cell: empty, whatever Tesseract hallucinated
    if name == "time":
        m_text = _time_colon(m_text)
        # thin colon dots can drop out of the glyph segmentation: a template
        # reading that is not a time never overrides a valid Tesseract time
        if parse_time(m_text) is None and parse_time(t_text) is not None:
            return t_text, t_conf
    if not trusted:
        return t_text, t_conf
    if m_text == t_text and t_conf is not None:
        return m_text, t_conf
    return m_text, m_score * 100


def read_board(image_bytes: bytes, engine: OcrEngine | None = None, *,
               stations: Iterable[str] = ()) -> list[Row]:
    """Rows of both boards. `engine` defaults to Tesseract; `stations` are the
    station names learned from the history (added to the curated seed)."""
    return read_board_debug(image_bytes, engine, stations=stations)[0]


def read_board_debug(image_bytes: bytes, engine: OcrEngine | None = None, *,
                     stations: Iterable[str] = ()) -> tuple[list[Row], list[dict]]:
    """(rows, debug): the rows of `read_board` plus one debug dict per detected line,
    including lines that gave no row (``row`` None: type or time unreadable).

    A debug dict holds ``board``, ``row_index`` (line within its board), ``row``,
    ``conf`` (0..1), ``raw_text`` (the cells as read, joined) and ``fields``:
    per column ``{raw, norm, conf (0-100 or None), bbox (x, y, w, h in image px)}``.
    Same OCR calls as before: debugging costs no accuracy and no extra time.
    """
    img = _decode(image_bytes)
    if engine is None:
        engine = TesseractEngine()

    slots: list[tuple[str, int, dict[str, np.ndarray], dict]] = []
    for board, (half, x_off) in zip(BOARDS, preprocess.split_boards_offsets(img)):
        for j, (cells, boxes) in enumerate(_cell_grid_geo(half)):
            slots.append((board, j, cells, {n: (x + x_off, y, w, h)
                                           for n, (x, y, w, h) in boxes.items()}))
    if not slots:
        return [], []

    reads = {name: _Composite([c[name] for _, _, c, _ in slots]).read(engine, *_TESS[name])
             for name in _ORDER}
    matcher = _get_matcher()
    seed = canonical.seed_stations()
    known_stations = set(stations) | seed

    rows: list[Row] = []
    debug: list[dict] = []
    for i, (board, j, cells, boxes) in enumerate(slots):
        cell = {name: reads[name][i] for name in _ORDER}
        for name in _ALLOWED:
            cell[name] = _numeric(name, cells[name], cell[name], matcher)
        type_text, flagged = strip_flag(cell["type"][0])
        train_type = normalize_type(type_text)
        sched = parse_time(cell["time"][0])
        confs = [c for _, c in cell.values() if c is not None]
        conf = sum(confs) / len(confs) / 100 if confs else 0.0
        station_raw = clean_station(cell["station"][0])
        operator_raw = canonical.clean_operator(cell["operator"][0])
        station, s_score = canonical.canonical_station(
            station_raw, known_stations, preferred=seed)
        operator, o_score = canonical.canonical_operator(operator_raw)
        delay = parse_delay(cell["delay"][0])  # None: unreadable cell (not "on time")
        norm = {"type": train_type, "no": _train_no(cell["no"][0]) or None,
                "station": station, "operator": operator, "time": sched,
                "delay": delay, "platform": parse_platform(cell["platform"][0])}
        entry = {
            "board": board, "row_index": j, "row": None,
            "conf": min(1.0, max(0.0, conf)),
            "raw_text": " ".join(t for t in (cell[n][0] for n in _ORDER) if t),
            "fields": {n: {"raw": cell[n][0], "norm": norm[n],
                           "conf": None if cell[n][1] is None
                           else round(min(100.0, max(0.0, cell[n][1])), 1),
                           "bbox": list(boxes[n])} for n in _ORDER},
            "station_score": s_score, "operator_score": o_score,
        }
        debug.append(entry)
        if train_type is None or sched is None:
            continue
        rows.append(Row(
            board=board,
            train_type=train_type,
            train_no=_train_no(cell["no"][0]),
            station=station,
            operator=operator,
            sched_time=sched,
            delay_min=delay if delay is not None else 0,
            delay_read=delay is not None,
            platform=parse_platform(cell["platform"][0]),
            flagged=flagged,
            confidence=min(1.0, max(0.0, conf)),
            operator_raw=operator_raw,
            station_raw=station_raw,
            # any corrected/unknown station (score < 1) or unmatched operator is uncertain
            uncertain=s_score < 1.0 or o_score < canonical.DEFAULT_THRESHOLD,
        ))
        entry["row"] = rows[-1]
    return rows, debug
