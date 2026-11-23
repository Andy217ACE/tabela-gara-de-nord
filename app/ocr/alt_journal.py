# © 2026 Andy217Ace
"""Jurnalul alternativei OCR (pagina admin #ocr2): un eveniment per rand propus (si in umbra,
si cand alternativa e activa), decupajul celulelor (PNG x3), verdicte, retentie.

Director: ``<dirname(DB_PATH)>/ocr_alt/`` (``OCR_ALT_JOURNAL_DIR`` il schimba). ``record`` nu
arunca niciodata: o eroare se logheaza si poller-ul merge mai departe."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

KEEP_DAYS = 30
MAX_EVENTS = 5000
PRUNE_EVERY_S = 3600
SCALE = 3
VERDICTS = ("correct", "wrong", "unclear")
ID_RE = re.compile(r"^\d{8}T\d{6}-(arrival|departure)-\d{1,3}$")
COL_RE = re.compile(r"^(no|time)$")

_lock = threading.RLock()
_last_prune = 0.0


def journal_dir() -> Path:
    d = os.environ.get("OCR_ALT_JOURNAL_DIR")
    if d:
        return Path(d)
    return Path(os.path.dirname(os.environ.get("DB_PATH", "tabela.db"))) / "ocr_alt"


def _events() -> list[dict]:
    try:
        text = (journal_dir() / "events.jsonl").read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    out = []
    for line in text.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # linie rupta (cadere in timpul scrierii): se sare
    return out


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _verdicts() -> dict:
    try:
        return json.loads((journal_dir() / "verdicts.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _png(cell: np.ndarray) -> bytes:
    a = np.asarray(cell)
    if a.dtype == bool:
        a = a.astype(np.uint8) * 255
    a = cv2.resize(a.astype(np.uint8), None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".png", a)
    if not ok:
        raise ValueError("png encode")
    return buf.tobytes()


def _context(entry: dict) -> dict:
    f = entry["fields"]
    return {k: f[k]["norm"] for k in ("type", "station", "operator", "platform", "delay")}


def record(work: list[dict], info: dict, cells: dict, shadow: bool,
           now: datetime | None = None) -> None:
    """Scrie evenimentele liniilor recuperate (``info["lines"]``); ``cells`` = {linie: {col: celula}}."""
    try:
        now = now or datetime.now(timezone.utc)
        d = journal_dir()
        with _lock:
            (d / "crops").mkdir(parents=True, exist_ok=True)
            lines = []
            for i in info.get("lines", []):
                e = work[i]
                cols = list(e["alt"]["cols"])
                eid = f"{now:%Y%m%dT%H%M%S}-{e['board']}-{e['row_index']}"
                for c in cols:
                    (d / "crops" / f"{eid}_{c}.png").write_bytes(_png(cells[i][c]))
                lines.append(json.dumps({
                    "id": eid, "ts": now.isoformat(timespec="seconds"), "shadow": bool(shadow),
                    "board": e["board"], "row_index": e["row_index"], "cols": cols,
                    "values": {c: e["fields"][c]["norm"] for c in cols}, "prob": e["alt"]["prob"],
                    "context": _context(e)}, ensure_ascii=False))
            if lines:
                with open(d / "events.jsonl", "a", encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + "\n")
            prune(now)
    except Exception:
        log.warning("jurnalul alternativei OCR a esuat; poller-ul merge mai departe", exc_info=True)


def prune(now: datetime | None = None, force: bool = False) -> None:
    """Retentie: 30 de zile si maxim 5000 de evenimente; cel mult o data pe ora."""
    global _last_prune
    with _lock:
        if not force and _last_prune and time.monotonic() - _last_prune < PRUNE_EVERY_S:
            return
        _last_prune = time.monotonic()
        now = now or datetime.now(timezone.utc)
        evs = _events()
        cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
        keep = [e for e in evs if e["ts"] >= cutoff][-MAX_EVENTS:]
        if len(keep) == len(evs):
            return
        d = journal_dir()
        _write_atomic(d / "events.jsonl",
                      "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in keep))
        kept = {e["id"] for e in keep}
        for e in evs:
            if e["id"] not in kept:
                for c in e["cols"]:
                    (d / "crops" / f"{e['id']}_{c}.png").unlink(missing_ok=True)
        v = _verdicts()
        if any(k not in kept for k in v):
            _write_atomic(d / "verdicts.json", json.dumps({k: x for k, x in v.items() if k in kept}))


def list_events(limit: int = 50, before: str | None = None,
                only: str = "all") -> tuple[list[dict], str | None]:
    """Cele mai noi primele; ``before`` = id dupa care continua; ``next`` = ultimul id al paginii
    daca mai exista."""
    with _lock:
        evs, v = _events()[::-1], _verdicts()
    if before:
        ids = [e["id"] for e in evs]
        evs = evs[ids.index(before) + 1:] if before in ids else evs
    out = []
    for e in evs:
        e["verdict"] = (v.get(e["id"]) or {}).get("verdict")
        if only == "unverified" and e["verdict"]:
            continue
        out.append(e)
    page = out[:limit]
    return page, (page[-1]["id"] if len(out) > limit else None)


def totals() -> dict:
    with _lock:
        evs, v = _events(), _verdicts()
    c = {k: 0 for k in VERDICTS}
    for e in evs:
        x = (v.get(e["id"]) or {}).get("verdict")
        if x in c:
            c[x] += 1
    n = c["correct"] + c["wrong"]
    return {"events": len(evs), "verified": sum(c.values()), **c,
            "precision": round(c["correct"] / n, 4) if n else None, "n_precision": n}


def set_verdict(eid: str, verdict: str | None) -> bool:
    """Seteaza/sterge verdictul; False daca evenimentul nu exista."""
    with _lock:
        if not any(e["id"] == eid for e in _events()):
            return False
        v = _verdicts()
        if verdict is None:
            v.pop(eid, None)
        else:
            v[eid] = {"verdict": verdict,
                      "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _write_atomic(journal_dir() / "verdicts.json", json.dumps(v))
        return True


def crop_path(eid: str, col: str) -> Path | None:
    if not (ID_RE.match(eid) and COL_RE.match(col)):
        return None
    p = journal_dir() / "crops" / f"{eid}_{col}.png"
    return p if p.is_file() else None
