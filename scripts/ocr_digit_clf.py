# © 2026 Andy217Ace
"""Set de adevar silver din capturile reale + clasificator de cifre (EXPERIMENTAL).

Nu e folosit de productie. Pasi (fiecare scrie in OUT_DIR):

    python scripts/ocr_digit_clf.py extract IMG_ROOT DB_JSON OUT_DIR
        Citeste fiecare captura cu cititorul actual (``read_board_debug``) si
        extrage celulele numerice (no, time, delay, platform) cu segmentarea de
        productie (``digits.segment_spans``), plus citirea din ``observations``
        (DB_JSON: exportul tabelelor captures si observations, vezi mai jos).
    python scripts/ocr_digit_clf.py label OUT_DIR [VERIFIED.csv]
        Aplica regulile de consens: silver = citirea actuala == observations, in
        format valid, cu numar de glife egal cu textul. Restul e "contestat"
        (dezacord, consens slab, segmentare). VERIFIED.csv (id,label) din verificarea
        umana, daca exista, promoveaza celulele contestate la silver.
    python scripts/ocr_digit_clf.py verify OUT_DIR [N]
        Lista de verificare: pana la N celule contestate, cu crop si eticheta propusa.
    python scripts/ocr_digit_clf.py truth OUT_DIR
        Glifele setului de adevar scris de mana (tests/fixtures/ocr_truth/truth.json).
    python scripts/ocr_digit_clf.py train OUT_DIR
        Antreneaza un MLP mic (numpy) pe silver-train; raporteaza acuratetea pe
        silver-test, pe setul de adevar scris de mana, si fata de motorul actual.

DB_JSON: ``{"captures": [...], "observations": [...]}``, exportul celor doua tabele
din tabela.db (read-only). Capturile nu se comit: IMG_ROOT trebuie sa fie in afara
repo-ului (ex. ``IMG_ROOT/captures/AAAA/LL/ZZ/hhmmss-xxxx.jpg``).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("OMP_THREAD_LIMIT", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TRUTH = ROOT / "tests" / "fixtures" / "ocr_truth" / "truth.json"
_WIN = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
if "TESSERACT_CMD" not in os.environ and _WIN.exists():
    os.environ["TESSERACT_CMD"] = str(_WIN)

import numpy as np  # noqa: E402

NUM_COLS = ("no", "time", "delay", "platform")
ALLOWED = {"no": "0123456789", "time": "0123456789:", "delay": "0123456789+",
           "platform": "0123456789"}
CLASSES = "0123456789+:"
TEST_SHARE = 5  # one frame in this many goes to the test split (by hash of its name)


def _norm(s) -> str:
    return "".join(str(s or "").split())


def _quant(g: np.ndarray) -> np.ndarray:
    """A glyph as the classifier and the matcher both see it: 8-bit, back to 0..1."""
    return (np.clip(g, 0, 1) * 255).round().astype(np.float32) / 255.0


def _split_of(frame: str) -> int:
    return int(hashlib.md5(frame.encode("utf-8")).hexdigest(), 16) % TEST_SHARE == 0


def _frame_cells(img_path: Path, matcher):
    """(cells, glyphs) of one frame: cell records (no text yet) and per glyph
    (uint8 image, matcher char, score, margin, fused)."""
    from app.ocr import digits, preprocess
    from app.ocr.reader import BOARDS, _Panel, _decode, read_board_debug

    data = img_path.read_bytes()
    _, debug = read_board_debug(data, budget_s=60.0)
    img = _decode(data)
    dbg = {(d["board"], d["row_index"]): d for d in debug}
    cells, glyphs = [], []
    for board, (half, x_off) in zip(BOARDS, preprocess.split_boards_offsets(img)):
        p = _Panel(half)
        for j in range(len(p)):
            cc = p.cells(j)
            boxes = p.boxes(j)
            entry = dbg.get((board, j))
            if entry is None:
                continue
            for col in NUM_COLS:
                cell = cc[col]
                spans = digits.segment_spans(cell)
                rec = {"frame": None, "board": board, "row": j, "col": col,
                       "box": [int(boxes[col][0] + x_off), int(boxes[col][1]),
                               int(boxes[col][2]), int(boxes[col][3])],
                       "A": _norm(entry["fields"][col]["raw"]) if col in entry["fields"] else "",
                       "retry": entry.get("retry") is not None,
                       "g0": len(glyphs), "n": len(spans)}
                for g, _, fused in spans:
                    gq = _quant(g)
                    ch, sc, mg = matcher.classify(gq, ALLOWED[col])
                    glyphs.append((np.round(gq * 255).astype(np.uint8), ch, sc, mg, bool(fused)))
                cells.append(rec)
    return cells, glyphs, debug


def _frame_job(args):
    """(name, cells, glyphs) of one frame; cached on disk when ``cache`` is given (a rerun
    after a crash does not read the frames again). cells None: the frame is not read."""
    import pickle
    name, path, cache = args
    if cache and Path(cache).exists():
        with open(cache, "rb") as f:
            return pickle.load(f)
    from app.ocr.digits import DigitMatcher
    matcher = DigitMatcher.load()
    try:
        cells, glyphs, _ = _frame_cells(Path(path), matcher)
    except Exception as e:  # undecodable, too small, or OCR timeout under load
        print("cadru fara citire:", name, type(e).__name__, e, flush=True)
        return name, None, None
    for c in cells:
        c["frame"] = name
    res = (name, cells, glyphs)
    if cache:
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        with open(cache, "wb") as f:
            pickle.dump(res, f)
    return res


def _run_frames(pairs):
    from multiprocessing import Pool
    workers = int(os.environ.get("NPROC", "3"))
    out = []
    with Pool(workers) as pool:
        for k, r in enumerate(pool.imap(_frame_job, pairs), 1):
            out.append(r)
            if k % 20 == 0 or k == len(pairs):
                print("progres", k, "/", len(pairs), flush=True)
    return out


def _save(out: Path, cells: list[dict], glyphs: list[tuple]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    X = np.stack([g[0] for g in glyphs]) if glyphs else np.zeros((0, 32, 32), np.uint8)
    np.savez_compressed(
        out / "glyphs_raw.npz", X=X,
        mchar=np.array([g[1] for g in glyphs], dtype="U1"),
        mscore=np.array([g[2] for g in glyphs], np.float32),
        mmargin=np.array([g[3] for g in glyphs], np.float32),
        fused=np.array([g[4] for g in glyphs], bool))
    (out / "cells_raw.json").write_text(json.dumps(cells, ensure_ascii=False), encoding="utf-8")


def extract(img_root: str, db_json: str, out_dir: str) -> None:
    from app.ocr.digits import DigitMatcher  # noqa: F401  (fails early if missing)

    root = Path(img_root)
    db = json.loads(Path(db_json).read_text(encoding="utf-8"))
    obs: dict[tuple[str, str, int], dict] = {}
    cap_of = {}
    for cap in db["captures"]:
        if cap["path"]:
            cap_of[cap["id"]] = cap["path"][:-4] if cap["path"].endswith(".jpg") else cap["path"]
    for o in db["observations"]:
        frame = cap_of.get(o["capture_id"])
        if frame is not None:
            obs[(frame, o["board"], o["row_index"])] = json.loads(o["fields_json"] or "{}")
    pairs = []
    cache_dir = Path(out_dir) / "cache"
    for frame in sorted(cap_of.values()):
        p = root / "captures" / (frame + ".jpg")
        if p.exists():
            pairs.append((frame, str(p), str(cache_dir / (hashlib.md5(frame.encode()).hexdigest() + ".pkl"))))
    print("frames", len(pairs), "of", len(cap_of), flush=True)
    results = _run_frames(pairs)
    failed = {r[0] for r in results if r[1] is None}
    if failed:  # OCR timeouts under parallel load: once more, one frame at a time
        print("reluate in serie:", len(failed), flush=True)
        redo = {r[0]: r for r in (_frame_job(p) for p in pairs if p[0] in failed)}
        results = [r if r[1] is not None else redo[r[0]] for r in results]
        print("fara citire dupa a doua incercare:",
              sum(1 for r in results if r[1] is None), flush=True)
    cells, glyphs = [], []
    for frame, cs, gs in results:
        if cs is None:
            continue
        base = len(glyphs)
        for c in cs:
            c["g0"] += base
            ob = obs.get((frame, c["board"], c["row"]))
            c["B"] = None if ob is None else _norm((ob.get(c["col"]) or {}).get("raw"))
            c["has_obs"] = ob is not None
            cells.append(c)
        glyphs.extend(gs)
    _save(Path(out_dir), cells, glyphs)
    print("cells", len(cells), "glyphs", len(glyphs), flush=True)


# --- labelling ---------------------------------------------------------------------------
def _format_ok(col: str, text: str) -> bool:
    import re
    pat = {"no": r"\d{3,5}", "time": r"\d{1,2}:\d{2}", "delay": r"\+\d{1,3}",
           "platform": r"\d{1,2}"}[col]
    return re.fullmatch(pat, text) is not None


def label(out_dir: str, verified_csv: str | None = None) -> dict:
    out = Path(out_dir)
    cells = json.loads((out / "cells_raw.json").read_text(encoding="utf-8"))
    raw = np.load(out / "glyphs_raw.npz")
    X, mchar, mscore, mmargin, fused = (raw["X"], raw["mchar"], raw["mscore"],
                                        raw["mmargin"], raw["fused"])
    verified: dict[str, str] = {}
    if verified_csv:  # verify_index.csv after the human check: "verificat" = da
        with open(verified_csv, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("verificat", "").strip().lower() in ("da", "1", "yes"):
                    verified[row["id"]] = _norm(row.get("eticheta_verificata", ""))

    keep_X, keep_y, keep_meta = [], [], []
    stat: dict[tuple[str, str], int] = {}
    for c in cells:
        A, B = c["A"], c.get("B")
        status, reason, text = "contestat", "", None
        if cell_id(c) in verified:
            status, text = "verificat", verified[cell_id(c)]
        elif "?" in A or (B is not None and "?" in B):
            status, reason = "nelizibil", "marcat ?"
        elif B is None:
            reason = "fara observatie"
        elif c["retry"]:
            reason = "recitit"
        elif A != B:
            reason = "dezacord"
        elif c["col"] == "no" and A == "":
            status, reason = "nelizibil", "gol"
        elif A != "" and not _format_ok(c["col"], A):
            reason = "format"
        elif A == "" and c["n"] > 0:
            reason = "pete"
        else:
            status, text = "silver", A
        if status in ("silver", "verificat"):
            g0, n = c["g0"], c["n"]
            if text == "" and n == 0:
                status = "gol"  # blank cell, no glyph: a known blank, no glyph example
            elif text == "" or n != len(text):
                status, text, reason = "contestat", None, "segmentare"
            elif status == "silver" and any(
                    not (mscore[g] >= 0.60 and mmargin[g] >= 0.04) for g in range(g0, g0 + n)):
                status, text, reason = "contestat", None, "slab"
        c["status"], c["reason"], c["label"] = status, reason, text
        stat[(c["col"], status)] = stat.get((c["col"], status), 0) + 1
        if status in ("silver", "verificat") and text:
            for k, ch in enumerate(text):
                g = c["g0"] + k
                keep_X.append(X[g])
                keep_y.append(ch)
                keep_meta.append((c["frame"], c["col"], _split_of(c["frame"]), bool(fused[g]),
                                  mchar[g], float(mscore[g]), float(mmargin[g])))
    (out / "cells.json").write_text(json.dumps(cells, ensure_ascii=False), encoding="utf-8")
    if keep_X:
        frames, cols, split, fus, mch, msc, mmg = zip(*keep_meta)
    else:
        frames = cols = split = fus = mch = msc = mmg = ()
    np.savez_compressed(
        out / "dataset.npz",
        X=np.stack(keep_X) if keep_X else np.zeros((0, 32, 32), np.uint8),
        y=np.array(keep_y, dtype="U1"), frame=np.array(frames, dtype="U200"),
        col=np.array(cols, dtype="U8"), split=np.array(split, bool), fused=np.array(fus, bool),
        mchar=np.array(mch, dtype="U1"), mscore=np.array(msc, np.float32),
        mmargin=np.array(mmg, np.float32))
    summary = {"cells": len(cells),
               "by_status": {f"{c}/{s}": n for (c, s), n in sorted(stat.items())},
               "glyphs_train_silver": int(sum(1 for s in split if not s)) if split else 0,
               "glyphs_test_silver": int(sum(split)) if split else 0}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return summary


def cell_id(c: dict) -> str:
    return f"{c['frame']}|{c['board']}|{c['row']}|{c['col']}"


# --- verification list -------------------------------------------------------------------
PRIORITY = ("dezacord", "segmentare", "slab", "format", "pete", "recitit", "fara observatie",
            "fara eticheta")


def verify(out_dir: str, n: int = 150, img_root: str | None = None) -> None:
    import cv2
    out = Path(out_dir)
    cells = json.loads((out / "cells.json").read_text(encoding="utf-8"))
    cont = [c for c in cells if c["status"] == "contestat"]
    rng = random.Random(7)
    picked: list[dict] = []
    for reason in PRIORITY:
        grp = [c for c in cont if c["reason"] == reason]
        rng.shuffle(grp)
        room = n - len(picked)
        picked.extend(grp[:room])
        if len(picked) >= n:
            break
    vdir = out / "verify"
    vdir.mkdir(parents=True, exist_ok=True)
    rows = []
    raw = np.load(out / "glyphs_raw.npz")
    for c in picked:
        ids = cell_id(c)
        name = hashlib.md5(ids.encode("utf-8")).hexdigest()[:12] + ".png"
        if img_root:
            img = cv2.imread(str(Path(img_root) / "captures" / (c["frame"] + ".jpg")))
            x, y, w, h = c["box"]
            crop = img[max(0, y):y + h, max(0, x):x + w] if img is not None else None
            if crop is not None and crop.size:
                cv2.imwrite(str(vdir / name), cv2.resize(crop, None, fx=4, fy=4,
                                                         interpolation=cv2.INTER_CUBIC))
        mch = "".join(str(raw["mchar"][g]) for g in range(c["g0"], c["g0"] + c["n"]))
        rows.append({"id": ids, "imagine": f"verify/{name}", "cadru": c["frame"],
                     "rand": c["row"] + 1, "placa": c["board"], "coloana": c["col"],
                     "eticheta_propusa": c["A"], "observatii": c["B"] if c["B"] is not None else "",
                     "motor_glife": mch, "motiv": c["reason"], "eticheta_verificata": "",
                     "verificat": ""})
    with open(out / "verify_index.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)
    with open(out / "verify_index.html", "w", encoding="utf-8") as f:
        f.write('<meta charset="utf-8"><title>Verificare cifre</title>'
                '<style>body{font-family:sans-serif}td{padding:4px;vertical-align:middle}</style>'
                '<table border=1><tr><th>crop</th><th>cadru</th><th>rand/placa/col</th>'
                '<th>eticheta propusa</th><th>observatii</th><th>motiv</th></tr>')
        for r in rows:
            f.write(f"<tr><td><img src='{r['imagine']}' height=60></td><td>{r['cadru']}</td>"
                    f"<td>{r['rand']} {r['placa']} {r['coloana']}</td><td>{r['eticheta_propusa']}</td>"
                    f"<td>{r['observatii']}</td><td>{r['motiv']}</td></tr>")
        f.write("</table>")
    print("verify", len(rows), "of", len(cont), "contested", flush=True)


# --- set de adevar scris de mana ---------------------------------------------------------
def truth_glyphs(out_dir: str) -> dict:
    from app.ocr import truth as truth_mod
    from app.ocr import digits, preprocess
    from app.ocr.digits import DigitMatcher
    from app.ocr.reader import BOARDS, _Panel, _decode

    t = truth_mod.load(TRUTH)
    matcher = DigitMatcher.load()
    X, y, col, mch, msc, mmg, fus, frames = [], [], [], [], [], [], [], []
    skipped = {"count": 0, "cells": 0}
    for frame, boards in t["frames"].items():
        data = (TRUTH.parent.parent / f"{frame}.jpg").read_bytes()
        img = _decode(data)
        panels = {b: (_Panel(half), x_off) for b, (half, x_off) in
                  zip(BOARDS, preprocess.split_boards_offsets(img))}
        for board, lines in boards.items():
            p, _ = panels[board]
            for i, lab in enumerate(lines):
                cc = p.cells(i)
                for c, text in _truth_texts(lab):
                    if text is None:
                        continue
                    spans = digits.segment_spans(cc[c])
                    cand = [text]
                    if c == "time" and text[:1] == "0":
                        cand.append(text[1:])
                    chosen = next((x for x in cand if len(spans) == len(x)), None)
                    skipped["cells"] += 1
                    if chosen is None:
                        skipped["count"] += 1
                        continue
                    for k, (g, _, fu) in enumerate(spans):
                        gq = _quant(g)
                        ch, sc, mg = matcher.classify(gq, ALLOWED[c])
                        X.append(np.round(gq * 255).astype(np.uint8))
                        y.append(chosen[k])
                        col.append(c)
                        frames.append(frame)
                        mch.append(ch)
                        msc.append(sc)
                        mmg.append(mg)
                        fus.append(bool(fu))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "truth_glyphs.npz", X=np.stack(X), y=np.array(y, dtype="U1"),
                        col=np.array(col, dtype="U8"), frame=np.array(frames, dtype="U200"),
                        mchar=np.array(mch, dtype="U1"), mscore=np.array(msc, np.float32),
                        mmargin=np.array(mmg, np.float32), fused=np.array(fus, bool))
    print("truth glyphs", len(y), "cells", skipped["cells"], "skipped (count)", skipped["count"],
          flush=True)
    return skipped


def _truth_texts(lab: dict):
    """(column, expected text or None) per numeric field of one hand-labelled line."""
    def get(f):
        v = lab.get(f, "?")
        return None if v == "?" else v
    no = get("no")
    yield "no", (str(no) if isinstance(no, int) else None)
    tm = get("time")
    yield "time", (tm if isinstance(tm, str) and tm else None)
    d = get("delay")
    if isinstance(d, int):
        yield "delay", ("" if d == 0 else f"+{d}")
    else:
        yield "delay", None
    if "platform" in lab and lab["platform"] != "?":
        p = lab["platform"]
        yield "platform", ("" if p is None else str(p))
    else:
        yield "platform", None


# --- classifier -------------------------------------------------------------------------
def _mask(cols: np.ndarray) -> np.ndarray:
    M = np.zeros((len(cols), len(CLASSES)), bool)
    for name, allowed in ALLOWED.items():
        rows = cols == name
        M[np.ix_(rows, [CLASSES.index(c) for c in allowed])] = True
    return M


def mlp_fit(X, y, hidden=128, epochs=30, lr=2e-3, wd=1e-4, seed=0, log=print):
    rng = np.random.default_rng(seed)
    n, d = X.shape
    k = len(CLASSES)
    P = {"W1": rng.normal(0, np.sqrt(2 / d), (d, hidden)).astype(np.float32),
         "b1": np.zeros(hidden, np.float32),
         "W2": rng.normal(0, np.sqrt(2 / hidden), (hidden, k)).astype(np.float32),
         "b2": np.zeros(k, np.float32)}
    m = {q: np.zeros_like(v) for q, v in P.items()}
    v2 = {q: np.zeros_like(v) for q, v in P.items()}
    step = 0
    for ep in range(epochs):
        perm = rng.permutation(n)
        tot = 0.0
        for s in range(0, n, 256):
            idx = perm[s:s + 256]
            xb, yb = X[idx], y[idx]
            hpre = xb @ P["W1"] + P["b1"]
            h = np.maximum(hpre, 0)
            z = h @ P["W2"] + P["b2"]
            z = z - z.max(1, keepdims=True)
            e = np.exp(z)
            pr = e / e.sum(1, keepdims=True)
            tot += float(-np.log(pr[np.arange(len(yb)), yb] + 1e-9).sum())
            pr[np.arange(len(yb)), yb] -= 1
            gz = pr / len(yb)
            g = {"W2": h.T @ gz + wd * P["W2"], "b2": gz.sum(0)}
            dh = gz @ P["W2"].T
            dh[hpre <= 0] = 0
            g["W1"] = xb.T @ dh + wd * P["W1"]
            g["b1"] = dh.sum(0)
            step += 1
            for q in P:
                m[q] = 0.9 * m[q] + 0.1 * g[q]
                v2[q] = 0.999 * v2[q] + 0.001 * g[q] ** 2
                mh = m[q] / (1 - 0.9 ** step)
                vh = v2[q] / (1 - 0.999 ** step)
                P[q] -= lr * mh / (np.sqrt(vh) + 1e-8)
        if ep % 10 == 9 or ep == epochs - 1:
            log(f"  epoca {ep + 1}/{epochs} pierdere medie {tot / n:.4f}")
    return P


def mlp_predict(P, X, cols) -> np.ndarray:
    h = np.maximum(X @ P["W1"] + P["b1"], 0)
    z = h @ P["W2"] + P["b2"]
    z = np.where(_mask(cols), z, -np.inf)
    return z.argmax(1)


def _acc(pred_chars, y, mask=None):
    ok = np.array(pred_chars) == y
    if mask is not None:
        ok, y = ok[mask], y[mask]
    return (float(ok.mean()) if len(y) else float("nan")), int(len(y))


def train(out_dir: str) -> dict:
    out = Path(out_dir)
    d = np.load(out / "dataset.npz")
    X = d["X"].reshape(len(d["y"]), -1).astype(np.float32) / 255.0
    y = np.array([CLASSES.index(c) for c in d["y"]])
    yc = d["y"]
    cols, split = d["col"], d["split"]
    tr, te = ~split, split
    print("silver train", int(tr.sum()), "silver test", int(te.sum()), flush=True)
    P = mlp_fit(X[tr], y[tr], log=lambda s: print(s, flush=True))
    res = {"n_train": int(tr.sum()), "n_test": int(te.sum())}

    def report(name, Xs, ys, cs, mch, mscore, mmargin):
        """ys, mch: characters (the truth and the matcher's reading)."""
        pred = mlp_predict(P, Xs, cs)
        clf_chars = np.array([CLASSES[i] for i in pred])
        trusted = (mscore >= 0.60) & (mmargin >= 0.04)
        out_r = {"n": int(len(ys)),
                 "clasificator": _acc(clf_chars, ys)[0],
                 "motor": _acc(mch, ys)[0],
                 "n_nesigur_motor": int((~trusted).sum()),
                 "clasificator_nesigur_motor": _acc(clf_chars, ys, ~trusted)[0],
                 "motor_nesigur_motor": _acc(mch, ys, ~trusted)[0]}
        res[name] = out_r
        print(name, json.dumps(out_r, ensure_ascii=False), flush=True)

    report("silver_test", X[te], yc[te], cols[te], d["mchar"][te], d["mscore"][te], d["mmargin"][te])
    t = np.load(out / "truth_glyphs.npz")
    Xt = t["X"].reshape(len(t["y"]), -1).astype(np.float32) / 255.0
    report("truth_scris_de_mana", Xt, t["y"], t["col"], t["mchar"], t["mscore"], t["mmargin"])
    np.savez_compressed(out / "model.npz", **P)
    (out / "train_report.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    return res


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd, args = argv[0], argv[1:]
    if cmd == "extract":
        extract(*args[:3])
    elif cmd == "label":
        label(args[0], args[1] if len(args) > 1 else None)
    elif cmd == "verify":
        verify(args[0], int(args[1]) if len(args) > 1 else 150, args[2] if len(args) > 2 else None)
    elif cmd == "truth":
        truth_glyphs(args[0])
    elif cmd == "train":
        train(args[0])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
