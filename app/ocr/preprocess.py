# © 2026 Andy217Ace
"""Image preprocessing for the board: colour mask, board split, row detection.

All geometry is expressed relative to the image (fractions) or derived from the
image itself (blue panel extent, projections), so renditions of the same layout
at a different resolution still work.
"""
from __future__ import annotations

import cv2
import numpy as np

SCALE = 3  # text masks are upscaled x3 for Tesseract

# The board image holds two panels side by side: arrivals (left), departures (right).
# Coarse halves as fractions of the width; each half is then tightened to its blue panel.
HALVES = ((0.0, 0.5), (0.5, 1.0))

# Text brightness = min(G, R): high for white and yellow text, low for the blue
# background (R, G low) and for the red watermark (G low), including red-on-blue (magenta).
TEXT_LEVEL = 100

# Blue panel pixels in OpenCV HSV (H in 0..179).
_BLUE_H = (95, 135)
_BLUE_S = 90
_BLUE_V = 40
_BLUE_V_REL = 0.4  # rows: ...and at least this share of the lit panel's value (p90)
# Panel edges: the value crossing at this share between the dark surround (p10)
# and the lit panel (p90) is stable under gain/gamma/contrast (the absolute 40 is
# not: a lifted gamma widens the blurred edge by up to 10 px). The span is then
# padded back by _EDGE_PAD of the half width to the geometry COLUMNS were
# calibrated on (the absolute threshold on board_1.jpg).
_EDGE_REL = 0.3
_EDGE_PAD = 0.004
_PANEL_MIN_FRAC = 0.25  # a row/column belongs to the panel when this share is blue
_MIN_GROUP_FRAC = 0.06  # blue row groups shorter than this share of the height are not rows


def blue_mask(img_bgr: np.ndarray, relative: bool = False) -> np.ndarray:
    """Blue panel pixels. `relative` also requires a value of at least
    _BLUE_V_REL x the lit panel's (row detection under a lifted exposure)."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    cand = (h >= _BLUE_H[0]) & (h <= _BLUE_H[1]) & (s >= _BLUE_S)
    # Value threshold relative to the lit panel: a lifted exposure/gamma makes the
    # dark-blue gaps between the row groups (and the header area) "blue" too.
    v_min = _BLUE_V
    if relative and cand.any():
        v_min = max(_BLUE_V, _BLUE_V_REL * float(np.percentile(v[cand], 90)))
    return cand & (v >= v_min)


def _edge_mask(img_bgr: np.ndarray) -> np.ndarray:
    """Blue pixels brighter than the mid-edge level (see _EDGE_REL)."""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    cand = (h >= _BLUE_H[0]) & (h <= _BLUE_H[1]) & (s >= _BLUE_S)
    if not cand.any():
        return cand
    bg = float(np.percentile(v, 10))
    lit = float(np.percentile(v[cand], 90))
    return cand & (v >= max(_BLUE_V / 4, bg + _EDGE_REL * (lit - bg)))


def _brightness(img_bgr: np.ndarray) -> np.ndarray:
    return np.minimum(img_bgr[:, :, 1], img_bgr[:, :, 2])


def text_mask(img_bgr: np.ndarray, level: float = TEXT_LEVEL) -> np.ndarray:
    """Binary image, black text (0) on white (255), upscaled x3.

    Keeps only light pixels (white/yellow); the blue background and the red
    watermark both have a low green channel and drop out. `level` is the
    brightness threshold (`board_mask` passes the per-panel `text_level`).
    """
    big = cv2.resize(_brightness(img_bgr), None, fx=SCALE, fy=SCALE,
                     interpolation=cv2.INTER_CUBIC)
    return np.where(big > level, 0, 255).astype(np.uint8)


# Per-panel text threshold: Otsu on the panel's own brightness distribution,
# bounded so that a flat panel (no text) or a pathological histogram never turns
# the background into text.
_LEVEL_MIN, _LEVEL_MAX = 40, 200
_MIN_TEXT_CONTRAST = 40  # brightest text vs. median background, else: no text


def text_level(board_bgr: np.ndarray, rows: np.ndarray | None = None) -> float:
    """Text/background brightness threshold of one panel, from its own pixels.

    The CFR webcam exposure and white balance drift (dawn/dusk, auto-exposure);
    a fixed absolute threshold then either thins the glyphs (dim frame: colon
    dots vanish, digits break) or turns light separators and halos into text
    (bright frame: the text lines merge into one band). Otsu on min(G, R) inside
    the blue panel rows tracks the drift.
    """
    if rows is None:
        rows = panel_rows(board_bgr)
    bright = _brightness(board_bgr)
    sample = (bright[rows] if rows.any() else bright).reshape(1, -1)
    if sample.size == 0:
        return float(TEXT_LEVEL)
    lo, hi = np.percentile(sample, [50, 99.5])
    if hi - lo < _MIN_TEXT_CONTRAST:
        return 255.0  # flat panel: nothing is text
    otsu, _ = cv2.threshold(sample, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(min(max(otsu, _LEVEL_MIN, lo + 0.5 * _MIN_TEXT_CONTRAST), _LEVEL_MAX))


def _span(profile: np.ndarray, min_frac: float) -> tuple[int, int] | None:
    idx = np.flatnonzero(profile >= min_frac)
    if idx.size == 0:
        return None
    return int(idx[0]), int(idx[-1]) + 1


def split_boards(img_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(arrivals, departures): each half tightened horizontally to its blue panel."""
    (a, _), (d, _) = split_boards_offsets(img_bgr)
    return a, d


def split_boards_offsets(img_bgr: np.ndarray) -> list[tuple[np.ndarray, int]]:
    """Like split_boards, plus the x offset of each panel in the original image."""
    h, w = img_bgr.shape[:2]
    out = []
    for f0, f1 in HALVES:
        x0, x1 = int(round(f0 * w)), int(round(f1 * w))
        half = img_bgr[:, x0:x1]
        span = _span(_edge_mask(half).mean(axis=0), _PANEL_MIN_FRAC)
        if span is not None and span[1] - span[0] > 0.5 * half.shape[1]:
            pad = int(round(_EDGE_PAD * half.shape[1]))
            a = max(0, span[0] - pad)
            half = half[:, a:min(half.shape[1], span[1] + pad)]
            x0 += a
        out.append((half, x0))
    return out


def _runs(on: np.ndarray) -> list[list[int]]:
    """[start, end) intervals where a boolean 1-D array is True."""
    padded = np.concatenate(([False], on.astype(bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [[int(a), int(b)] for a, b in zip(edges[::2], edges[1::2])]


def panel_rows(board_bgr: np.ndarray, relative: bool = True) -> np.ndarray:
    """Boolean per image row: True inside a blue row group.

    Thin blue strips (the dark-blue column header line) are discarded: a real
    group holds several text rows and is much taller. `relative` (default) uses
    the exposure-relative blue value (see `blue_mask`).
    """
    h = board_bgr.shape[0]
    on = blue_mask(board_bgr, relative=relative).mean(axis=1) >= _PANEL_MIN_FRAC
    out = np.zeros(h, bool)
    for a, b in _runs(on):
        if b - a >= _MIN_GROUP_FRAC * h:
            out[a:b] = True
    return out


def board_masks(board_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(text mask, layout mask) of one board, blanked outside the blue panel rows.

    Blanking removes the title, column headers and clock (dark area above). The
    layout mask also has the vertical separators removed: it drives row-band and
    column detection. The text mask keeps every glyph pixel (a separator touching
    a "1" would otherwise erase it) and is what the cells are cut from.
    """
    rows = panel_rows(board_bgr)
    mask = text_mask(board_bgr, text_level(board_bgr, rows))
    mask[~np.repeat(rows, SCALE)] = 255
    layout = mask.copy()
    _drop_vertical_lines(layout, rows)
    return mask, layout


def board_mask(board_bgr: np.ndarray) -> np.ndarray:
    """Layout mask of one board (see `board_masks`)."""
    return board_masks(board_bgr)[1]


_VLINE_FRAC = 0.6  # a vertical stroke this share of a blue row group tall is a separator


def _drop_vertical_lines(mask: np.ndarray, rows: np.ndarray) -> None:
    """Remove (in place) vertical separators/glare lines crossing a row group.

    They are much taller than any glyph and would otherwise bridge the gaps
    between text lines and land inside the cells.
    """
    groups = [b - a for a, b in _runs(rows)]
    if not groups:
        return
    length = int(_VLINE_FRAC * float(np.median(groups)) * SCALE)
    if length < 4 * SCALE:
        return
    ink = (mask == 0).astype(np.uint8)
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((length, 1), np.uint8))
    mask[lines > 0] = 255


_GAP_REL = 0.15  # an image row with less ink than this share of a typical text row is a gap
_GROW_REL = 1.0  # cores grow back over rows with at least this share of the gap threshold


def row_bands(board_mask: np.ndarray) -> list[tuple[int, int]]:
    """Text line intervals (y0, y1) by horizontal projection of a black-on-white mask.

    Hysteresis: line cores are found with a threshold relative to the ink of a
    typical text row (stray specks or glare between the lines do not merge them),
    then each core grows back to the low absolute threshold so the glyph tops and
    bottoms are not cropped; two lines growing into each other split at the
    emptiest row between them.
    """
    ink = (board_mask == 0).sum(axis=1)
    low = max(2, int(0.004 * board_mask.shape[1]))
    nz = ink[ink > 0]
    rel = _GAP_REL * float(np.percentile(nz, 75)) if nz.size else 0.0
    cores = _runs(ink >= max(low, rel))
    grow = max(low, _GROW_REL * rel)
    if not cores:
        return []
    runs = []
    for i, (a, b) in enumerate(cores):
        top = cores[i - 1][1] if i else 0
        bot = cores[i + 1][0] if i + 1 < len(cores) else len(ink)
        while a > top and ink[a - 1] >= grow:
            a -= 1
        while b < bot and ink[b] >= grow:
            b += 1
        runs.append([a, b])
    for i in range(len(runs) - 1):  # grown into the neighbour: cut at the minimum
        if runs[i][1] >= runs[i + 1][0]:
            lo, hi = cores[i][1], cores[i + 1][0]
            cut = lo + int(np.argmin(ink[lo:hi])) if hi > lo else lo
            runs[i][1], runs[i + 1][0] = cut, cut + 1 if hi > lo else cut
    med = float(np.median([b - a for a, b in runs]))
    # Merge thin fragments (diacritics, breves) into the closest neighbouring run.
    merged = True
    while merged and len(runs) > 1:
        merged = False
        for i, (a, b) in enumerate(runs):
            if b - a >= 0.5 * med:
                continue
            gaps = []
            if i > 0:
                gaps.append((a - runs[i - 1][1], i - 1))
            if i + 1 < len(runs):
                gaps.append((runs[i + 1][0] - b, i + 1))
            gap, j = min(gaps)
            if gap <= 0.35 * med:
                lo, hi = min(i, j), max(i, j)
                runs[lo] = [runs[lo][0], runs[hi][1]]
                del runs[hi]
                merged = True
                break
    heights = [b - a for a, b in runs]
    med = float(np.median(heights))
    bands: list[tuple[int, int]] = []
    for a, b in runs:
        hgt = b - a
        if hgt < 0.5 * med:
            continue  # stray specks
        k = max(1, int(round(hgt / med))) if hgt > 1.6 * med else 1
        step = hgt / k
        for i in range(k):
            bands.append((int(round(a + i * step)), int(round(a + (i + 1) * step))))
    return bands
