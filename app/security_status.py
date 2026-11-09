# © 2026 Andy217Ace
"""Cardul „Securitate" din #admin: citește snapshot.json scris de exportatorul root
(scripts/security_snapshot.py, timer la 2 min) din `<dir baza>/security/`.

Aplicația nu rulează nimic cu privilegii și nu atinge fail2ban sau log-urile. Datele vin din
trafic ostil (IP-uri, căi probate): aici se reconstruiește doar structura cunoscută, cu
tipuri verificate și liste/șiruri limitate; UI-ul le afișează doar ca text. O valoare lipsă
sau de tip greșit devine None (afișată „—"), nu 0.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

SCHEMA = 1
STALE_S = 600          # exportatorul rulează la 2 min; peste 10 min datele sunt „vechi"
MAX_BANNED = 1000
MAX_HISTORY = 200
MAX_IPS = 500
MAX_TOP = 20
MAX_JAILS = 20
TOP_PATHS = 5
MAX_PATH_LEN = 200
MAX_IP_LEN = 64
MAX_NAME_LEN = 64
MAX_TIME_LEN = 40
MAX_FILE_BYTES = 8 * 1024 * 1024
EVENTS = {"ban", "unban", "restore"}
ERRORS = {"fail2ban_db", "fail2ban_log", "access_log"}
TOTALS = ("banned_now", "bans_24h", "bans_7d", "probes_24h", "probe_ips_24h", "requests_24h",
          "probes_7d", "requests_7d")

_cache: dict = {"key": None, "data": None}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache["key"] = None
        _cache["data"] = None


def _s(v, n: int) -> str | None:
    return v[:n] if isinstance(v, str) else None


def _i(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def _b(v) -> bool | None:
    return v if isinstance(v, bool) else None


def _list(v, n: int) -> list:
    return v[:n] if isinstance(v, list) else []


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _window(w) -> dict:
    w = _dict(w)
    return {"requests": _i(w.get("requests")), "probes": _i(w.get("probes")),
            "first_seen": _s(w.get("first_seen"), MAX_TIME_LEN),
            "last_seen": _s(w.get("last_seen"), MAX_TIME_LEN),
            "paths": [{"path": _s(p.get("path"), MAX_PATH_LEN), "count": _i(p.get("count"))}
                      for p in _list(w.get("paths"), TOP_PATHS) if isinstance(p, dict)]}


def sanitize(data: dict) -> dict:
    """Doar câmpurile cunoscute, cu tipuri verificate și dimensiuni limitate."""
    f2 = _dict(data.get("fail2ban"))
    acc = _dict(data.get("access_log"))
    totals = _dict(data.get("totals"))
    ips = {}
    for ip, v in list(_dict(data.get("ips")).items())[:MAX_IPS]:
        if isinstance(ip, str) and isinstance(v, dict):
            ips[ip[:MAX_IP_LEN]] = {"24h": _window(v.get("24h")), "7d": _window(v.get("7d"))}
    return {
        "generated_at": _s(data.get("generated_at"), MAX_TIME_LEN),
        "errors": [e for e in _list(data.get("errors"), 10) if e in ERRORS],
        "probe_rule": data.get("probe_rule") if data.get("probe_rule") in ("filter", "builtin") else None,
        "duration_ms": _i(data.get("duration_ms")),
        "ips_truncated": _b(data.get("ips_truncated")),
        "banned_truncated": _b(data.get("banned_truncated")),
        "fail2ban": {
            "available": f2.get("available") is True,
            "log_available": _b(f2.get("log_available")),
            "jails": [{"name": _s(j.get("name"), MAX_NAME_LEN), "banned_now": _i(j.get("banned_now"))}
                      for j in _list(f2.get("jails"), MAX_JAILS) if isinstance(j, dict)],
        },
        "totals": {k: _i(totals.get(k)) for k in TOTALS},
        "banned": [{"ip": _s(b.get("ip"), MAX_IP_LEN), "jail": _s(b.get("jail"), MAX_NAME_LEN),
                    "banned_at": _s(b.get("banned_at"), MAX_TIME_LEN),
                    "expires_at": _s(b.get("expires_at"), MAX_TIME_LEN),
                    "permanent": _b(b.get("permanent")), "bancount": _i(b.get("bancount"))}
                   for b in _list(data.get("banned"), MAX_BANNED) if isinstance(b, dict)],
        "history": [{"at": _s(h.get("at"), MAX_TIME_LEN),
                     "event": h.get("event") if h.get("event") in EVENTS else None,
                     "jail": _s(h.get("jail"), MAX_NAME_LEN), "ip": _s(h.get("ip"), MAX_IP_LEN)}
                    for h in _list(data.get("history"), MAX_HISTORY) if isinstance(h, dict)],
        "ips": ips,
        "top": [{"ip": _s(t.get("ip"), MAX_IP_LEN), "probes_24h": _i(t.get("probes_24h")),
                 "probes_7d": _i(t.get("probes_7d")), "requests_7d": _i(t.get("requests_7d")),
                 "last_seen": _s(t.get("last_seen"), MAX_TIME_LEN), "banned": _b(t.get("banned"))}
                for t in _list(data.get("top"), MAX_TOP) if isinstance(t, dict)],
        "access_log": {"available": acc.get("available") is True, "files": _i(acc.get("files")),
                       "lines": _i(acc.get("lines")), "parse_errors": _i(acc.get("parse_errors")),
                       "truncated": _b(acc.get("truncated")),
                       "ips_capped": _b(acc.get("ips_capped"))},
    }


def _load(path: Path):
    """(generated_ts, date sanitizate) sau un șir cu motivul („missing" / „invalid").
    Rezultatul se ține în cache cât timp fișierul (mtime, dimensiune) nu se schimbă."""
    try:
        st = path.stat()
    except OSError:
        return "missing"
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache["key"] == key:
            return _cache["data"]
    if st.st_size > MAX_FILE_BYTES:
        out = "invalid"
    else:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return "missing"
        except (OSError, ValueError):
            raw = None
        ts = raw.get("generated_ts") if isinstance(raw, dict) else None
        if (not isinstance(raw, dict) or raw.get("schema") != SCHEMA
                or not isinstance(ts, (int, float)) or isinstance(ts, bool)):
            out = "invalid"
        else:
            out = (float(ts), sanitize(raw))
    with _lock:
        _cache["key"] = key
        _cache["data"] = out
    return out


def read_snapshot(path, now_ts: float) -> dict:
    """{"available": True, "age_s", "stale": False, ...} sau {"available": False, "reason":
    "missing" | "invalid" | "stale"} (cu vârsta și momentul generării pentru „stale")."""
    got = _load(Path(path))
    if isinstance(got, str):
        return {"available": False, "reason": got}
    ts, data = got
    age = max(0, round(now_ts - ts))
    if age > STALE_S:
        return {"available": False, "reason": "stale", "stale": True, "age_s": age,
                "generated_at": data["generated_at"]}
    return {"available": True, "stale": False, "age_s": age, **data}


def snapshot_path(db_path: str) -> Path | None:
    if db_path == ":memory:":
        return None
    return Path(os.path.abspath(db_path)).parent / "security" / "snapshot.json"
