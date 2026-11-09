# © 2026 Andy217Ace
"""Antrenare zilnica a clasificatorului de cifre, in MOD UMBRA: nu promoveaza nimic.

Pasi (toate scrierile sunt in WORKDIR, implicit /var/lib/tabela/shadow):
    1. export: capturile si observatiile din baza (deschisa doar in citire) -> export.json
    2. extract + label (scripts/ocr_digit_clf.py): crop-uri si etichete silver in run/
    3. antrenare MLP (numpy) pe silver-train
    4. evaluare pe silver-test, pe setul scris de mana (truth.json) si fata de motorul curent
    5. report-AAAA-LL-ZZ.json cu acuratetile si decizia "nu promovez" (cu motiv)

Nu se atinge: app/ (inclusiv app/ocr/digit_templates.npz), baza de date, VERSION,
CHANGELOG.md, sw.js. Etichetele silver nu sunt verificate de om.

Setul scris de mana: tests/fixtures/ocr_truth/truth.json din repo, altfel WORKDIR/truth.json
(daca exista). Imaginile cadrelor sunt capturi reale, deci nu sunt in git: se cauta intai in
WORKDIR/truth-img/<cadru>.jpg (copiate manual pe server), apoi langa truth.json, ca in
ocr_digit_clf. Cadrele fara imagine se sar si se numara in raport (set_adevar_cadre). Fara set
de adevar, raportul il spune si nu se evalueaza nimic pe el.

Rulare (pe server, din tabela-shadow-train.service):
    python scripts/nightly_shadow_train.py [--workdir DIR] [--db FILE] [--img-root DIR]
"""
from __future__ import annotations

import argparse
import json
import shutil
import signal
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKDIR = Path("/var/lib/tabela/shadow")
DEFAULT_DB = Path("/var/lib/tabela/tabela.db")
DEFAULT_IMG_ROOT = Path("/var/lib/tabela")
REPO_TRUTH = ROOT / "tests" / "fixtures" / "ocr_truth" / "truth.json"
TRUTH_IMG = "truth-img"  # WORKDIR/truth-img/<cadru>.jpg: imaginile setului scris de mana
TIME_LIMIT_S = 2 * 3600
# Cadre citite cu OCR pe noapte, esantion stabil din toata retentia (ocr_digit_clf.select_frames).
# Fara limita, timpul si memoria cresteau cu retentia capturilor: 10 544 de cadre (9.11) = peste
# 2 ore doar de OCR si ~2,4 mil. de glife = OOM la antrenare (7.11). 3000 de cadre: ~700 mii de
# glife, ~3 GB de X float32; cu cache-ul pastrat intre nopti se citesc doar cadrele noi.
MAX_FRAMES = 3000
CACHE = "cache"  # WORKDIR/cache/<amprenta motorului OCR>/: citirile per cadru, pastrate intre nopti
MIN_TRAIN_GLYPHS = 200
EPOCHS = 30
DECISION = "nu promovez"
MIN_SCORE, MIN_MARGIN = 0.60, 0.04  # aceleasi praguri ca app/ocr/digits.py (nesigur)
SIGNIFICANT = 0.005  # diferenta de 0,5 puncte procentuale fata de motor
LIMITS = [
    "Etichetele silver sunt acordul dintre cititorul curent si observatiile salvate: "
    "aceeasi sursa, nu verificare independenta; nu sunt verificate de om.",
    "Setul de antrenare vine doar din capturile pastrate pe server (retentie limitata), "
    f"cel mult {MAX_FRAMES} de cadre pe noapte, esantion stabil din toata retentia; "
    "numerele exacte sunt in surse, cadre si etichete.",
    "Setul scris de mana acopera cadre din 21-27.10; nu reprezinta neaparat conditiile de azi.",
]


def _now_local() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Europe/Bucharest"))
    except Exception:  # fara tzdata: ora locala a sistemului
        return datetime.now().astimezone()


def _fin(x):
    """Numar finit sau None (JSON nu are nan)."""
    return None if x is None or not np.isfinite(x) else float(x)


def _check_workdir(workdir: Path) -> Path:
    w = workdir.resolve()
    if w == ROOT or ROOT in w.parents:
        raise ValueError(f"WORKDIR nu poate fi in repo: {w}")
    return w


def export_db(db: Path, img_root: Path, out_json: Path, select=None) -> dict:
    """Capturile si observatiile din baza, in formatul asteptat de ocr_digit_clf.extract.
    Baza se deschide doar in citire (mode=ro); nu se scrie nimic in ea.

    Se exporta doar capturile cu fisier pe disc alese de ``select`` (lista de cadre ->
    sublista; implicit toate) si observatiile lor: export.json se incarca intreg in memorie,
    deci nu trebuie sa creasca cu toata baza (observatiile capturilor sterse de retentie
    raman in baza)."""
    con = sqlite3.connect(f"{Path(db).resolve().as_uri()}?mode=ro", uri=True)
    try:
        n_caps = n_with_img = n_obs = 0
        on_disk = {}
        for i, p in con.execute("SELECT id, path FROM captures"):
            n_caps += 1
            if p:
                n_with_img += 1
                if (Path(img_root) / "captures" / p).is_file():
                    on_disk[p] = i
        # select primeste numele cadrelor (calea fara .jpg), ca ocr_digit_clf.extract
        frame_of = {(p[:-4] if p.endswith(".jpg") else p): p for p in on_disk}
        chosen = list(frame_of) if select is None else select(list(frame_of))
        caps = [{"id": on_disk[frame_of[f]], "path": frame_of[f]} for f in sorted(chosen)]
        ids = {c["id"] for c in caps}
        obs = []
        for c, b, r, f in con.execute(
                "SELECT capture_id, board, row_index, fields_json FROM observations"):
            n_obs += 1
            if c in ids:
                obs.append({"capture_id": c, "board": b, "row_index": r, "fields_json": f})
    finally:
        con.close()
    out_json.write_text(json.dumps({"captures": caps, "observations": obs}, ensure_ascii=False),
                        encoding="utf-8")
    return {"capturi": n_caps, "capturi_cu_imagine": n_with_img,
            "capturi_cu_fisier": len(on_disk), "observatii": n_obs,
            "cadre_exportate": len(caps), "observatii_exportate": len(obs)}


def _truth_file(candidates) -> Path | None:
    for p in candidates:
        if p is not None and Path(p).is_file():
            return Path(p)
    return None


def _eval(clf, P, X, y, cols, mch, msc, mmg) -> dict:
    """Acuratetea clasificatorului si a motorului curent pe un set (chars)."""
    if len(y) == 0:
        return {"n": 0, "clasificator": None, "motor": None}
    pred = clf.mlp_predict(P, X, cols)
    clf_chars = np.array([clf.CLASSES[i] for i in pred])
    trusted = (msc >= MIN_SCORE) & (mmg >= MIN_MARGIN)
    return {
        "n": int(len(y)),
        "clasificator": _fin(clf._acc(clf_chars, y)[0]),
        "motor": _fin(clf._acc(mch, y)[0]),
        "n_nesigur_motor": int((~trusted).sum()),
        "clasificator_nesigur_motor": _fin(clf._acc(clf_chars, y, ~trusted)[0]),
        "motor_nesigur_motor": _fin(clf._acc(mch, y, ~trusted)[0]),
    }


def _unit(a: np.ndarray) -> np.ndarray:
    """Glife uint8 -> float32 in 0..1, cu o singura alocare (impartirea e pe loc)."""
    a = a.astype(np.float32)
    a /= 255.0
    return a


def _train_eval(clf, run: Path, workdir: Path, day: str, truth_file: Path | None) -> dict:
    d = np.load(run / "dataset.npz")
    te = np.asarray(d["split"], bool)
    tr = ~te
    n_tr = int(tr.sum())
    out = {"n_train": n_tr, "n_test": int(te.sum()), "antrenat": False, "model": None}
    if n_tr < MIN_TRAIN_GLYPHS:
        return out
    U = d["X"].reshape(len(d["y"]), -1)  # uint8; float32 doar pe parti, cate o copie
    y_idx = np.array([clf.CLASSES.index(c) for c in d["y"]])
    Xtr = _unit(U[tr])
    P = clf.mlp_fit(Xtr, y_idx[tr], epochs=EPOCHS, log=lambda s: None)
    del Xtr
    model = workdir / f"model-{day}.npz"
    np.savez_compressed(model, **P)
    out.update(antrenat=True, model=str(model), epoci=EPOCHS)
    out["silver_test"] = _eval(clf, P, _unit(U[te]), d["y"][te], d["col"][te], d["mchar"][te],
                               d["mscore"][te], d["mmargin"][te])
    out["set_adevar"] = None
    if truth_file is not None and (run / "truth_glyphs.npz").exists():
        t = np.load(run / "truth_glyphs.npz")
        Xt = _unit(t["X"].reshape(len(t["y"]), -1))
        out["set_adevar"] = str(truth_file)
        out["scris_de_mana"] = _eval(clf, P, Xt, t["y"], t["col"], t["mchar"], t["mscore"],
                                     t["mmargin"])
    return out


def decide(stare: str, antrenare: dict, truth_file: Path | None) -> dict:
    """Decizia zilnica. In modul umbra e mereu „nu promovez"; motivul spune de ce."""
    motive = ["mod umbra: nimic nu se promoveaza automat"]
    if stare == "eroare":
        motive.append("rularea a esuat (vezi eroare)")
    if not antrenare.get("antrenat"):
        motive.append(f"date insuficiente pentru antrenare (sub {MIN_TRAIN_GLYPHS} glife)")
    tr = antrenare.get("scris_de_mana")
    if truth_file is None:
        motive.append("nu exista set de adevar scris de mana")
    elif tr and tr.get("clasificator") is not None and tr.get("motor") is not None:
        diff = tr["clasificator"] - tr["motor"]
        motive.append(f"scris de mana: clasificator {tr['clasificator']:.2%}, motor "
                      f"{tr['motor']:.2%}, diferenta {diff:+.2%}")
        motive.append("diferenta nesemnificativa" if abs(diff) < SIGNIFICANT
                      else "diferenta peste prag, dar etichetele silver nu sunt verificate")
    else:
        motive.append("setul scris de mana nu are glife evaluabile")
    motive.append("o eventuala promovare se decide manual, pe baza raportului")
    return {"promovez": False, "decizie": DECISION, "motiv": "; ".join(motive)}


def _load_clf():
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import ocr_digit_clf
    return ocr_digit_clf


def _cache_dir(clf, workdir: Path) -> Path:
    """WORKDIR/cache/<amprenta>; cache-urile altor versiuni ale motorului OCR se sterg."""
    base = workdir / CACHE
    fp = clf.engine_fingerprint()
    if base.is_dir():
        for d in base.iterdir():
            if d.name != fp:
                shutil.rmtree(d, ignore_errors=True) if d.is_dir() else d.unlink()
    return base / fp


def run(workdir, db, img_root, truth_candidates, clf=None, now=None) -> dict:
    """Ruleaza o data toate pasii si scrie report-AAAA-LL-ZZ.json in WORKDIR."""
    workdir = _check_workdir(Path(workdir))
    workdir.mkdir(parents=True, exist_ok=True)
    now = now or _now_local()
    day = now.strftime("%Y-%m-%d")
    t0 = time.monotonic()
    clf = clf or _load_clf()
    run_dir = workdir / "run"
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir()
    truth_file = _truth_file(truth_candidates)
    rep = {"data": day, "generat_la": now.isoformat(timespec="seconds"), "mod": "umbra",
           "stare": "ok", "eroare": None, "surse": None, "etichete": None,
           "antrenare": None, "set_adevar": str(truth_file) if truth_file else None,
           "set_adevar_cadre": None, "cadre": None,
           "limite": LIMITS}
    antrenare: dict = {"antrenat": False}
    try:
        rep["surse"] = export_db(Path(db), Path(img_root), workdir / "export.json",
                                 select=lambda fr: clf.select_frames(fr, MAX_FRAMES))
        rep["cadre"] = clf.extract(str(img_root), str(workdir / "export.json"), str(run_dir),
                                   max_frames=MAX_FRAMES, cache_dir=str(_cache_dir(clf, workdir)))
        rep["etichete"] = clf.label(str(run_dir), None)
        if truth_file is not None:
            clf.TRUTH = truth_file
            clf.TRUTH_IMG_DIRS = [workdir / TRUTH_IMG]
            rep["set_adevar_cadre"] = clf.truth_glyphs(str(run_dir))
        antrenare = _train_eval(clf, run_dir, workdir, day, truth_file)
        if not antrenare["antrenat"]:
            rep["stare"] = "date insuficiente"
    except Exception as e:  # raportul se scrie si la eroare; codul de iesire il spune
        rep["stare"] = "eroare"
        rep["eroare"] = f"{type(e).__name__}: {e}"
    rep["antrenare"] = antrenare
    rep["decizie"] = decide(rep["stare"], antrenare, truth_file)
    rep["numpy"] = np.__version__
    rep["durata_s"] = round(time.monotonic() - t0, 1)
    path = workdir / f"report-{day}.json"
    path.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    rep["raport"] = str(path)
    return rep


def _alarm(_signum, _frame):
    raise TimeoutError(f"limita de timp de {TIME_LIMIT_S // 60} minute depasita")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--workdir", default=str(DEFAULT_WORKDIR))
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--img-root", default=str(DEFAULT_IMG_ROOT))
    args = ap.parse_args(argv)
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(TIME_LIMIT_S)
    truth_candidates = [REPO_TRUTH, Path(args.workdir) / "truth.json"]
    rep = run(args.workdir, args.db, args.img_root, truth_candidates)
    if hasattr(signal, "SIGALRM"):
        signal.alarm(0)
    print(json.dumps({"stare": rep["stare"], "eroare": rep["eroare"],
                      "decizie": rep["decizie"]["decizie"], "raport": rep["raport"]},
                     ensure_ascii=False), flush=True)
    return 1 if rep["stare"] == "eroare" else 0


if __name__ == "__main__":
    raise SystemExit(main())
