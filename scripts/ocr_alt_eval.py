# © 2026 Andy217Ace
"""Evaluarea alternativei OCR (app/ocr/alt_reader.py) pe cadrele cu adevar scris de mana.

    python scripts/ocr_alt_eval.py baseline OUT.pkl      # citeste cadrele cu cititorul actual
    python scripts/ocr_alt_eval.py eval OUT.pkl MODEL.npz [--json REZ.json] [--thr 0.95]

``baseline`` ruleaza cititorul actual o singura data pe fiecare cadru (truth.json + holdout) si
salveaza intrarile de debug. ``eval`` aplica alternativa peste ele si masoara, fata de adevar,
criteriile de promovare din docs/superpowers/specs/2026-11-17-ocr-alternativa.md:

  * NATURAL: liniile pe care cititorul actual le lasa necitite si ce face alternativa cu ele:
    recuperate corect, recuperate gresit (citiri false), lasate necitite.
  * CELULE: alternativa pe TOATE celulele no/time cu adevar, ca si cum cititorul ar fi esuat pe
    ele: da suficiente valori verificate (>= 300) pentru rata de citiri false, pe prag.
  * INTERFERENTA: liniile pe care alternativa nu le-a completat trebuie sa ramana identice.
  * BUGET: p95 al timpului alternativei.

Tesseract ruleaza cu OMP_THREAD_LIMIT=1 in NPROC procese (implicit 2). Capturile reale nu sunt in
git (OCR_TRUTH_DIR, ca in tests/ocr_truth_images.py).
"""
from __future__ import annotations

import copy
import json
import os
import pickle
import sys
import time
from pathlib import Path

os.environ["OMP_THREAD_LIMIT"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures"
TRUTH = FIX / "ocr_truth" / "truth.json"
HOLDOUT = FIX / "ocr_truth" / "holdout" / "holdout.json"
_WIN = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if "TESSERACT_CMD" not in os.environ and _WIN.exists():
    os.environ["TESSERACT_CMD"] = str(_WIN)

COLS = ("no", "time")
THRESHOLDS = [0.5, 0.8, 0.9, 0.95, 0.99, 0.999]
CRITERIA = {  # pragurile de promovare din spec
    "recuperate_min": 0.60,   # criteriul 1: >= 60% din cadrele-esec devin acceptate
    "gresite_max": 0.005,     # criteriul 2: <= 0,5% valori gresite pe liniile alternativei
    "valori_min": 300,        # ... cu minim 300 de valori verificate
    "buget_s": 4.0,           # criteriul 5: p95 <= OCR_ALT_BUDGET_S
}


def frame_path(frame: str) -> Path:
    if frame.startswith("ocr_truth/"):
        private = Path(os.environ.get("OCR_TRUTH_DIR") or FIX / "ocr_truth" / "private")
        return private / (frame[len("ocr_truth/"):] + ".jpg")
    return FIX / f"{frame}.jpg"


def truth_frames() -> dict:
    """{frame: {board: [line labels]}} din truth.json + holdout.json (doar cadre cu imagine)."""
    from app.ocr import truth
    frames = dict(truth.load(TRUTH)["frames"])
    if HOLDOUT.is_file():
        frames.update(truth.load(HOLDOUT)["frames"])
    return {f: b for f, b in frames.items() if frame_path(f).is_file()}


def _read_one(frame: str):
    from app.ocr.reader import read_board_debug
    t0 = time.perf_counter()
    _, debug = read_board_debug(frame_path(frame).read_bytes(), budget_s=60.0)
    return frame, debug, time.perf_counter() - t0


def baseline(out: str) -> None:
    from multiprocessing import Pool
    names = sorted(truth_frames())
    with Pool(int(os.environ.get("NPROC", "2"))) as pool:
        res = {f: {"debug": d, "secs": s} for f, d, s in pool.imap(_read_one, names)}
    Path(out).write_bytes(pickle.dumps(res))
    print("cadre", len(res))


# --- evaluare --------------------------------------------------------------------------------
def _label(tf: dict, frame: str, board: str, j: int):
    lines = tf.get(frame, {}).get(board, [])
    return lines[j] if j < len(lines) else None


def _verdict(label, col: str, got) -> str:
    """ok / wrong / skip (adevarul lipseste sau e "?": nu se poate verifica)."""
    exp = label.get(col, "?") if label else "?"
    if exp in ("?", None):
        return "skip"
    return "ok" if str(got) == str(exp) else "wrong"


def _cache_panels(alt) -> None:
    """alt._panels cu o singura decodare per cadru (aceeasi imagine, mai multe apeluri)."""
    real, memo = alt._panels, {}

    def cached(image):
        key = hash(image)
        if key not in memo:
            memo[key] = real(image)
        return memo[key]
    alt._panels = cached
    alt._panels_real = real


def natural(base: dict, tf: dict, model, alt, min_prob: float) -> dict:
    """Liniile pe care cititorul actual le lasa necitite, si ce face alternativa cu ele."""
    out = {"cadre": len(base), "cadre_cu_necitite": 0, "cadre_eligibile": 0,
           "cadre_recuperate_complet": 0, "linii_necitite": 0, "linii_fara_tip": 0,
           "linii_eligibile": 0, "recuperate": 0, "valori": {"ok": 0, "wrong": 0, "skip": 0},
           "gresite": [], "interferenta": 0, "secs": []}
    for frame, rec in sorted(base.items()):
        es = copy.deepcopy(rec["debug"])
        un = alt.unread_lines(es)
        n_un = sum(len(v) for v in un.values())
        out["linii_necitite"] += n_un
        out["linii_fara_tip"] += sum(es[i]["fields"]["type"]["norm"] is None
                                    for v in un.values() for i in v)
        out["cadre_cu_necitite"] += bool(n_un)
        before = copy.deepcopy(es)
        elig = alt.eligible(before)
        out["linii_eligibile"] += len(elig)
        out["cadre_eligibile"] += bool(elig)
        info = alt.recover(frame_path(frame).read_bytes(), es, model, min_prob=min_prob)
        out["secs"].append(info["secs"])
        out["recuperate"] += info["recovered"]
        out["cadre_recuperate_complet"] += bool(n_un) and info["recovered"] == n_un
        for i, (a, b) in enumerate(zip(before, es)):
            if i in info["lines"]:
                for col in b["alt"]["cols"]:
                    v = _verdict(_label(tf, frame, b["board"], b["row_index"]), col,
                                 b["fields"][col]["norm"])
                    out["valori"][v] += 1
                    if v == "wrong":
                        out["gresite"].append([frame, b["board"], b["row_index"], col,
                                               b["fields"][col]["norm"]])
            elif a["row"] != b["row"] or a["state"] != b["state"] or a["fields"] != b["fields"]:
                out["interferenta"] += 1  # o linie neatinsa de alternativa s-a schimbat
    return out


def cells(base: dict, tf: dict, model, alt, min_prob: float) -> dict:
    """Nivel de celula, pe TOATE liniile cu adevar: alternativa citeste celula chiar daca
    cititorul a reusit (simuleaza esecul lui). Pe prag: citite / gresite; argmax fara
    abstinenta (acuratetea clasificatorului); citirea cititorului pentru comparatie."""
    res = {c: {"n": 0, "reader_ok": 0, "reader_wrong": 0, "reader_unread": 0, "argmax_ok": 0,
               "by_thr": {str(t): {"read": 0, "ok": 0, "wrong": 0} for t in THRESHOLDS}}
           for c in COLS}
    examples, secs = [], []
    for frame, rec in sorted(base.items()):
        t0 = time.perf_counter()
        panels = alt._panels_real(frame_path(frame).read_bytes())
        decode = time.perf_counter() - t0
        per_line = []
        for e in rec["debug"]:
            label = _label(tf, frame, e["board"], e["row_index"])
            if label is None:
                continue
            t1 = time.perf_counter()
            cc = panels[e["board"]].cells(e["row_index"])
            for col in COLS:
                exp = label.get(col, "?")
                if exp in ("?", None):
                    continue
                r = res[col]
                r["n"] += 1
                got = e["fields"][col]["norm"]
                if got is None:
                    r["reader_unread"] += 1
                elif _verdict(label, col, got) == "ok":
                    r["reader_ok"] += 1
                else:
                    r["reader_wrong"] += 1
                am = alt.read_cell(model, cc[col], col, min_prob=0.0)
                r["argmax_ok"] += am is not None and _verdict(label, col, am[0]) == "ok"
                for t in THRESHOLDS:
                    x = alt.read_cell(model, cc[col], col, min_prob=t)
                    if x is None:
                        continue
                    b = r["by_thr"][str(t)]
                    b["read"] += 1
                    ok = _verdict(label, col, x[0]) == "ok"
                    b["ok" if ok else "wrong"] += 1
                    if not ok and t == min_prob:
                        examples.append([frame, e["board"], e["row_index"], col, x[0], str(exp)])
            per_line.append(time.perf_counter() - t1)
        secs.append(decode + sum(per_line) * 24 / max(1, len(per_line)))
    return {"cols": res, "gresite_la_prag": examples, "secs_cadru_complet": secs}


def p95(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))] if xs else 0.0


def evaluate(pkl: str, model_path: str, json_out: str | None = None,
             thr: str | None = None) -> dict:
    from app.ocr import alt_reader as alt
    model = alt.AltModel.load(model_path)
    tf = truth_frames()
    base = {f: v for f, v in pickle.loads(Path(pkl).read_bytes()).items() if f in tf}  # nosec B301 - own cache written by this tool, never external input
    min_prob = alt.MIN_PROB if thr is None else float(thr)
    _cache_panels(alt)
    nat = natural(base, tf, model, alt, min_prob)
    cel = cells(base, tf, model, alt, min_prob)
    v = nat["valori"]
    report = {"model": str(model_path), "min_prob": min_prob, "natural": nat, "cells": cel,
              "p95_linii_necitite_s": p95(nat["secs"]),
              "p95_cadru_complet_s": p95(cel["secs_cadru_complet"]), "criterii": CRITERIA}
    print(f"model {model_path}  prag glifa {min_prob}")
    print(f"\nNATURAL ({nat['cadre']} cadre): {nat['cadre_cu_necitite']} cu linii necitite, "
          f"{nat['linii_necitite']} linii necitite ({nat['linii_fara_tip']} fara tip citit: "
          f"nerecuperabile), {nat['linii_eligibile']} eligibile")
    print(f"  recuperate {nat['recuperate']}; valori ok {v['ok']} / gresite {v['wrong']} / "
          f"neverificabile {v['skip']}; cadre recuperate complet "
          f"{nat['cadre_recuperate_complet']}/{nat['cadre_cu_necitite']}")
    print(f"  interferenta (linii neatinse schimbate): {nat['interferenta']}")
    print("\nCELULE (toate liniile cu adevar; alternativa citeste si celulele citite de cititor):")
    print(f"{'camp':<5}{'n':>5} {'cititor ok':>10} {'gresit':>7} {'necitit':>8} {'argmax ok':>10}")
    for c in COLS:
        r = cel["cols"][c]
        print(f"{c:<5}{r['n']:>5} {r['reader_ok']:>10} {r['reader_wrong']:>7} "
              f"{r['reader_unread']:>8} {r['argmax_ok']:>10}")
    print(f"\n{'prag':>6}  {'no citite/gresite':>18} {'time citite/gresite':>20}  gresite%")
    for t in THRESHOLDS:
        rs = [cel["cols"][c]["by_thr"][str(t)] for c in COLS]
        tot, wr = sum(x["read"] for x in rs), sum(x["wrong"] for x in rs)
        pct = f"{100 * wr / tot:.2f}%" if tot else "-"
        print(f"{t:>6}  {rs[0]['read']:>13}/{rs[0]['wrong']:<4} {rs[1]['read']:>15}/{rs[1]['wrong']:<4}"
              f"  {pct}")
    for ex in cel["gresite_la_prag"][:20]:
        print("   gresit la prag:", *ex)
    print(f"\np95 timp: linii necitite {report['p95_linii_necitite_s']:.2f} s; "
          f"cadru complet (24 linii, limita superioara) {report['p95_cadru_complet_s']:.2f} s")
    if json_out:
        Path(json_out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print("raport:", json_out)
    return report


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd == "baseline":
        baseline(*args)
    elif cmd == "eval":
        opts = {a: args[i + 1] for i, a in enumerate(args) if a in ("--json", "--thr")}
        evaluate(args[0], args[1], opts.get("--json"), opts.get("--thr"))
    else:
        print(__doc__)
