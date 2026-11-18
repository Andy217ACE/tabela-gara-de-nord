# © 2026 Andy217Ace
"""Alternativa OCR: clasificatorul de cifre (MLP numpy, antrenat in umbra) ca rezerva.

Nu inlocuieste cititorul (``reader.read_board_debug``). Se apeleaza DUPA el, numai pe liniile
pe care cititorul le-a lasat necitite (text pe linie, dar nicio valoare sigura de tren), si
completeaza doar celulele numerice ``no`` si ``time`` care au ramas goale. Tipul trenului,
statia si operatorul raman cele ale cititorului: o linie fara tip ramane necitita. O valoare
deja citita nu se schimba niciodata. Cand alternativa nu e sigura, linia ramane necitita.

Dezactivata implicit: ``OCR_ALT=1`` o porneste, ``OCR_ALT_MODEL`` indica fisierul ``model-*.npz``
scris de ``scripts/nightly_shadow_train.py`` (W1, b1, W2, b2; 32x32 -> 128 -> 12 clase).

Siguranta (fiecare regula taie citiri false, niciuna nu inventeaza):
- o celula se accepta doar daca TOATE glifele ei au probabilitate >= ``MIN_PROB`` si niciuna
  nu e lipita de alta (``fused``: segmentarea nu stie cate cifre are);
- ora trebuie sa fie o ora valida si sa incapa in ordinea cronologica a panoului (tabela
  listeaza trenurile dupa ora): o ora care iese din ordine se respinge;
- numarul trenului nu poate fi al altei linii din acelasi panou (``reader._duplicate``);
- rezultatul e marcat: ``entry["alt"]`` si ``fields[col]["check"] = "alt"``, randul are
  ``uncertain`` si increderea plafonata (nu poate crea singur un serviciu nou).

Bugetul propriu: ``OCR_ALT_BUDGET_S`` (4 s). OcrError nu declanseaza alternativa: o apeleaza
doar codul care a primit liniile de la cititor (vezi docs/superpowers/plans/
2026-11-17-ocr-alt-integrare.md).
"""
from __future__ import annotations

import copy
import hashlib
import logging
import os
import threading
import time
from pathlib import Path

import numpy as np

from app import canonical
from app.models import Row
from app.normalize import clean_station, parse_time, strip_flag
from app.ocr import digits, order, preprocess

log = logging.getLogger(__name__)

CLASSES = "0123456789+:"
ALLOWED = {"no": "0123456789", "time": "0123456789:"}
ALT_COLS = ("no", "time")  # coloanele numerice pe care le poate completa alternativa
MIN_PROB = 0.99            # probabilitatea minima a FIECAREI glife dintr-o celula acceptata
MAX_NO_DIGITS = 5
MAX_UNREAD = 4             # ca reader.MAX_RETRY_LINES: peste, panoul e stricat, nu se atinge
MIN_UNREAD = 1             # linii necitite pe panou de la care alternativa se declanseaza
BUDGET_S = 4.0
ALT_MARK = "alt"
ALT_CONFIDENCE = order.REPAIRED_CONFIDENCE  # plafon: sub pragul unui serviciu nou sigur


# --- configurare (env; fara a atinge app/config.py) -----------------------------------------
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def enabled() -> bool:
    """Alternativa e pornita doar explicit (OCR_ALT=1)."""
    return os.environ.get("OCR_ALT", "").strip().lower() in ("1", "true", "yes", "on")


def budget_s() -> float:
    return max(0.0, _env_float("OCR_ALT_BUDGET_S", BUDGET_S))


def min_unread() -> int:
    return max(1, _env_int("OCR_ALT_MIN_UNREAD", MIN_UNREAD))


def max_unread() -> int:
    return max(0, _env_int("OCR_ALT_MAX_UNREAD", MAX_UNREAD))


# --- model ----------------------------------------------------------------------------------
def engine_fingerprint() -> str:
    """Amprenta motorului OCR de productie (fisierele app/ocr, fara acest modul)."""
    here = Path(__file__).resolve()
    h = hashlib.sha256()
    for f in sorted(here.parent.rglob("*")):
        if f.is_file() and f.suffix in (".py", ".npz", ".json") and f != here:
            h.update(f.name.encode("utf-8"))
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


class AltModel:
    """MLP 1024 -> 128 (ReLU) -> 12; doar greutati, inferenta numpy (microsecunde pe glifa)."""

    def __init__(self, W1, b1, W2, b2):
        self.W1, self.b1 = np.asarray(W1, np.float32), np.asarray(b1, np.float32)
        self.W2, self.b2 = np.asarray(W2, np.float32), np.asarray(b2, np.float32)
        if (self.W1.shape[0] != digits.GLYPH_H * digits.GLYPH_W
                or self.W2.shape[1] != len(CLASSES)
                or self.W1.shape[1] != self.W2.shape[0]):
            raise ValueError("forma greutatilor nu e cea a clasificatorului de cifre")

    @classmethod
    def load(cls, path: Path | str) -> "AltModel":
        """Citeste ``model-*.npz``. Daca fisierul poarta ``engine_fp`` (amprenta motorului la
        antrenare) si ea nu se potriveste cu motorul curent, modelul e invechit: ValueError."""
        with np.load(path) as d:
            if "engine_fp" in d.files and str(d["engine_fp"]) != engine_fingerprint():
                raise ValueError("modelul a fost antrenat pe alt motor OCR (amprenta difera)")
            return cls(d["W1"], d["b1"], d["W2"], d["b2"])

    def proba(self, glyphs: list[np.ndarray], allowed: str) -> np.ndarray:
        """(n, 12) probabilitati softmax, mascate la caracterele permise (restul 0)."""
        x = np.stack([_quant(g).reshape(-1) for g in glyphs]).astype(np.float32)
        z = np.maximum(x @ self.W1 + self.b1, 0) @ self.W2 + self.b2
        keep = np.array([c in allowed for c in CLASSES])
        z = np.where(keep, z, -np.inf)
        z = z - z.max(axis=1, keepdims=True)
        e = np.exp(z)
        return e / e.sum(axis=1, keepdims=True)


def _quant(g: np.ndarray) -> np.ndarray:
    """Glifa asa cum a vazut-o antrenarea: 8 biti, inapoi in 0..1 (ocr_digit_clf._quant)."""
    return (np.clip(g, 0, 1) * 255).round().astype(np.float32) / 255.0


_model_lock = threading.Lock()
_model_cache: dict[str, AltModel | None] = {}


def get_model() -> AltModel | None:
    """Modelul din OCR_ALT_MODEL, incarcat o data; None (alternativa oprita) daca lipseste,
    e stricat sau invechit."""
    path = os.environ.get("OCR_ALT_MODEL", "")
    if not path:
        return None
    with _model_lock:
        if path not in _model_cache:
            try:
                _model_cache[path] = AltModel.load(path)
            except (OSError, KeyError, ValueError) as e:
                log.warning("OCR alt: model indisponibil (%s: %s); alternativa oprita",
                            type(e).__name__, e)
                _model_cache[path] = None
        return _model_cache[path]


# --- citirea unei celule --------------------------------------------------------------------
def _time_text(text: str) -> str | None:
    """Ora din textul citit; colonul subtire poate lipsi din segmentare (3-4 cifre)."""
    if text.isdigit() and len(text) in (3, 4):
        text = f"{text[:-2]}:{text[-2:]}"
    return parse_time(text)


def read_cell(model: AltModel, cell: np.ndarray, col: str,
              min_prob: float = MIN_PROB) -> tuple[str, float] | None:
    """(text normalizat, cea mai slaba probabilitate) al unei celule ``no`` / ``time``, sau
    None cand celula nu se poate citi sigur (goala, glife lipite, probabilitate mica, format
    invalid)."""
    try:
        spans = digits.segment_spans(cell)
    except ValueError:
        return None
    if not spans or any(fused for _, _, fused in spans):
        return None
    p = model.proba([g for g, _, _ in spans], ALLOWED[col])
    best = p.argmax(axis=1)
    worst = float(p[np.arange(len(best)), best].min())
    if worst < min_prob:
        return None
    text = "".join(CLASSES[k] for k in best)
    if col == "time":
        t = _time_text(text)
        return (t, worst) if t else None
    if not text.isdigit() or len(text) > MAX_NO_DIGITS or int(text) == 0:
        return None
    return str(int(text)), worst


# --- declansare si aplicare pe un cadru -----------------------------------------------------
def _complete(entry: dict) -> bool:
    r = entry["row"]
    return r is not None and bool(r.train_no)


def unread_lines(entries: list[dict]) -> dict[str, list[int]]:
    """{panou: indexuri in entries} ale liniilor cu text dar fara tren complet."""
    out: dict[str, list[int]] = {}
    for i, e in enumerate(entries):
        if e["state"] != "empty" and not _complete(e):
            out.setdefault(e["board"], []).append(i)
    return out


def eligible(entries: list[dict], lo: int | None = None, hi: int | None = None) -> list[int]:
    """Liniile pe care alternativa are voie sa le incerce: din panourile cu cel putin ``lo``
    si cel mult ``hi`` linii necitite (peste ``hi`` cadrul e stricat la sursa: nu se
    inventeaza), si doar cele al caror tip a fost citit (tipul nu il poate citi MLP-ul) si
    carora le lipseste cel putin o coloana numerica."""
    lo = min_unread() if lo is None else lo
    hi = max_unread() if hi is None else hi
    out = []
    for board, idx in unread_lines(entries).items():
        if not lo <= len(idx) <= hi:
            continue
        for i in idx:
            f = entries[i]["fields"]
            if f["type"]["norm"] is None:
                continue
            if any(f[c]["norm"] is None for c in ALT_COLS):
                out.append(i)
    return sorted(out)


def _panels(image_bytes: bytes):
    from app.ocr import reader
    img = reader._decode(image_bytes)
    return {board: reader._Panel(half) for board, (half, _) in zip(
        reader.BOARDS, preprocess.split_boards_offsets(img))}


def _build_row(entry: dict, no: int, sched: str):
    """Randul liniei cu numarul/ora completate; restul vine din citirea cititorului."""
    f = entry["fields"]
    type_text, flagged = strip_flag(f["type"]["raw"])
    delay = f["delay"]["norm"]
    old = entry["row"]
    return Row(
        board=entry["board"], train_type=f["type"]["norm"], train_no=no,
        station=f["station"]["norm"] or "", operator=f["operator"]["norm"] or "",
        sched_time=sched, delay_min=delay if delay is not None else 0,
        delay_read=delay is not None, platform=f["platform"]["norm"],
        flagged=flagged if old is None else old.flagged,
        confidence=min(entry["conf"], ALT_CONFIDENCE), uncertain=True,
        operator_raw=canonical.clean_operator(f["operator"]["raw"]),
        station_raw=clean_station(f["station"]["raw"]))


def _fits_order(entries: list[dict], i: int, sched: str) -> bool:
    """Ora ``sched`` a liniei ``i`` incape in ordinea cronologica a panoului."""
    board = entries[i]["board"]
    line = sorted((k for k, e in enumerate(entries)
                   if e["board"] == board and (e["row"] is not None or k == i)),
                  key=lambda k: entries[k]["row_index"])
    times = [sched if k == i else entries[k]["row"].sched_time for k in line]
    return line.index(i) not in order.out_of_order(times)


def _duplicate(no: int, entries: list[dict], i: int) -> bool:
    b = entries[i]["board"]
    return any(k != i and e["board"] == b and e["row"] is not None and e["row"].train_no == no
               for k, e in enumerate(entries))


def recover(image_bytes: bytes, entries: list[dict], model: AltModel, *,
            budget: float | None = None, lines: list[int] | None = None,
            min_prob: float = MIN_PROB) -> dict:
    """Completeaza IN LOC liniile necitite din ``entries`` (debug-ul cititorului).

    Intoarce {"tried", "recovered", "lines": [indexuri], "secs", "reason"}. ``lines``
    (indexuri) ocoleste declansarea; implicit se iau ``eligible(entries)``. Nu atinge
    celulele citite, nici liniile cu stare ``ok`` si numar. Un cadru fara linii eligibile nu
    costa nimic (nu se decodeaza imaginea)."""
    t0 = time.perf_counter()
    budget = budget_s() if budget is None else budget
    todo = eligible(entries) if lines is None else list(lines)
    info = {"tried": 0, "recovered": 0, "lines": [], "secs": 0.0,
            "reason": "no_eligible_lines" if not todo else "ok"}
    if not todo:
        return info
    panels = _panels(image_bytes)
    for i in todo:
        if time.perf_counter() - t0 > budget:
            info["reason"] = "budget"
            break
        e = entries[i]
        panel = panels.get(e["board"])
        if panel is None or e["row_index"] >= len(panel):
            continue
        info["tried"] += 1
        cells = panel.cells(e["row_index"])
        f = e["fields"]
        missing = [c for c in ALT_COLS if f[c]["norm"] is None]  # citite de cititor: neatinse
        got = {c: read_cell(model, cells[c], c, min_prob) for c in missing}
        if not missing or any(r is None for r in got.values()):
            continue  # o celula lipsa ramasa necitita: linia ramane necitita
        no = int(got["no"][0]) if "no" in got else int(f["no"]["norm"])
        sched = got["time"][0] if "time" in got else f["time"]["norm"]
        if sched is None or not no:
            continue
        if _duplicate(no, entries, i) or not _fits_order(entries, i, sched):
            continue
        e["row"] = _build_row(e, no, sched)
        for col, (text, prob) in got.items():
            f[col].update(raw=text, norm=int(text) if col == "no" else text,
                          conf=round(prob * 100, 1), check=ALT_MARK)
        e["state"] = "ok"
        e[ALT_MARK] = {"cols": sorted(got), "prob": round(min(p for _, p in got.values()), 4)}
        info["recovered"] += 1
        info["lines"].append(i)
    info["secs"] = time.perf_counter() - t0
    return info


def shadow() -> bool:
    """OCR_ALT_SHADOW=1: alternativa ruleaza si scrie in jurnal ce ar fi completat, dar nu
    schimba nimic (faza de 7 zile in umbra din specificatie)."""
    return os.environ.get("OCR_ALT_SHADOW", "").strip().lower() in ("1", "true", "yes", "on")


shadow_log = logging.getLogger("app.ocr.alt_shadow")


def apply(image_bytes: bytes, entries: list[dict], model: AltModel | None = None) -> dict:
    """Punctul de intrare pentru poller: no-op daca alternativa e oprita sau fara model.
    Modifica ``entries`` in loc (doar la reusita; la eroare raman neatinse); randurile noi =
    ``[e["row"] for e in entries if e["row"]]``. In mod umbra (``OCR_ALT_SHADOW``) calculeaza
    pe o copie, scrie in jurnal ``app.ocr.alt_shadow`` si lasa ``entries`` neatinse."""
    info = {"tried": 0, "recovered": 0, "lines": [], "secs": 0.0}
    if not enabled():
        return info | {"reason": "disabled"}
    model = model or get_model()
    if model is None:
        return info | {"reason": "no_model"}
    work = copy.deepcopy(entries)
    try:
        info = recover(image_bytes, work, model)
    except Exception:  # optional: cadrul ramane asa cum l-a lasat cititorul
        log.warning("OCR alt a esuat; cadrul ramane cum l-a citit cititorul", exc_info=True)
        return info | {"reason": "error"}
    if shadow():
        for i in info["lines"]:
            e = work[i]
            shadow_log.info("alt-shadow %s linia %d: %s", e["board"], e["row_index"],
                            {c: e["fields"][c]["norm"] for c in e["alt"]["cols"]}
                            | {"prob": e["alt"]["prob"]})
        return info | {"shadow": True}
    entries[:] = work
    return info


__all__ = ["AltModel", "apply", "recover", "eligible", "read_cell", "enabled", "get_model",
           "shadow"]
