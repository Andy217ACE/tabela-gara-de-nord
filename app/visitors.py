# © 2026 Andy217Ace
"""Online visitors for #admin: in memory only (one uvicorn worker), reset on restart.

Fed by the HTTP middleware, keyed by request.client.host (uvicorn --proxy-headers with
--forwarded-allow-ips 127.0.0.1 already resolves the real IP behind nginx; no header is read
here). "Online" = a request in the last ONLINE_S seconds. Bots and non-browser clients are
ignored by User-Agent. Last page = the last non-asset request path (page or /api call).
"""
from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict

ONLINE_S = 300
MAX_ENTRIES = 500  # oldest-seen dropped first

_BOT = re.compile(r"bot|spider|crawl|curl|wget|python|httpx|headless|monitor|uptime|preview|"
                  r"scan|fetch|http-client|go-http|java/|okhttp|libwww|axios|node", re.I)
_BROWSER = re.compile(r"^Mozilla/\d")
_ASSET = re.compile(r"\.(js|css|png|jpe?g|svg|ico|webp|woff2?|json|map|txt|xml|webmanifest)$", re.I)

_lock = threading.Lock()
_seen: OrderedDict[str, dict] = OrderedDict()


def mask_ip(ip: str) -> str:
    if ":" in ip:
        return ":".join(ip.split(":")[:3]) + ":x"
    parts = ip.split(".")
    return ".".join(parts[:3] + ["x"]) if len(parts) == 4 else "?"


def parse_ua(ua: str) -> str:
    """Short 'Browser / OS' label."""
    os_ = next((n for p, n in ((r"Windows", "Windows"), (r"Android", "Android"),
                               (r"iPhone|iPad|iOS", "iOS"), (r"Mac OS X|Macintosh", "macOS"),
                               (r"CrOS", "ChromeOS"), (r"Linux", "Linux")) if re.search(p, ua)), "?")
    br = next((n for p, n in ((r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"), (r"SamsungBrowser", "Samsung"),
                              (r"Firefox/|FxiOS", "Firefox"), (r"Chrome/|CriOS", "Chrome"),
                              (r"Safari/", "Safari")) if re.search(p, ua)), "?")
    return f"{br} / {os_}"


def record(ip: str, ua: str, path: str, now: float | None = None) -> None:
    if not ip or not _BROWSER.match(ua or "") or _BOT.search(ua) or _ASSET.search(path):
        return
    now = time.time() if now is None else now
    with _lock:
        v = _seen.pop(ip, None)
        if v is None:
            v = {"first": now, "n": 0}
        v.update(last=now, path=path[:200], ua=ua[:300], n=v["n"] + 1)
        _seen[ip] = v  # re-insert: the dict stays ordered by last seen
        while len(_seen) > MAX_ENTRIES:
            _seen.popitem(last=False)


def online(now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    with _lock:
        items = [(ip, dict(v)) for ip, v in _seen.items() if now - v["last"] <= ONLINE_S]
    return [{"ip": mask_ip(ip), "client": parse_ua(v["ua"]), "path": v["path"],
             "requests": v["n"], "first_seen": v["first"], "last_seen": v["last"]}
            for ip, v in reversed(items)]


def reset() -> None:
    with _lock:
        _seen.clear()
