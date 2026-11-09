# © 2026 Andy217Ace
"""Exportatorul de securitate pentru pagina #admin: IP-urile banate de fail2ban, istoricul
ban-urilor și cererile (totale / probe) din log-ul nginx, pe 24 h și 7 zile.

Rulează ca root din tabela-security-snapshot.timer (vezi deploy/) și scrie atomic un JSON
(`/var/lib/tabela/security/snapshot.json`, 0640, grup `tabela`). Aplicația doar citește
fișierul: nu primește privilegii, nu atinge fail2ban sau log-urile.

Doar biblioteca standard. Fără rețea (unit-ul are PrivateNetwork=yes), fără DNS invers sau
geoIP. Totul e doar citire: DB-ul fail2ban se deschide `mode=ro`. Liniile de log vin din
trafic ostil: se parsează cu regex-uri fixe, căile se taie la MAX_PATH_LEN și nu se
interpretează în niciun fel. Dimensiunea și timpul de rulare sunt limitate (MAX_IPS,
MAX_HISTORY, MAX_RUN_S).

Clasificarea „probă" = filtrul fail2ban `nginx-tabela-probes` (deploy/fail2ban/): aceeași
expresie `_probe` (citită din filtrul instalat, cu o copie identică integrată ca rezervă),
doar răspunsuri 4xx, `/.well-known/` exclus.

Uz: python3 -I scripts/security_snapshot.py [--out PATH] [--db PATH] [--filter PATH]
        [--f2b-log PATH]... [--access-log PATH]... [--group tabela]
Ieșire: 0 dacă fișierul a fost scris (sursele lipsă sunt marcate în el), 1 altfel.
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = 1
DAY = 86400
WEEK = 7 * DAY
MAX_IPS = 500          # IP-uri cu detalii în snapshot (banați întâi, apoi după probe)
MAX_HISTORY = 200      # evenimente ban/unban
TOP_PATHS = 5          # căi probate pe IP
TOP_IPS = 20           # „top IP-uri după cereri-probă"
MAX_PATH_LEN = 200
MAX_LINE = 8192
MAX_PATHS_PER_IP = 200  # chei distincte ținute în memorie pe IP
MAX_RUN_S = 40.0       # peste acest timp citirea log-urilor se oprește (truncated)
FUTURE_SKEW_S = 300

DEFAULT_OUT = "/var/lib/tabela/security/snapshot.json"
DEFAULT_DB = "/var/lib/fail2ban/fail2ban.sqlite3"
DEFAULT_FILTER = "/etc/fail2ban/filter.d/nginx-tabela-probes.local"
DEFAULT_F2B_LOGS = ["/var/log/fail2ban.log", "/var/log/fail2ban.log.1",
                    "/var/log/fail2ban.log.2.gz"]
DEFAULT_ACCESS_LOGS = (["/var/log/nginx/access.log", "/var/log/nginx/access.log.1"]
                       + [f"/var/log/nginx/access.log.{i}.gz" for i in range(2, 15)])
DEFAULT_GROUP = "tabela"

# copie identică a `_probe` din deploy/fail2ban/nginx-tabela-probes.local (test de egalitate)
BUILTIN_PROBE = (
    r'(?:[^" ?]*/)?(?:\.(?:env[^/" ]*|git(?:/|ignore|-credentials|lab-ci\.ya?ml)|aws/|svn/|'
    r'hg/|npmrc|htpasswd|htaccess|ssh/|DS_Store|docker/|vscode/sftp)|SDK/webLanguage|'
    r'wp-(?:config|login|admin|includes|content)|[^" ?]*\.php\d?(?:[./?]|(?=[ "]))|phpinfo|'
    r'config\.json(?=[ "?])|docker-compose\.ya?ml|storage/logs/laravel\.log)')

UTC = timezone.utc
_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1)}
# nginx „combined": IP - user [09/Nov/2026:17:10:14 +0000] "GET /x HTTP/1.1" 404 ...
_ACCESS = re.compile(
    r'^(\S{1,64}) \S+ \S+ \[(\d{2})/([A-Z][a-z]{2})/(\d{4}):(\d{2}):(\d{2}):(\d{2}) '
    r'([+-])(\d{2})(\d{2})\] "((?:[^"\\]|\\.)*)" (\d{3}) ')
# 2026-11-09 17:10:15,005 fail2ban.actions [668168]: NOTICE  [jail] Ban 1.2.3.4
_F2B = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+ fail2ban\.actions\s+\[\d+\]:\s+\w+\s+'
    r'\[([^\]\s]{1,64})\] (Ban|Unban|Restore Ban) (\S{1,64})\s*$')
_EVENTS = {"Ban": "ban", "Unban": "unban", "Restore Ban": "restore"}


# -- regula de probă -----------------------------------------------------------------------

def compile_probe(probe: str) -> re.Pattern:
    """failregex-ul filtrului, cu <HOST> și data deja scoase: se aplică pe `"<cerere>" <cod> `."""
    return re.compile(r'^"[A-Z]+ (?:https?://[^/" ]+)?/(?!\.well-known/)' + probe
                      + r'[^"]*" 4\d\d ')


_DEFAULT_RX = compile_probe(BUILTIN_PROBE)


def load_probe(filter_path) -> tuple[str, str]:
    """`_probe` din filtrul fail2ban instalat ("filter"), sau copia integrată ("builtin") dacă
    filtrul lipsește, n-are linia sau expresia nu se compilează."""
    try:
        text = Path(filter_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return BUILTIN_PROBE, "builtin"
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "_probe":
            value = value.strip()
            try:
                compile_probe(value)
            except re.error:
                break
            return value, "filter"
    return BUILTIN_PROBE, "builtin"


def is_probe(request: str, status: int, rx: re.Pattern | None = None) -> bool:
    return bool((rx or _DEFAULT_RX).match(f'"{request}" {status} '))


# -- parsere -------------------------------------------------------------------------------

def parse_access_line(line: str) -> dict | None:
    """O linie nginx „combined" -> {ip, ts, request, path, status}; None dacă nu se potrivește.
    `path` e ținta fără query string (tăiată), sau None pentru cereri fără țintă (TLS pe HTTP)."""
    m = _ACCESS.match(line[:MAX_LINE])
    if not m:
        return None
    ip, dd, mon, yyyy, hh, mi, ss_, sign, oh, om, request, status = m.groups()
    month = _MONTHS.get(mon)
    if month is None:
        return None
    try:
        off = timedelta(hours=int(oh), minutes=int(om)) * (-1 if sign == "-" else 1)
        dt = datetime(int(yyyy), month, int(dd), int(hh), int(mi), int(ss_),
                      tzinfo=timezone(off))
    except ValueError:
        return None
    parts = request.split(" ")
    path = None
    if len(parts) >= 2 and (parts[1].startswith("/") or parts[1].startswith("http")):
        path = parts[1].split("?", 1)[0][:MAX_PATH_LEN]
    return {"ip": ip, "ts": dt.timestamp(), "request": request, "path": path,
            "status": int(status)}


def parse_f2b_line(line: str, tz=None) -> dict | None:
    """Ban / Unban / Restore Ban din fail2ban.log; ora din log e ora serverului (`tz` sau
    fusul local)."""
    m = _F2B.match(line.rstrip("\n"))
    if not m:
        return None
    when, jail, event, ip = m.groups()
    try:
        dt = datetime.strptime(when, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    dt = dt.replace(tzinfo=tz) if tz is not None else dt.astimezone()
    return {"ts": int(dt.timestamp()), "event": _EVENTS[event], "jail": jail, "ip": ip}


def _lines(path):
    p = str(path)
    if p.endswith(".gz"):
        return gzip.open(p, "rt", encoding="utf-8", errors="replace")
    return open(p, "r", encoding="utf-8", errors="replace")


# -- baza fail2ban -------------------------------------------------------------------------

def read_f2b_db(path, now: float) -> dict:
    """Doar citire. `banned`: rândurile din `bips` încă active (bantime < 0 = permanent);
    `bans`: ban-urile din ultimele 7 zile din `bans` (fail2ban păstrează ~1 zi, dbpurgeage)."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    con = sqlite3.connect(p.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        jails = [r[0] for r in con.execute(
            "SELECT name FROM jails WHERE enabled=1 ORDER BY name")]
        banned = []
        for ip, jail, tob, bt, cnt in con.execute(
                "SELECT ip, jail, timeofban, bantime, bancount FROM bips ORDER BY timeofban DESC"):
            if not isinstance(tob, int) or not isinstance(bt, int):
                continue
            permanent = bt < 0
            if not permanent and tob + bt <= now:
                continue
            banned.append({"ip": str(ip), "jail": str(jail), "banned_ts": tob,
                           "expires_ts": None if permanent else tob + bt,
                           "bancount": cnt if isinstance(cnt, int) else None})
        bans = [{"ts": tob, "event": "ban", "jail": str(jail), "ip": str(ip)}
                for jail, ip, tob in con.execute(
                    "SELECT jail, ip, timeofban FROM bans WHERE timeofban >= ? "
                    "ORDER BY timeofban DESC LIMIT ?", (int(now - WEEK), MAX_HISTORY))]
    finally:
        con.close()
    return {"jails": jails, "banned": banned, "bans": bans}


# -- agregare ------------------------------------------------------------------------------

def _iso(ts) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


def _new_window() -> dict:
    return {"requests": 0, "probes": 0, "first": None, "last": None, "paths": Counter()}


def _window_out(w: dict | None) -> dict:
    w = w or _new_window()
    paths = sorted(w["paths"].items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_PATHS]
    return {"requests": w["requests"], "probes": w["probes"],
            "first_seen": _iso(w["first"]), "last_seen": _iso(w["last"]),
            "paths": [{"path": p, "count": c} for p, c in paths]}


def _scan_access(paths, now, rx, deadline) -> dict:
    stats: dict[str, dict] = {}
    info = {"available": False, "files": 0, "lines": 0, "parse_errors": 0, "truncated": False,
            "error": False}
    for p in paths:
        if time.monotonic() > deadline:
            info["truncated"] = True
            break
        try:
            st = os.stat(p)
        except OSError:
            continue
        info["available"] = True
        if st.st_mtime < now - WEEK:   # ultima scriere e mai veche de 7 zile: nimic util
            continue
        info["files"] += 1
        try:
            with _lines(p) as fh:
                for raw in fh:
                    info["lines"] += 1
                    if info["lines"] % 2000 == 0 and time.monotonic() > deadline:
                        info["truncated"] = True
                        break
                    r = parse_access_line(raw)
                    if r is None:
                        info["parse_errors"] += 1
                        continue
                    age = now - r["ts"]
                    if age > WEEK or age < -FUTURE_SKEW_S:
                        continue
                    probe = r["path"] is not None and is_probe(r["request"], r["status"], rx)
                    per = stats.setdefault(r["ip"], {"24h": _new_window(), "7d": _new_window()})
                    for name, span in (("24h", DAY), ("7d", WEEK)):
                        if age > span:
                            continue
                        w = per[name]
                        w["requests"] += 1
                        if w["first"] is None or r["ts"] < w["first"]:
                            w["first"] = r["ts"]
                        if w["last"] is None or r["ts"] > w["last"]:
                            w["last"] = r["ts"]
                        if probe:
                            w["probes"] += 1
                            if r["path"] in w["paths"] or len(w["paths"]) < MAX_PATHS_PER_IP:
                                w["paths"][r["path"]] += 1
        except (OSError, EOFError, gzip.BadGzipFile):
            info["error"] = True
        if info["truncated"]:
            break
    return {"stats": stats, "info": info}


def build_snapshot(now: float, db, f2b_logs, access_logs, filter_path, tz=None) -> dict:
    start = time.monotonic()
    deadline = start + MAX_RUN_S
    errors: list[str] = []
    probe, probe_src = load_probe(filter_path)
    rx = compile_probe(probe)

    try:
        f2 = read_f2b_db(db, now)
    except (OSError, sqlite3.Error):
        f2 = None
        errors.append("fail2ban_db")

    events, log_ok = [], False
    for p in f2b_logs:
        try:
            with _lines(p) as fh:
                log_ok = True
                for line in fh:
                    e = parse_f2b_line(line[:MAX_LINE], tz)
                    if e:
                        events.append(e)
        except (OSError, EOFError, gzip.BadGzipFile):
            continue
    if f2b_logs and not log_ok:
        errors.append("fail2ban_log")
    events.sort(key=lambda e: e["ts"])

    # banați acum: DB-ul (bips), minus cei debanați manual după ban (ultimul eveniment din log)
    banned = []
    if f2 is not None:
        last = {}
        for e in events:
            if e["event"] in ("ban", "unban"):
                last[(e["jail"], e["ip"])] = e
        for b in f2["banned"]:
            le = last.get((b["jail"], b["ip"]))
            if le and le["event"] == "unban" and le["ts"] >= b["banned_ts"]:
                continue
            banned.append(b)

    if log_ok:
        history = list(reversed(events))
        bans_24h = sum(1 for e in events if e["event"] == "ban" and e["ts"] >= now - DAY)
        bans_7d = sum(1 for e in events if e["event"] == "ban" and e["ts"] >= now - WEEK)
    elif f2 is not None:
        history = list(f2["bans"])
        bans_24h = sum(1 for e in history if e["ts"] >= now - DAY)
        bans_7d = None
    else:
        history, bans_24h, bans_7d = [], None, None

    scan = _scan_access(access_logs, now, rx, deadline)
    info, stats = scan["info"], scan["stats"]
    if info.pop("error") or not info["available"]:
        errors.append("access_log")

    banned_ips = []
    for b in banned:
        if b["ip"] not in banned_ips:
            banned_ips.append(b["ip"])
    banned_set = set(banned_ips)

    def rank(ip):
        w = stats[ip]["7d"]
        return (-w["probes"], -w["requests"], ip)

    probers = sorted((ip for ip, s in stats.items() if s["7d"]["probes"] > 0), key=rank)
    ips: dict = {}
    truncated_ips = False
    if info["available"]:
        order = banned_ips + [ip for ip in probers if ip not in banned_set]
        truncated_ips = len(order) > MAX_IPS
        for ip in order[:MAX_IPS]:
            s = stats.get(ip, {})
            ips[ip] = {"24h": _window_out(s.get("24h")), "7d": _window_out(s.get("7d"))}

    top = [{"ip": ip, "probes_24h": stats[ip]["24h"]["probes"],
            "probes_7d": stats[ip]["7d"]["probes"], "requests_7d": stats[ip]["7d"]["requests"],
            "last_seen": _iso(stats[ip]["7d"]["last"]), "banned": ip in banned_set}
           for ip in probers[:TOP_IPS]]

    acc = info["available"]
    w24 = [s["24h"] for s in stats.values()]
    w7 = [s["7d"] for s in stats.values()]
    totals = {
        "banned_now": len(banned) if f2 is not None else None,
        "bans_24h": bans_24h,
        "bans_7d": bans_7d,
        "probes_24h": sum(w["probes"] for w in w24) if acc else None,
        "probe_ips_24h": sum(1 for w in w24 if w["probes"]) if acc else None,
        "requests_24h": sum(w["requests"] for w in w24) if acc else None,
        "probes_7d": sum(w["probes"] for w in w7) if acc else None,
        "requests_7d": sum(w["requests"] for w in w7) if acc else None,
    }
    jails = []
    if f2 is not None:
        names = list(f2["jails"]) + sorted({b["jail"] for b in banned} - set(f2["jails"]))
        jails = [{"name": n, "banned_now": sum(1 for b in banned if b["jail"] == n)}
                 for n in names]

    return {
        "schema": SCHEMA,
        "generated_ts": now,
        "generated_at": _iso(now),
        "errors": errors,
        "probe_rule": probe_src,
        "fail2ban": {"available": f2 is not None, "log_available": log_ok, "jails": jails},
        "totals": totals,
        "banned": [{"ip": b["ip"], "jail": b["jail"], "banned_at": _iso(b["banned_ts"]),
                    "expires_at": _iso(b["expires_ts"]), "permanent": b["expires_ts"] is None,
                    "bancount": b["bancount"]} for b in banned],
        "history": [{"at": _iso(e["ts"]), "event": e["event"], "jail": e["jail"], "ip": e["ip"]}
                    for e in history[:MAX_HISTORY]],
        "ips": ips,
        "ips_truncated": truncated_ips,
        "top": top,
        "access_log": info,
        "duration_ms": round((time.monotonic() - start) * 1000),
    }


# -- scriere -------------------------------------------------------------------------------

def write_atomic(out, data: dict, gid: int | None = None) -> None:
    """Scrie `<out>.tmp` lângă țintă și îl redenumește peste țintă; mod 0640, grup `gid`.
    Pe POSIX: directorul se deschide fără a urma symlink-uri și trebuie să aparțină userului
    curent (root în producție); temporarul se creează exclusiv (O_EXCL|O_NOFOLLOW)."""
    out = Path(out)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                         sort_keys=True).encode("utf-8")
    tmp_name = out.name + ".tmp"
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow and os.open in os.supports_dir_fd:
        dfd = os.open(out.parent, os.O_RDONLY | os.O_DIRECTORY | nofollow)
        try:
            if os.fstat(dfd).st_uid != os.geteuid():
                raise PermissionError("output directory not owned by the current user")
            try:
                os.unlink(tmp_name, dir_fd=dfd)
            except FileNotFoundError:
                pass
            fd = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o640,
                         dir_fd=dfd)
            try:
                os.write(fd, payload)
                os.fchmod(fd, 0o640)
                if gid is not None:
                    os.fchown(fd, -1, gid)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.replace(tmp_name, out.name, src_dir_fd=dfd, dst_dir_fd=dfd)
        finally:
            os.close(dfd)
        return
    tmp = out.with_name(tmp_name)  # fallback non-POSIX (teste pe Windows)
    with open(tmp, "wb") as f:
        f.write(payload)
    os.replace(tmp, out)


def _gid(group: str) -> int | None:
    try:
        import grp
        return grp.getgrnam(group).gr_gid
    except (ImportError, KeyError):
        return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Snapshot fail2ban + nginx pentru #admin")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--filter", default=DEFAULT_FILTER)
    ap.add_argument("--f2b-log", action="append", default=None)
    ap.add_argument("--access-log", action="append", default=None)
    ap.add_argument("--group", default=DEFAULT_GROUP)
    a = ap.parse_args(argv)
    try:
        snap = build_snapshot(time.time(), db=a.db,
                              f2b_logs=a.f2b_log or DEFAULT_F2B_LOGS,
                              access_logs=a.access_log or DEFAULT_ACCESS_LOGS,
                              filter_path=a.filter)
        write_atomic(a.out, snap, gid=_gid(a.group) if a.group else None)
    except (OSError, ValueError):
        print("security_snapshot: scrierea a eșuat", file=sys.stderr)  # fără traceback
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
