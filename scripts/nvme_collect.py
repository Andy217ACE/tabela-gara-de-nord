# © 2026 Andy217Ace
"""Colectorul discului NVMe: citește (doar citire) smart-log, error-log și smartctl -a și
scrie un JSON atomic, pe care aplicația îl afișează în #admin.

Rulează ca root dintr-un timer systemd (vezi deploy/tabela-nvme.timer). Nu primește
argumente din exterior: comenzile sunt fixe, fără shell. Nu rulează nimic care scrie pe
disc sau resetează contoare (format, smartctl -t, set-feature, self-test, sanitize…).

Uz: python3 scripts/nvme_collect.py [/var/lib/tabela/nvme.json]
Ieșire: 0 dacă fișierul a fost scris (chiar și cu erori parțiale, marcate în el), 1 altfel.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import nvme_status  # noqa: E402

DEVICE = "/dev/nvme0"
DEFAULT_OUT = "/var/lib/tabela/nvme.json"
OWNER_USER = "tabela"
CMD_TIMEOUT_S = 20
TZ = ZoneInfo("Europe/Bucharest")

ARGV = {
    "smart_log": ["nvme", "smart-log", DEVICE],
    "error_log": ["nvme", "error-log", DEVICE, f"--log-entries={nvme_status.ERROR_LOG_KEEP}"],
    "smartctl": ["smartctl", "-a", DEVICE],
}
KIND_BY_ARGV = {tuple(v): k for k, v in ARGV.items()}
_run = subprocess.run


def _cmd(run, kind: str) -> str | None:
    """Ieșirea comenzii (stdout) sau None dacă lipsește, eșuează sau e goală."""
    try:
        p = run(list(ARGV[kind]), capture_output=True, text=True, timeout=CMD_TIMEOUT_S,
                shell=False, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    out = p.stdout or ""
    return out if out.strip() else None


def collect(runner=None, now: float | None = None) -> dict:
    """Snapshot-ul complet. O sursă care lipsește e None în JSON (nu 0) și apare în `error`."""
    run = runner or _run
    ts = time.time() if now is None else now
    errors: list[str] = []

    smart = nvme_status.parse_smart_log(_cmd(run, "smart_log") or "") or None
    if smart is None:
        errors.append("smart_log")

    sc_text = _cmd(run, "smartctl")
    sc = nvme_status.parse_smartctl(sc_text) if sc_text else {}
    if not sc.get("overall_health") and not sc.get("health"):
        errors.append("smartctl")
        sc = None

    el_text = _cmd(run, "error_log")
    el = nvme_status.parse_error_log(el_text) if el_text else None
    if el is None:
        errors.append("error_log")

    return {
        "schema": nvme_status.SCHEMA,
        "collected_ts": ts,
        "collected_at": datetime.fromtimestamp(ts, TZ).isoformat(timespec="seconds"),
        "ok": not errors,
        "error": errors[0] if errors else None,
        "device": {"model": sc.get("model") if sc else None},
        "smart_log": smart,
        "smartctl": {"overall_health": sc["overall_health"], "health": sc["health"]} if sc else None,
        "error_log": el or [],
    }


def _owner(user: str):
    """(uid, gid) al userului, sau None dacă nu există (Windows, teste)."""
    try:
        import pwd
        pw = pwd.getpwnam(user)
    except (ImportError, KeyError):
        return None
    return pw.pw_uid, pw.pw_gid


def write_atomic(path, data: dict, owner=None) -> None:
    """Scrie în fișierul temporar de lângă țintă, apoi os.replace. Mod 0640; proprietar
    `owner` (uid, gid) dacă e dat. Nu lasă fișiere temporare la succes."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o640)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    if owner and hasattr(os, "chown"):
        os.chown(tmp, *owner)
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv else Path(DEFAULT_OUT)
    try:
        write_atomic(out, collect(), owner=_owner(OWNER_USER))
    except OSError:
        print("nvme_collect: scrierea a eșuat", file=sys.stderr)  # fără traceback, fără căi
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
