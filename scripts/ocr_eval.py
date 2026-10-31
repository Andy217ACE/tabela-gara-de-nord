# © 2026 Andy217Ace
"""OCR field accuracy against the hand-labelled truth set (app/ocr/truth.py).

    python scripts/ocr_eval.py predict OUT.json [IMG_DIR]       # read every truth frame
    python scripts/ocr_eval.py score OUT.json [BEFORE.json]      # table (+ before/after)

Frames are named by their path under tests/fixtures without ".jpg" (IMG_DIR overrides
that root). Tesseract runs
with OMP_THREAD_LIMIT=1 in NPROC processes (default 4): never run it unthrottled on the
production server (a parallel run there stalled the live OCR for 16 minutes).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["OMP_THREAD_LIMIT"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TRUTH = ROOT / "tests" / "fixtures" / "ocr_truth" / "truth.json"
_WIN = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if "TESSERACT_CMD" not in os.environ and _WIN.exists():
    os.environ["TESSERACT_CMD"] = str(_WIN)


def _work(path: str):
    from app.ocr import truth
    from app.ocr.reader import read_board_debug
    _, debug = read_board_debug(Path(path).read_bytes(), budget_s=60.0)
    return Path(path).stem, [{"board": b, "row": i, **v}
                             for (b, i), v in truth.lines_of(debug).items()]


def _image(name: str, img_dir: str | None) -> Path:
    """Capturile "ocr_truth/..." sunt private: OCR_TRUTH_DIR (implicit .../ocr_truth/private)."""
    if img_dir:
        return Path(img_dir) / f"{name}.jpg"
    if name.startswith("ocr_truth/"):
        private = Path(os.environ.get("OCR_TRUTH_DIR") or TRUTH.parent / "private")
        return private / (name[len("ocr_truth/"):] + ".jpg")
    return TRUTH.parent.parent / f"{name}.jpg"


def predict(out: str, img_dir: str | None = None) -> None:
    from multiprocessing import Pool

    from app.ocr import truth
    frames = truth.load(TRUTH)["frames"]
    names = sorted(frames)
    with Pool(int(os.environ.get("NPROC", "4"))) as pool:
        res = dict(zip(names, (lines for _, lines in pool.map(
            _work, [str(_image(name, img_dir)) for name in names]))))
    Path(out).write_text(json.dumps(res), encoding="utf-8")
    print("frames", len(res))


def _as_pred(run: dict) -> dict:
    return {frame: {(l["board"], l["row"]): l for l in lines} for frame, lines in run.items()}


def score(*runs: str) -> None:
    from app.ocr import truth
    t = truth.load(TRUTH)
    results = []
    for path in runs:
        r = truth.score(t, _as_pred(json.loads(Path(path).read_text(encoding="utf-8"))))
        results.append(r)
        print(path)
        print("\n".join(truth.table(r)))
        for f in truth.FIELDS:
            for m in r["misses"][f]:
                print("   ", f, *m)
    if len(results) == 2:
        print("\ncamp      gresit inainte -> dupa | necitit inainte -> dupa")
        for f in truth.FIELDS:
            a, b = results[1]["counts"][f], results[0]["counts"][f]
            print(f"{f:<9} {a['wrong']:>6} -> {b['wrong']:<4} | {a['unread']:>7} -> {b['unread']}")


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd == "predict":
        predict(*args)
    elif cmd == "score":
        score(*args)
    else:
        print(__doc__)
