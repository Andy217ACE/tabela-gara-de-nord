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
_PANEL_MIN_FRAC = 0.25  # a row/column belongs to the panel when this share is blue
_MIN_GROUP_FRAC = 0.06  # blue row groups shorter than this share of the height are not rows


def blue_mask(img_bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return (h >= _BLUE_H[0]) & (h <= _BLUE_H[1]) & (s >= _BLUE_S) & (v >= _BLUE_V)


def text_mask(img_bgr: np.ndarray) -> np.ndarray:
    """Binary image, black text (0) on white (255), upscaled x3.

    Keeps only light pixels (white/yellow); the blue background and the red
    watermark both have a low green channel and drop out.
    """
    bright = np.minimum(img_bgr[:, :, 1], img_bgr[:, :, 2])
    big = cv2.resize(bright, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_CUBIC)
    return np.where(big > TEXT_LEVEL, 0, 255).astype(np.uint8)


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
        span = _span(blue_mask(half).mean(axis=0), _PANEL_MIN_FRAC)
        if span is not None and span[1] - span[0] > 0.5 * half.shape[1]:
            half = half[:, span[0]:span[1]]
            x0 += span[0]
        out.append((half, x0))
    return out


def _runs(on: np.ndarray) -> list[list[int]]:
    """[start, end) intervals where a boolean 1-D array is True."""
    padded = np.concatenate(([False], on.astype(bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [[int(a), int(b)] for a, b in zip(edges[::2], edges[1::2])]


def panel_rows(board_bgr: np.ndarray) -> np.ndarray:
    """Boolean per image row: True inside a blue row group.

    Thin blue strips (the dark-blue column header line) are discarded: a real
    group holds several text rows and is much taller.
    """
    h = board_bgr.shape[0]
    on = blue_mask(board_bgr).mean(axis=1) >= _PANEL_MIN_FRAC
    out = np.zeros(h, bool)
    for a, b in _runs(on):
        if b - a >= _MIN_GROUP_FRAC * h:
            out[a:b] = True
    return out


def board_mask(board_bgr: np.ndarray) -> np.ndarray:
    """Text mask of one board, blanked outside the blue panel rows.

    Removes the title, column headers and clock, which sit on the dark area above.
    """
    mask = text_mask(board_bgr)
    keep = np.repeat(panel_rows(board_bgr), SCALE)
    mask[~keep] = 255
    return mask


def row_bands(board_mask: np.ndarray) -> list[tuple[int, int]]:
    """Text line intervals (y0, y1) by horizontal projection of a black-on-white mask."""
    ink = (board_mask == 0).sum(axis=1)
    runs = _runs(ink >= max(2, int(0.004 * board_mask.shape[1])))
    if not runs:
        return []
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
