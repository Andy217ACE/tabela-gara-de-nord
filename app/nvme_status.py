# © 2026 Andy217Ace
"""Discul NVMe al serverului, pentru pagina #admin.

Parserele citesc ieșirea text a `nvme smart-log`, `nvme error-log` și `smartctl -a`. Ele
rulează în colectorul root (scripts/nvme_collect.py), nu în aplicație. Aplicația citește
doar fișierul JSON scris de colector (`nvme.json`, lângă baza de date) și nu rulează nimic
cu privilegii. Un câmp lipsit sau nerecunoscut e absent din dict, nu 0.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

STALE_S = 900  # colectorul rulează la 1–5 min; peste 15 min datele sunt „vechi"
ERROR_LOG_KEEP = 5
SCHEMA = 1

_INT = re.compile(r"^\s*(0x[0-9a-fA-F]+|\d[\d,]*)")
_TEMP_C = re.compile(r"(\d+)\s*(?:C|Celsius)\b")
_HEALTH = re.compile(r"overall-health self-assessment test result:\s*(\S+)")
_MODEL = re.compile(r"^Model Number:\s*(.+?)\s*$", re.M)
_STATUS = re.compile(r"^(0x[0-9a-fA-F]+)\s*\(([A-Z_]+)")
_ENTRY = re.compile(r"Entry\[\s*\d+\]")


def _key(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")


def _value(key: str, raw: str):
    """Numere (cu virgule de mii, hex sau „32 C (305 Kelvin)"), altfel textul brut."""
    raw = raw.strip()
    if key == "temperature":
        m = _TEMP_C.search(raw)
        return int(m.group(1)) if m else None
    m = _INT.match(raw)
    if not m:
        return raw
    tok = m.group(1).replace(",", "")
    return int(tok, 16) if tok.lower().startswith("0x") else int(tok)


def _pairs(text: str):
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        if k.strip():
            yield k, v


def parse_smart_log(text: str) -> dict:
    """Toate câmpurile `nvme smart-log`, cu cheie normalizată (snake_case)."""
    out: dict = {}
    for k, v in _pairs(text):
        key = _key(k)
        if key.startswith("smart_log") or key.startswith("nvme_smart") or not key:
            continue  # antetul „Smart Log for NVME device:…"
        val = _value(key, v)
        if val is None or val == "":
            continue
        out["temperature_c" if key == "temperature" else key] = val
    return out


def parse_smartctl(text: str) -> dict:
    """Starea SMART globală, modelul și câmpurile din „SMART/Health Information" (serialul
    nu se păstrează)."""
    m = _HEALTH.search(text)
    mm = _MODEL.search(text)
    health: dict = {}
    in_health = False
    for line in text.splitlines():
        if line.startswith("SMART/Health Information"):
            in_health = True
            continue
        if in_health and ":" in line:
            k, _, v = line.partition(":")
            key = _key(k)
            val = _value(key, v)
            if key and val is not None and val != "":
                health[key] = val
    return {
        "overall_health": m.group(1) if m else None,
        "model": mm.group(1) if mm else None,
        "health": health,
    }


def parse_error_log(text: str) -> list[dict]:
    """Primele ERROR_LOG_KEEP intrări din `nvme error-log`, în ordinea din ieșire."""
    entries: list[dict] = []
    parts = _ENTRY.split(text)[1:]  # textul de după fiecare „Entry[ n]"
    for part in parts[:ERROR_LOG_KEEP]:
        e: dict = {}
        for k, v in _pairs(part):
            key = _key(k)
            if key == "status_field":
                sm = _STATUS.match(v.strip())
                e[key] = f"{sm.group(1)} ({sm.group(2)})" if sm else v.strip()
                continue
            val = _value(key, v)
            if key and val is not None and val != "":
                e[key] = val
        if e:
            entries.append(e)
    return entries


def read_snapshot(path, now_ts: float) -> dict:
    """Citește nvme.json scris de colector. Lipsă sau invalid -> {"available": False}.
    Întoarce doar câmpurile cunoscute, plus vârsta datelor și indicatorul „vechi"."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"available": False}
    if not isinstance(data, dict):
        return {"available": False}
    ts = data.get("collected_ts")
    age = None
    if isinstance(ts, (int, float)) and not isinstance(ts, bool):
        age = max(0, round(now_ts - ts))
    out = {
        "available": True,
        "ok": data.get("ok") is True,
        "error": data.get("error") if isinstance(data.get("error"), str) else None,
        "collected_at": data.get("collected_at") if isinstance(data.get("collected_at"), str) else None,
        "age_s": age,
        "stale": age is None or age > STALE_S,
    }
    for key in ("device", "smart_log", "smartctl", "error_log"):
        if key in data:
            out[key] = data[key]
    return out
