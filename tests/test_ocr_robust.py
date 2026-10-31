# © 2026 Andy217Ace
"""OCR robustness: photometric/geometric variants of the real fixtures.

The CFR webcam image changes with the light (dawn/dusk, exposure, white balance),
JPEG quality and small framing shifts. Each variant below is derived
programmatically from tests/fixtures/board_{1,2}.jpg and must still read:

* each board yields >= 10 rows (board_2 departures: >= 10 of 12 lines, i.e. >= 9
  of its 11 distinct services);
* sched_time and train_no are correct on >= 90 % of the recovered rows.

Rows are aligned to the golden lines by a monotone alignment on the row content,
so a missing row does not shift every following comparison.

``python -m tests.test_ocr_robust`` prints the per-variant table.
"""
from __future__ import annotations

import difflib
import json
import sys
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.ocr.reader import read_board
from tests.ocr_truth_images import capture

FIX = Path(__file__).parent / "fixtures"
FIXTURES = ("board_1", "board_2")
MIN_ROWS = 10
MIN_FIELD = 0.90


def _clip(a: np.ndarray) -> np.ndarray:
    return np.clip(a, 0, 255).astype(np.uint8)


def _gain(img, f):
    return _clip(img.astype(np.float32) * f)


def _gamma(img, g):
    lut = np.array([255.0 * (i / 255.0) ** g for i in range(256)])
    return _clip(lut[img])


def _contrast(img, f):
    x = img.astype(np.float32)
    return _clip((x - x.mean()) * f + x.mean())


def _cast(img, gains_bgr):
    return _clip(img.astype(np.float32) * np.array(gains_bgr, np.float32))


def _noise(img, sigma):
    rng = np.random.default_rng(1234)
    return _clip(img.astype(np.float32) + rng.normal(0, sigma, img.shape))


def _jpeg(img, q):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def _shift(img, dx, dy):
    h, w = img.shape[:2]
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def _scale(img, f):
    return cv2.resize(img, None, fx=f, fy=f,
                      interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC)


def _dim_right(img, f):
    out = img.copy()
    w = img.shape[1]
    out[:, w // 2:] = _gain(img[:, w // 2:], f)
    return out


VARIANTS = {
    "original": lambda im: im,
    "bright_0.55": lambda im: _gain(im, 0.55),
    "bright_0.70": lambda im: _gain(im, 0.70),
    "bright_1.30": lambda im: _gain(im, 1.30),
    "bright_1.60": lambda im: _gain(im, 1.60),
    "gamma_0.6": lambda im: _gamma(im, 0.6),
    "gamma_1.5": lambda im: _gamma(im, 1.5),
    "contrast_+30": lambda im: _contrast(im, 1.3),
    "contrast_-30": lambda im: _contrast(im, 0.7),
    "cast_warm": lambda im: _cast(im, (0.80, 0.95, 1.15)),
    "cast_cold": lambda im: _cast(im, (1.15, 1.00, 0.80)),
    "noise_6": lambda im: _noise(im, 6),
    "noise_12": lambda im: _noise(im, 12),
    "jpeg_40": lambda im: _jpeg(im, 40),
    "jpeg_60": lambda im: _jpeg(im, 60),
    "shift_+6": lambda im: _shift(im, 6, 6),
    "shift_-6": lambda im: _shift(im, -6, -6),
    "scale_0.9": lambda im: _scale(im, 0.9),
    "scale_1.1": lambda im: _scale(im, 1.1),
    "dim_departures_0.5": lambda im: _dim_right(im, 0.5),
}
# Variants a human cannot read either are excluded here with a justification.
EXCLUDED: dict[str, str] = {}


def _golden(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _sim(r, e) -> float:
    return ((r.train_no == e["train_no"]) + (r.sched_time == e["sched_time"])
            + (r.train_type == e["train_type"])
            + difflib.SequenceMatcher(None, r.station, e["station"]).ratio())


def align(rows, golden) -> list[tuple]:
    """Monotone alignment (rows in board order) maximising the content similarity."""
    n, m = len(rows), len(golden)
    best = np.zeros((n + 1, m + 1))
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = _sim(rows[i - 1], golden[j - 1])
            best[i, j] = max(best[i - 1, j], best[i, j - 1],
                             best[i - 1, j - 1] + (s if s >= 1.5 else -1e9))
    pairs, i, j = [], n, m
    while i and j:
        if best[i, j] == best[i - 1, j]:
            i -= 1
        elif best[i, j] == best[i, j - 1]:
            j -= 1
        else:
            pairs.append((rows[i - 1], golden[j - 1]))
            i, j = i - 1, j - 1
    return pairs[::-1]


@lru_cache(maxsize=None)
def _image(name: str) -> np.ndarray:
    return cv2.imread(str(capture(FIX / f"{name}.jpg")), cv2.IMREAD_COLOR)


@lru_cache(maxsize=None)
def evaluate(name: str, variant: str) -> dict:
    img = VARIANTS[variant](_image(name))
    ok, buf = cv2.imencode(".png", img)  # lossless: only the variant itself degrades
    rows = read_board(buf.tobytes())
    golden = _golden(name)
    out = {}
    for board in ("arrival", "departure"):
        got = [r for r in rows if r.board == board]
        pairs = align(got, golden[board])
        n = max(1, len(got))
        out[board] = {
            "rows": len(got), "expected": len(golden[board]), "aligned": len(pairs),
            "sched": sum(r.sched_time == e["sched_time"] for r, e in pairs) / n,
            "no": sum(r.train_no == e["train_no"] for r, e in pairs) / n,
        }
    return out


CASES = [(f, v) for f in FIXTURES for v in VARIANTS if v not in EXCLUDED]


@pytest.mark.parametrize("name,variant", CASES)
def test_variant_reads(name, variant):
    res = evaluate(name, variant)
    for board, r in res.items():
        assert r["rows"] >= MIN_ROWS, (board, r)
        assert r["sched"] >= MIN_FIELD, (board, r)
        assert r["no"] >= MIN_FIELD, (board, r)


def test_board_2_original_reads_every_line():
    res = evaluate("board_2", "original")
    assert res["arrival"]["rows"] == 12 and res["arrival"]["aligned"] == 12
    assert res["departure"]["rows"] == 12 and res["departure"]["aligned"] == 12
    for r in res.values():
        assert r["sched"] == 1.0 and r["no"] == 1.0


def test_alignment_skips_a_missing_row():
    from app.models import Row

    g = _golden("board_2")["departure"]
    rows = [Row("departure", e["train_type"], e["train_no"], e["station"], e["operator"],
                e["sched_time"]) for k, e in enumerate(g) if k != 3]
    pairs = align(rows, g)
    assert len(pairs) == 11
    assert all(r.train_no == e["train_no"] for r, e in pairs)


def table() -> str:
    lines = [f"{'fixture':8} {'variant':20} {'arr':>7} {'dep':>7} "
             f"{'sched a/d':>11} {'no a/d':>11}  ok"]
    for name, variant in CASES:
        res = evaluate(name, variant)
        a, d = res["arrival"], res["departure"]
        good = all(r["rows"] >= MIN_ROWS and r["sched"] >= MIN_FIELD
                   and r["no"] >= MIN_FIELD for r in res.values())
        lines.append(
            f"{name:8} {variant:20} {a['rows']:>3}/{a['expected']:<3} "
            f"{d['rows']:>3}/{d['expected']:<3} "
            f"{a['sched']:>5.2f}/{d['sched']:<5.2f} {a['no']:>5.2f}/{d['no']:<5.2f}  "
            f"{'OK' if good else 'FAIL'}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(table())
    sys.exit(0)
