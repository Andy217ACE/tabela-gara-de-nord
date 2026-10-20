# © 2026 Andy217Ace
"""Glyph template matching for the numeric fields (the board uses one fixed font).

Templates live in ``digit_templates.npz`` next to this module. They are averaged
glyph bitmaps cut from a calibration image whose values are known (see
``build_templates`` and ``python -m app.ocr.digits``). Glyphs are normalised to a
fixed box, so the matcher is independent of the source resolution.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

GLYPH_H = 32
GLYPH_W = 32
_SHIFT = 2  # tolerated misalignment (px, normalised box) when matching
PITCH = 0.78  # digit advance / text line height in the board font
WIDE = 1.0    # a component wider than this x line height holds several glyphs
MIN_SCORE = 0.60   # glyph match below this correlation is not trusted
MIN_MARGIN = 0.01  # ...nor a near-tie with the runner-up template
TEMPLATES_PATH = Path(__file__).with_name("digit_templates.npz")


def segment(cell: np.ndarray) -> list[np.ndarray]:
    """Split a black-on-white cell into normalised glyph images (float 0..1, ink = 1).

    Connected components overlapping horizontally are merged (``:`` is two dots);
    specks are dropped. Each glyph keeps its vertical position inside the text
    line, so ``+`` and ``:`` stay distinguishable from digits.
    """
    ink = (cell == 0).astype(np.uint8)
    if not ink.any():
        return []
    n, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    boxes = [list(stats[i, :4]) for i in range(1, n)]  # x, y, w, h
    if not boxes:
        return []
    ref_h = max(b[3] for b in boxes)
    min_area = 0.015 * ref_h * ref_h
    boxes = [b for b, i in zip(boxes, range(1, n)) if stats[i, 4] >= min_area]
    boxes.sort(key=lambda b: b[0])
    merged: list[list[int]] = []
    for x, y, w, h in boxes:
        if merged:
            mx, my, mw, mh = merged[-1]
            overlap = min(mx + mw, x + w) - max(mx, x)
            if overlap > 0.5 * min(mw, w):
                x0, y0 = min(mx, x), min(my, y)
                merged[-1] = [x0, y0, max(mx + mw, x + w) - x0, max(my + mh, y + h) - y0]
                continue
        merged.append([x, y, w, h])
    if not merged:
        return []
    line_top = min(b[1] for b in merged)
    line_bot = max(b[1] + b[3] for b in merged)
    line_h = line_bot - line_top
    # Drop fragments that are tiny in both directions (noise, neighbour slivers).
    glyphs = []
    for x, y, w, h in merged:
        if h < 0.15 * line_h and w < 0.15 * line_h:
            continue
        for x0, x1 in _split_touching(ink[line_top:line_bot], x, w, line_h):
            crop = ink[line_top:line_bot, x0:x1].astype(np.float32)
            glyphs.append(_normalise(crop))
    return glyphs


def _split_touching(line: np.ndarray, x: int, w: int, line_h: int) -> list[tuple[int, int]]:
    """Split a component wider than one glyph (touching digits) at the thinnest columns.

    The board font has fixed-pitch digits about PITCH x line height apart.
    """
    if w <= WIDE * line_h:
        return [(x, x + w)]
    k = max(2, int(round(w / (PITCH * line_h))))
    col_ink = line[:, x:x + w].sum(axis=0)
    step = w / k
    win = max(1, int(0.2 * step))
    cuts = [x]
    for i in range(1, k):
        c = int(round(i * step))
        lo, hi = max(1, c - win), min(w - 1, c + win + 1)
        cuts.append(x + lo + int(np.argmin(col_ink[lo:hi])))
    cuts.append(x + w)
    return [(a, b) for a, b in zip(cuts[:-1], cuts[1:]) if b > a]


def _normalise(crop: np.ndarray) -> np.ndarray:
    h, w = crop.shape
    scale = GLYPH_H / h
    nw = max(1, min(GLYPH_W, int(round(w * scale))))
    img = cv2.resize(crop, (nw, GLYPH_H), interpolation=cv2.INTER_AREA)
    out = np.zeros((GLYPH_H, GLYPH_W), np.float32)
    x0 = (GLYPH_W - nw) // 2
    out[:, x0:x0 + nw] = img
    return out


class DigitMatcher:
    def __init__(self, labels: str, templates: np.ndarray):
        self.labels = labels
        self.templates = templates.astype(np.float32)

    @classmethod
    def load(cls, path: Path = TEMPLATES_PATH) -> "DigitMatcher":
        data = np.load(path)
        return cls(str(data["labels"]), data["templates"])

    def classify(self, glyph: np.ndarray, allowed: str) -> tuple[str, float, float]:
        """(best character, its score 0..1, margin over the runner-up)."""
        padded = cv2.copyMakeBorder(glyph, _SHIFT, _SHIFT, _SHIFT, _SHIFT,
                                    cv2.BORDER_CONSTANT, value=0)
        scored = sorted(
            ((float(cv2.matchTemplate(padded, tpl, cv2.TM_CCOEFF_NORMED).max()), ch)
             for ch, tpl in zip(self.labels, self.templates) if ch in allowed),
            reverse=True)
        if not scored:
            return "", 0.0, 0.0
        runner_up = scored[1][0] if len(scored) > 1 else 0.0
        return scored[0][1], scored[0][0], scored[0][0] - runner_up

    def read(self, cell: np.ndarray, allowed: str) -> tuple[str, float, bool]:
        """(text, weakest glyph score 0..1, trusted) for a numeric cell.

        ``trusted`` is False when any glyph matched poorly or ambiguously.
        An empty cell gives ("", 1.0, True).
        """
        text, worst, trusted = [], 1.0, True
        for g in segment(cell):
            ch, score, margin = self.classify(g, allowed)
            text.append(ch)
            worst = min(worst, score)
            trusted &= score >= MIN_SCORE and margin >= MIN_MARGIN
        return "".join(text), worst, trusted


def build_templates(samples: list[tuple[np.ndarray, str]]) -> tuple[str, np.ndarray]:
    """Average glyphs per character from (cell, known text) pairs.

    Cells whose glyph count differs from the text length are skipped.
    """
    acc: dict[str, list[np.ndarray]] = {}
    for cell, text in samples:
        glyphs = segment(cell)
        if len(glyphs) != len(text):
            continue
        for g, ch in zip(glyphs, text):
            acc.setdefault(ch, []).append(g)
    labels = "".join(sorted(acc))
    return labels, np.stack([np.mean(acc[c], axis=0) for c in labels])


def _calibration_samples(image_path: Path, golden_path: Path, boards: tuple[str, ...]):
    from app.ocr import preprocess
    from app.ocr.reader import BOARDS, cell_grid

    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    samples = []
    for board, half in zip(BOARDS, preprocess.split_boards(img)):
        if board not in boards:
            continue
        for cells, exp in zip(cell_grid(half), golden[board]):
            samples.append((cells["no"], str(exp["train_no"])))
            samples.append((cells["time"], exp["sched_time"]))
            if exp["delay_min"]:
                samples.append((cells["delay"], f"+{exp['delay_min']}"))
            if exp["platform"] is not None:
                samples.append((cells["platform"], str(exp["platform"])))
    return samples


def main(argv: list[str]) -> int:
    """python -m app.ocr.digits IMAGE GOLDEN_JSON [board ...] — rebuild the templates."""
    if len(argv) < 2:
        print(main.__doc__)
        return 2
    boards = tuple(argv[2:]) or ("arrival", "departure")
    labels, templates = build_templates(
        _calibration_samples(Path(argv[0]), Path(argv[1]), boards))
    np.savez_compressed(TEMPLATES_PATH, labels=np.array(labels), templates=templates)
    print(f"saved {len(labels)} templates ({labels!r}) to {TEMPLATES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
