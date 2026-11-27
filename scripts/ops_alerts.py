# © 2026 Andy217Ace
"""Alerte de operare pe Telegram (pornit de tabela-ops-alerts.timer la 5 minute).

Verifică: /api/health local și public (panouri vechi, calitatea OCR), discul,
colectorul Infofer (dacă timer-ul lui e activ) și unitățile tabela-* căzute (failed).
O problemă se anunță după FAIL_RUNS rulări la rând, apoi cel mult o dată la COOLDOWN_S
(sau imediat dacă se agravează); la revenire se trimite „rezolvat”. Starea stă în
OPS_STATE_PATH (JSON mic). Trimiterea refolosește app.telegram (același bot/chat ca
alertele de trenuri); fără TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID scriptul doar notează
în jurnal și iese cu 0.

Uz: python scripts/ops_alerts.py [--state PATH] [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LOCAL_URL = "http://127.0.0.1:8000/api/health"
PUBLIC_URL = "https://tabelacfr.ddns.net/api/health"
DISKS = ("/", "/var/lib/tabela", "/var/lib/tabela/captures")
INFOFER_DB = "/var/lib/tabela/infofer.db"
STATE_PATH = "/var/lib/tabela/ops_alerts.json"
DISK_WARN, DISK_CRIT = 85.0, 95.0
INFOFER_MAX_AGE_S = 15 * 60
OCR_MIN_FRAMES = 10        # fereastra OCR are ~60 cadre (o oră); sub 10 nu judecăm
OCR_MIN_FULL = 0.5         # sub jumătate din cadre complete (toate rândurile) = OCR degradat
FAIL_RUNS = 2              # o singură rulare proastă (ex. repornire la deploy) nu alertează
COOLDOWN_S = 3 * 3600
HTTP_TIMEOUT = 20
LEVELS = {"ok": 0, "warn": 1, "crit": 2}


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as r:  # noqa: S310 (URL fix)
        return json.loads(r.read().decode("utf-8"))


def check_health(name: str, url: str, fetch=_get_json) -> list[tuple]:
    """(key, level, mesaj) pentru o adresă /api/health; panourile și OCR doar pentru cea locală."""
    try:
        h = fetch(url)
    except Exception as e:  # noqa: BLE001 - orice eșec de rețea/parsare = site căzut
        return [(f"health:{name}", "crit", f"{url} nu răspunde ({type(e).__name__})")]
    out = [(f"health:{name}", "ok", f"{url} răspunde")]
    if name != "local":
        return out
    stale = [k for k, b in (h.get("boards") or {}).items() if b.get("stale")]
    if h.get("ok") is False or stale:
        out.append(("boards", "warn", f"panouri vechi: {', '.join(stale) or 'toate'}"
                                      f" (ultima citire acum {h.get('age_s')} s)"))
    else:
        out.append(("boards", "ok", "panourile se citesc"))
    win = ((h.get("ocr") or {}).get("window") or {})
    n, full = win.get("frames") or 0, win.get("full_frames") or 0
    if n >= OCR_MIN_FRAMES and full / n < OCR_MIN_FULL:
        out.append(("ocr", "warn", f"OCR degradat: {full}/{n} cadre complete în ultima oră"))
    else:
        out.append(("ocr", "ok", "OCR normal"))
    return out


def check_disks(paths=DISKS, usage=shutil.disk_usage) -> list[tuple]:
    out, seen = [], set()
    for p in paths:
        try:
            dev = os.stat(p).st_dev
            u = usage(p)
        except OSError:
            continue  # calea lipsește pe acest server
        if dev in seen:
            continue  # același sistem de fișiere ca o cale deja verificată
        seen.add(dev)
        pct = 100.0 * u.used / u.total if u.total else 0.0
        level = "crit" if pct > DISK_CRIT else "warn" if pct > DISK_WARN else "ok"
        out.append((f"disk:{p}", level, f"disc {p} la {pct:.0f}%"))
    return out


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=30)


def check_infofer(now: float, db=INFOFER_DB, run=_systemctl) -> list[tuple]:
    if run("is-active", "--quiet", "tabela-infofer.timer").returncode != 0:
        return [("infofer", "ok", "colectorul Infofer nu e activ")]
    last = None
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
            row = c.execute("SELECT MAX(fetched_at) FROM infofer_runs WHERE n_markers > 0").fetchone()
        if row and row[0]:
            last = datetime.fromisoformat(row[0]).timestamp()
    except (sqlite3.Error, ValueError):
        pass
    if last is None or now - last > INFOFER_MAX_AGE_S:
        ago = "niciodată" if last is None else f"acum {int((now - last) // 60)} min"
        return [("infofer", "warn", f"colectorul Infofer: ultima rulare reușită {ago}")]
    return [("infofer", "ok", "colectorul Infofer merge")]


def check_units(run=_systemctl) -> list[tuple]:
    r = run("list-units", "--failed", "--plain", "--no-legend", "tabela*")
    failed = sorted(line.split()[0] for line in r.stdout.splitlines() if line.strip())
    if failed:
        return [("units", "crit", f"unități căzute: {', '.join(failed)}")]
    return [("units", "ok", "nicio unitate tabela-* căzută")]


def evaluate(results: list[tuple], state: dict, now: float) -> list[str]:
    """Actualizează `state` și întoarce mesajele de trimis (dedup + cooldown + „rezolvat”)."""
    msgs = []
    for key, level, text in results:
        s = state.get(key) or {"fails": 0, "level": "ok", "sent_at": None}
        if level == "ok":
            if s["sent_at"] is not None:
                msgs.append(f"[REZOLVAT] {text}")
            state.pop(key, None)
            continue
        s["fails"] += 1
        worse = LEVELS[level] > LEVELS[s["level"]]
        due = s["sent_at"] is None or now - s["sent_at"] >= COOLDOWN_S
        if s["fails"] >= FAIL_RUNS and (due or (worse and s["sent_at"] is not None)):
            msgs.append(f"[{'CRITIC' if level == 'crit' else 'ATENȚIE'}] {text}")
            s["sent_at"], s["level"] = now, level
        state[key] = s
    return msgs


def load_state(path: str) -> dict:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: str, state: dict) -> None:
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state), encoding="utf-8")
    os.replace(tmp, p)


def send_telegram(cfg, text: str) -> None:
    from app.telegram import TelegramChannel  # același canal ca alertele de trenuri
    asyncio.run(TelegramChannel(cfg).send(None, {"body": text}))


def run_checks(now: float) -> list[tuple]:
    results = check_health("local", LOCAL_URL)
    public = os.environ.get("OPS_PUBLIC_URL", PUBLIC_URL).strip()
    if public:  # OPS_PUBLIC_URL= (gol) oprește verificarea publică (ex. router fără NAT loopback)
        results += check_health("public", public)
    return results + check_disks() + check_infofer(now) + check_units()


def main(argv=None, *, checks=run_checks, sender=send_telegram, clock=time.time) -> int:
    ap = argparse.ArgumentParser(description="Alerte de operare pe Telegram")
    ap.add_argument("--state", default=os.environ.get("OPS_STATE_PATH", STATE_PATH))
    ap.add_argument("--dry-run", action="store_true", help="afișează mesajele, nu trimite")
    a = ap.parse_args(argv)
    from app.telegram import config_from_env
    cfg = config_from_env()
    if cfg is None and not a.dry_run:
        print("ops_alerts: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID nesetate; nimic de făcut")
        return 0
    now = clock()
    state = load_state(a.state)
    msgs = evaluate(checks(now), state, now)
    for m in msgs:
        print(f"ops_alerts: {m}")
        if not a.dry_run:
            sender(cfg, m)
    if not a.dry_run:
        save_state(a.state, state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
