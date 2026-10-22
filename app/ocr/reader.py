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

import dataclasses
import logging
import os
import time
from collections.abc import Iterable

import cv2
import numpy as np
import pytesseract  # noqa: F401  (kept importable: tests patch reader.pytesseract)

from app import canonical
from app.models import Row
from app.normalize import (
    clean_station,
    resolve_type,
    parse_delay,
    parse_platform,
    parse_time,
    strip_flag,
)
from app.ocr import digits, preprocess, stats
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

    def __init__(self, cells: list[np.ndarray], upscale: float = 1.0):
        if upscale != 1.0:  # bigger glyphs for Tesseract (the "x4" re-read)
            cells = [np.where(cv2.resize(c, None, fx=upscale, fy=upscale,
                                         interpolation=cv2.INTER_LINEAR) < 128, 0, 255
                              ).astype(np.uint8) if c.size else c for c in cells]
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


class _Panel:
    """One board (blue panel): masks, the text-line bands (checked against the 4x3
    structure, see ``preprocess.structured_bands``) and the column edges per line."""

    def __init__(self, board_bgr: np.ndarray):
        self.img = board_bgr
        self.mask, self.layout, self.rows, self.level = preprocess.board_masks_ctx(board_bgr)
        self.bands, self.repaired = preprocess.structured_bands(self.layout, self.rows)
        self.edges = [_cell_edges(self.layout, b) for b in self.bands]
        self._variants: dict[str, np.ndarray] = {}

    def __len__(self) -> int:
        return len(self.bands)

    def variant(self, name: str) -> np.ndarray:
        if name not in ("vline", "lvl-", "lvl+", "adapt"):
            return self.mask  # x4/wide change the scale or crop, not the binarisation
        if name not in self._variants:
            self._variants[name] = preprocess.variant_mask(self.img, self.rows, self.level, name)
        return self._variants[name]

    def cells(self, i: int, mask: np.ndarray | None = None, pad_y: int = 0
              ) -> dict[str, np.ndarray]:
        mask = self.mask if mask is None else mask
        y0, y1 = self.bands[i]
        strip = mask[max(0, y0 - pad_y):min(mask.shape[0], y1 + pad_y)]
        e = self.edges[i]
        return {name: strip[:, x0:x1] for name, x0, x1 in zip(_ORDER, e[:-1], e[1:])}

    def boxes(self, i: int) -> dict[str, tuple[int, int, int, int]]:
        s = preprocess.SCALE
        y0, y1 = self.bands[i]
        y, hgt = y0 // s, max(1, -(-(y1 - y0) // s))
        e = self.edges[i]
        return {name: (x0 // s, y, max(1, (x1 - x0) // s), hgt)
                for name, x0, x1 in zip(_ORDER, e[:-1], e[1:])}

    def has_ink(self, i: int) -> bool:
        return preprocess.band_has_ink(self.mask, self.bands[i])


def cell_grid(board_bgr: np.ndarray) -> list[dict[str, np.ndarray]]:
    """Per detected row of one board: {column name: binary cell image (x3)}."""
    return [cells for cells, _ in _cell_grid_geo(board_bgr)]


def _cell_grid_geo(board_bgr: np.ndarray) -> list[tuple[dict[str, np.ndarray], dict]]:
    """cell_grid plus each cell's box (x, y, w, h) in board pixels (not the x3 mask)."""
    p = _Panel(board_bgr)
    return [(p.cells(i), p.boxes(i)) for i in range(len(p))]


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
    try:
        m_text, m_score, trusted = matcher.read(cell, _ALLOWED[name])
    except ValueError:  # a degenerate cell must not fail the whole frame
        log.warning("glyph templates failed on a %s cell %s; Tesseract reading kept",
                    name, getattr(cell, "shape", None), exc_info=True)
        return t_text, t_conf
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


DELAY_UNREAD = "+?"  # a delay cell with text that cannot be read safely (parse: None)
DELAY_MAX_DIGITS = 3  # "+N" with 1..3 digits; anything longer is not a delay
# a delay digit cut out of a blob fused with its neighbours is trusted only on a clear
# match (glare: "+45" gave "1" at 0.78 / margin 0.041 under the adaptive threshold)
FUSED_MIN_SCORE = 0.80
FUSED_MIN_MARGIN = 0.10


def _delay(cell: np.ndarray, tess: tuple[str, float | None], matcher: DigitMatcher | None
           ) -> tuple[str, float | None, str | None]:
    """(text, confidence 0-100, reason the cell is unread or None) of a delay cell.

    The board prints a delay as "+" and 1-3 digits. Measured misreads (audit Beta 1.13):
    a glare blob over the first digit fuses "+" with it, Tesseract then reads one digit
    too many ("+65" -> "+465", "+20" -> "+240") or flips the blurred digit (60/80, 5/35/95)
    while the glyph templates find the right number of glyphs but cannot trust them.
    So: the first glyph must be a "+" (template and cross shape); the digit count comes
    from the glyph segmentation; a digit the templates do not trust is accepted only if
    Tesseract reads the same digit at the same place, and never when it was cut out of
    a blob fused with its neighbours (glare: both readers guess the hidden part, 6 -> 8
    in agreement); three digits (>= 100 min) need
    every glyph trusted AND both readers agreeing. Otherwise the cell is unread
    (DELAY_UNREAD -> parse_delay None): a missing delay, never 0 and never a guess.
    """
    t_text, t_conf = tess[0].replace(" ", ""), tess[1]
    if matcher is None:
        return t_text, t_conf, None
    try:
        gl = matcher.glyphs(cell, _ALLOWED["delay"])
    except ValueError:
        log.warning("glyph templates failed on a delay cell %s; Tesseract reading kept",
                    getattr(cell, "shape", None), exc_info=True)
        return t_text, t_conf, None
    if not gl:
        return "", None, None  # no ink: the board's "on time"
    ch0, s0, m0, g0, _ = gl[0]
    if ch0 != "+" or not (digits.glyph_trusted(s0, m0) or digits.is_plus(g0)):
        return DELAY_UNREAD, None, "no_plus"
    if any(ch == "+" for ch, *_ in gl[1:]):
        return DELAY_UNREAD, None, "plus_twice"
    digs = gl[1:]
    n = len(digs)
    if not 1 <= n <= DELAY_MAX_DIGITS:
        return DELAY_UNREAD, None, "digits"
    m_digits = "".join(ch for ch, *_ in digs)
    # a digit cut out of a fused blob (glare) needs a clear match, not a near tie
    trusted = [digits.glyph_trusted(s, m) and (not fused or (s >= FUSED_MIN_SCORE
                                                             and m >= FUSED_MIN_MARGIN))
               for _, s, m, _, fused in digs]
    t_digits = t_text[1:] if t_text.startswith("+") else t_text
    t_ok = t_digits.isdigit() and len(t_digits) == n
    worst = min(s for _, s, *_ in gl) * 100
    if n == DELAY_MAX_DIGITS and not (all(trusted) and t_ok and t_digits == m_digits):
        return DELAY_UNREAD, None, "three_digits"
    if all(trusted):
        return "+" + m_digits, (t_conf if t_ok and t_digits == m_digits and t_conf is not None
                                else worst), None
    if any(not ok and fused for ok, (*_, fused) in zip(trusted, digs)):
        return DELAY_UNREAD, None, "glare"
    if not t_ok:
        return DELAY_UNREAD, None, "count"
    if any(not ok and t_digits[i] != m_digits[i] for i, ok in enumerate(trusted)):
        return DELAY_UNREAD, None, "disagree"
    return "+" + m_digits, t_conf if t_conf is not None else worst, None


def read_board(image_bytes: bytes, engine: OcrEngine | None = None, *,
               stations: Iterable[str] = ()) -> list[Row]:
    """Rows of both boards. `engine` defaults to Tesseract; `stations` are the
    station names learned from the history (added to the curated seed)."""
    return read_board_debug(image_bytes, engine, stations=stations)[0]


def read_board_debug(image_bytes: bytes, engine: OcrEngine | None = None, *,
                     stations: Iterable[str] = (),
                     budget_s: float | None = None) -> tuple[list[Row], list[dict]]:
    """(rows, debug): the rows of `read_board` plus one debug dict per detected line,
    including lines that gave no row (``row`` None: type or time unreadable).

    A debug dict holds ``board``, ``row_index`` (line within its board), ``row``,
    ``conf`` (0..1), ``raw_text`` (the cells as read, joined), ``state`` (``ok``;
    ``unread``: text on the line but no train could be read; ``empty``: no text on the
    line), ``retry`` (only on re-read lines: ``{attempts, variant}``, variant None when
    no re-read succeeded) and ``fields``: per column ``{raw, norm, conf (0-100 or
    None), bbox (x, y, w, h in image px)}``.

    Lines with text but no complete row (type, time or number unreadable) are re-read
    with alternative preprocessing (``preprocess.VARIANTS``), only those lines and only
    their type/number/time columns, until they read or the frame's time budget
    (`budget_s`, default env ``OCR_FRAME_BUDGET_S`` = 8 s) is spent. Nothing is
    invented: a line no variant can read stays ``unread``. A summary of every frame
    goes to ``app.ocr.stats``.
    """
    t_start = time.perf_counter()
    img = _decode(image_bytes)
    if engine is None:
        engine = TesseractEngine()
    budget = frame_budget() if budget_s is None else budget_s

    panels = [(board, _Panel(half), x_off)
              for board, (half, x_off) in zip(BOARDS, preprocess.split_boards_offsets(img))]
    slots: list[tuple[str, int, _Panel, int]] = [
        (board, j, p, x_off) for board, p, x_off in panels for j in range(len(p))]
    if not slots:
        stats.record(_summary(panels, [], 0, 0.0, t_start))
        return [], []

    base_cells = [p.cells(j) for _, j, p, _ in slots]
    reads = {name: _Composite([c[name] for c in base_cells]).read(engine, *_TESS[name])
             for name in _ORDER}
    ctx = _Ctx(_get_matcher(), stations)
    entries: list[dict] = []
    for i, (board, j, p, x_off) in enumerate(slots):
        boxes = {n: (x + x_off, y, w, h) for n, (x, y, w, h) in p.boxes(j).items()}
        entry = _assemble(board, j, {name: reads[name][i] for name in _ORDER},
                          base_cells[i], boxes, ctx)
        entry["state"] = ("ok" if entry["row"] is not None
                          else "unread" if p.has_ink(j) else "empty")
        entries.append(entry)

    # -- re-read the lines with text but no complete row --------------------------------
    first_s = time.perf_counter() - t_start
    todo = [i for i, e in enumerate(entries) if e["state"] != "empty" and not _complete(e)]
    for board in BOARDS:  # a panel with many unreadable lines is a broken frame (glitch,
        # truncated JPEG): re-reading garbage only invents rows, so it is not retried
        mine = [i for i in todo if entries[i]["board"] == board]
        if len(mine) > MAX_RETRY_LINES:
            log.info("OCR: %s panel has %d unreadable lines; not re-read (broken frame?)",
                     board, len(mine))
            todo = [i for i in todo if entries[i]["board"] != board]
    attempts = {i: 0 for i in todo}
    est = first_s * len(_RETRY_COLS) / len(_ORDER)  # cost of one variant, until measured
    t_retry = time.perf_counter()
    try:
        for variant in preprocess.VARIANTS:
            if not todo:
                break
            if time.perf_counter() - t_start + est > budget:
                log.info("OCR re-read stopped by the %.1f s frame budget (%d line(s) left)",
                         budget, len(todo))
                break
            t_v = time.perf_counter()
            vreads = _reread(engine, [_variant_cells(slots[i], variant) for i in todo],
                             variant, t_start, budget)
            if vreads is None:  # budget spent between two columns
                break
            vcells, vtext = vreads
            left = []
            for k, i in enumerate(todo):
                attempts[i] += 1
                new = _merge(entries[i], slots[i], base_cells[i], vcells[k],
                             {n: vtext[n][k] for n in _RETRY_COLS}, ctx)
                if new is not None and not _duplicate(new, entries, i):
                    new["state"] = "ok"
                    new["retry"] = {"attempts": attempts[i], "variant": variant}
                    entries[i] = new
                else:
                    left.append(i)
            todo = left
            est = time.perf_counter() - t_v
    except Exception:  # an optional re-read never costs the first pass's rows
        log.warning("OCR re-read failed; first-pass reading kept", exc_info=True)
    for i, n in attempts.items():
        if n == 0:
            continue  # never re-read (budget): not reported as a re-read
        if "retry" not in entries[i]:
            entries[i]["retry"] = {"attempts": n, "variant": None}
        else:
            entries[i]["retry"]["attempts"] = n
    retry_s = time.perf_counter() - t_retry if attempts else 0.0
    _reread_delays(engine, slots, entries, ctx, t_start, budget)

    for e in entries:
        for f in e["fields"].values():
            f.pop("_tess", None)
            f.pop("_tess_conf", None)
    rows = [e["row"] for e in entries if e["row"] is not None]
    stats.record(_summary(panels, entries, sum(n > 0 for n in attempts.values()),
                          retry_s, t_start))
    return rows, entries


MAX_RETRY_LINES = 4  # per panel; more unreadable lines than this: the frame is broken
_RETRY_COLS = ("type", "no", "time")  # the fields a train row cannot exist without
_X4 = 4 / preprocess.SCALE  # "x4": cells upscaled from x3 to x4 for Tesseract
FRAME_BUDGET_S = 8.0  # OCR time per frame, re-reads included (the cycle is ~60 s)


def frame_budget() -> float:
    """Total OCR time allowed per frame, re-reads included (env OCR_FRAME_BUDGET_S)."""
    try:
        return max(0.0, float(os.environ.get("OCR_FRAME_BUDGET_S", FRAME_BUDGET_S)))
    except ValueError:
        return FRAME_BUDGET_S


def _complete(entry: dict) -> bool:
    r = entry["row"]
    return r is not None and bool(r.train_no)


def _reread(engine: OcrEngine, vcells: list[dict], variant: str, t_start: float,
            budget: float):
    """(cells, {column: readings}) of the re-read columns, or None when the frame budget
    runs out between two columns. Each Tesseract call gets at most the remaining budget
    (at least 1 s) as its timeout."""
    out = {}
    old_timeout = getattr(engine, "timeout", None)
    try:
        for name in _RETRY_COLS:
            left = budget - (time.perf_counter() - t_start)
            if left <= 0:
                return None
            if old_timeout is not None:
                engine.timeout = max(1.0, min(old_timeout, left))
            out[name] = _Composite([c[name] for c in vcells],
                                   upscale=_X4 if variant == "x4" else 1.0
                                   ).read(engine, *_TESS[name])
    finally:
        if old_timeout is not None:
            engine.timeout = old_timeout
    return vcells, out


def _merge(old: dict, slot, base: dict, vcells: dict, vtext: dict, ctx: "_Ctx"
           ) -> dict | None:
    """The line re-assembled with the re-read value of ONLY the columns that did not
    read (a value the first pass read is never replaced), or None if still incomplete."""
    board, j, _, _ = slot
    missing = [n for n in _RETRY_COLS if old["fields"][n]["norm"] is None]
    if not missing:
        return None
    tess = {n: (old["fields"][n]["_tess"], old["fields"][n]["_tess_conf"]) for n in _ORDER}
    cells = dict(base)
    for name in missing:
        tess[name] = vtext[name]
        cells[name] = vcells[name]
    boxes = {n: tuple(old["fields"][n]["bbox"]) for n in _ORDER}
    new = _assemble(board, j, tess, cells, boxes, ctx)
    if not _complete(new):
        return None
    for n in _RETRY_COLS:  # belt and braces: values read in the first pass stay
        if n not in missing and new["fields"][n]["norm"] != old["fields"][n]["norm"]:
            return None
    return new


def _duplicate(new: dict, entries: list[dict], i: int) -> bool:
    """A re-read giving the train number of another line of the same panel is a read of
    the neighbouring line (wider crop), not this one: rejected."""
    no = new["row"].train_no
    return any(k != i and e["board"] == new["board"] and e["row"] is not None
               and e["row"].train_no == no for k, e in enumerate(entries))


DELAY_VARIANTS = ("lvl+", "vline", "lvl-", "adapt")  # binarisations tried on unread delays


def _reread_delays(engine: OcrEngine, slots, entries: list[dict], ctx: "_Ctx",
                   t_start: float, budget: float) -> None:
    """Re-read, within the frame budget, the delay cells `_delay` left unread (glare,
    readers disagreeing), with other binarisations (a stricter threshold can cut the
    glare bridge between "+" and the digit). A variant's reading is taken only when it
    passes the same rules as the first pass; otherwise the delay stays unread. Records
    ``fields.delay.retry`` = {attempts, variant (None: still unread)}."""
    todo = [i for i, e in enumerate(entries)
            if e["row"] is not None and e["fields"]["delay"].get("check")]
    if not todo or ctx.matcher is None:
        return
    tries = {i: 0 for i in todo}
    try:
        for variant in DELAY_VARIANTS:
            if not todo or time.perf_counter() - t_start >= budget:
                break
            cells = [_variant_cells(slots[i], variant)["delay"] for i in todo]
            old_timeout = getattr(engine, "timeout", None)
            if old_timeout is not None:
                engine.timeout = max(1.0, min(old_timeout,
                                              budget - (time.perf_counter() - t_start)))
            try:
                texts = _Composite(cells).read(engine, *_TESS["delay"])
            finally:
                if old_timeout is not None:
                    engine.timeout = old_timeout
            left = []
            for k, i in enumerate(todo):
                tries[i] += 1
                text, conf, why = _delay(cells[k], texts[k], ctx.matcher)
                value = parse_delay(text)
                if why is None and value is not None:
                    _set_delay(entries[i], text, conf, value,
                               {"attempts": tries[i], "variant": variant})
                else:
                    left.append(i)
            todo = left
    except Exception:  # optional: the first pass (delay unread) stays
        log.warning("OCR delay re-read failed; delay left unread", exc_info=True)
    for i in todo:
        if tries[i]:
            entries[i]["fields"]["delay"]["retry"] = {"attempts": tries[i], "variant": None}


def _set_delay(entry: dict, text: str, conf: float | None, value: int, retry: dict) -> None:
    f = entry["fields"]["delay"]
    f.update(raw=text, norm=value, retry=retry,
             conf=None if conf is None else round(min(100.0, max(0.0, conf)), 1))
    f.pop("check", None)
    f.pop("seen", None)
    entry["row"] = dataclasses.replace(entry["row"], delay_min=value, delay_read=True)
    entry["raw_text"] = " ".join(t for t in (entry["fields"][n]["raw"] for n in _ORDER) if t)


def _variant_cells(slot, variant: str) -> dict[str, np.ndarray]:
    _, j, p, _ = slot
    if variant == "wide":  # crop wider: glyph tops/bottoms cut by a tight band
        y0, y1 = p.bands[j]
        pad = max(2, (y1 - y0) // 4)
        # ...but never past half the gap to a neighbouring line (its glyphs)
        if j > 0:
            pad = min(pad, max(0, (y0 - p.bands[j - 1][1]) // 2))
        if j + 1 < len(p.bands):
            pad = min(pad, max(0, (p.bands[j + 1][0] - y1) // 2))
        return p.cells(j, pad_y=pad)
    return p.cells(j, mask=p.variant(variant))


class _Ctx:
    """Per-frame constants of the row assembly."""

    def __init__(self, matcher: DigitMatcher | None, stations: Iterable[str]):
        self.matcher = matcher
        self.seed = canonical.seed_stations()
        self.known = set(stations) | self.seed


def _assemble(board: str, j: int, tess: dict, cells: dict, boxes: dict, ctx: _Ctx) -> dict:
    """Debug entry of one line (``row`` set when type and time read), from the
    Tesseract readings `tess` {column: (text, conf)} and the cell images `cells`."""
    cell = dict(tess)
    for name in _ALLOWED:
        if name != "delay":
            cell[name] = _numeric(name, cells[name], cell[name], ctx.matcher)
    d_text, d_conf, d_why = _delay(cells["delay"], cell["delay"], ctx.matcher)
    cell["delay"] = (d_text, d_conf)
    type_text, flagged = strip_flag(cell["type"][0])
    # "*" (flag) is stripped first; "I"/"RN".. are resolved only where measured
    train_type = resolve_type(type_text, _train_no(cell["no"][0]))
    sched = parse_time(cell["time"][0])
    confs = [c for _, c in cell.values() if c is not None]
    conf = sum(confs) / len(confs) / 100 if confs else 0.0
    station_raw = clean_station(cell["station"][0])
    operator_raw = canonical.clean_operator(cell["operator"][0])
    station, s_score = canonical.canonical_station(
        station_raw, ctx.known, preferred=ctx.seed)
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
                       "bbox": list(boxes[n]),
                       # Tesseract's own reading: a re-read of other columns starts here
                       "_tess": tess[n][0], "_tess_conf": tess[n][1]} for n in _ORDER},
        "station_score": s_score, "operator_score": o_score,
    }
    if d_why is not None:  # why the delay is unread, and what Tesseract alone saw
        entry["fields"]["delay"]["check"] = d_why
        entry["fields"]["delay"]["seen"] = tess["delay"][0]
    if train_type is None or sched is None:
        return entry
    entry["row"] = Row(
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
    )
    return entry


def _summary(panels, entries: list[dict], retried: int, retry_s: float,
             t_start: float) -> dict:
    """Per-frame summary for ``app.ocr.stats`` (rows per panel, re-reads, timings)."""
    per = {}
    for board, p, _ in panels:
        es = [e for e in entries if e["board"] == board]
        per[board] = {
            "lines": len(p), "rows": sum(_complete(e) for e in es),
            "unread": sum(e["state"] == "unread" for e in es),
            "empty": sum(e["state"] == "empty" for e in es),
            "groups_repaired": p.repaired,
            "retried": sum("retry" in e for e in es),
            "recovered": sum(bool(e.get("retry", {}).get("variant")) for e in es),
        }
    return {"boards": per, "retried": retried,
            "recovered": sum(v["recovered"] for v in per.values()),
            "retry_ms": int(retry_s * 1000),
            "duration_ms": int((time.perf_counter() - t_start) * 1000)}
