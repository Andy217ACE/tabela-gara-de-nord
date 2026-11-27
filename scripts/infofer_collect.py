# © 2026 Andy217Ace
"""Spike INTERN (7 zile): colectează harta trenurilor în circulație de la Infofer.

O rulare = o cerere GET la LoadMapPartial, parsarea markerilor Leaflet (un marker pe tren)
și inserarea lor într-o bază SQLite SEPARATĂ (nu în tabela.db). Nimic nu apare pe site;
datele servesc doar la scripts/infofer_analyze.py (prezice Infofer întârzierea la sosire
mai devreme decât tabela?). Termenii Infofer: uz necomercial, fără afișare publică fără
acord scris.

Uz: python scripts/infofer_collect.py [--db /var/lib/tabela/infofer.db]
Ieșire: 0 dacă s-a parsat cel puțin un marker, 1 altfel (eroarea e scrisă în infofer_runs).
"""
from __future__ import annotations

import argparse
import gzip
import html
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

URL = "https://mersultrenurilor.infofer.ro/ro-RO/Trains/LoadMapPartial"
DEFAULT_DB = "/var/lib/tabela/infofer.db"
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)"
              " Chrome/131.0 Safari/537.36")
TIMEOUT_S = 20
RETENTION_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS infofer_obs (
    fetched_at TEXT NOT NULL,
    service_date TEXT NOT NULL,
    train_no TEXT NOT NULL,
    category TEXT,
    delay_min INTEGER,
    delay_raw TEXT,
    report_hhmm TEXT,
    passed_time INTEGER,
    lat REAL,
    lon REAL,
    bearing REAL,
    operator TEXT
);
CREATE INDEX IF NOT EXISTS ix_infofer_obs ON infofer_obs(service_date, train_no, fetched_at);
CREATE TABLE IF NOT EXISTS infofer_runs (
    fetched_at TEXT NOT NULL,
    http_status INTEGER,
    bytes INTEGER,
    n_markers INTEGER,
    error TEXT
);
"""

_MARKER = re.compile(r"var\s+icon\s*=\s*L\.svgIcon\(")
_TRAIN = re.compile(r"TrainRunningNumber=(\d+)&amp;Date=(\d{2})\.(\d{2})\.(\d{4})")
_CATEGORY = re.compile(r'span-train-category-[\w-]*">\s*([^<]*?)\s*<')
_DELAY = re.compile(r"<span class=color-[\w-]+>\s*<b>([^<]*)</b>([^<]*)</span>")
_REPORT = re.compile(r'class="[^"]*\balert\b[^"]*"[^>]*>([^<]*)</div>')
_HHMM = re.compile(r"\b(\d{1,2}:\d{2})\b")
_PASSED = re.compile(r"passedTime:\s*(-?\d+)")
_BEARING = re.compile(r"bearing:\s*(-?[\d.]+)")
_LAT = re.compile(r"var\s+\w*Latitude\s*=\s*(-?[\d.]+)")
_LON = re.compile(r"var\s+\w*Longitude\s*=\s*(-?[\d.]+)")
_OPERATOR = re.compile(r"/images/Logos/(\w+)-mini")
_MIN = re.compile(r"(\d+)\s*min")


def _text(s: str) -> str:
    return " ".join(html.unescape(s).split())


def parse_delay(raw: str | None) -> int | None:
    """'16 min întârziere' -> 16, 'fără întârziere' -> 0, '1 min mai devreme' -> -1."""
    if not raw:
        return None
    low = raw.lower()
    if "fără întârziere" in low:
        return 0
    m = _MIN.search(low)
    if not m:
        return None
    if "devreme" in low:
        return -int(m.group(1))
    return int(m.group(1)) if "întârziere" in low else None


def parse_marker(block: str) -> dict | None:
    """Un marker -> dict cu coloanele infofer_obs (fără fetched_at); None dacă lipsește
    numărul trenului sau poziția."""
    t, lat, lon = _TRAIN.search(block), _LAT.search(block), _LON.search(block)
    if not (t and lat and lon):
        return None
    cat, dl, rep = _CATEGORY.search(block), _DELAY.search(block), _REPORT.search(block)
    passed, bearing, op = _PASSED.search(block), _BEARING.search(block), _OPERATOR.search(block)
    delay_raw = _text(dl.group(1) + " " + dl.group(2)) if dl else None
    report = _HHMM.search(_text(rep.group(1))) if rep else None
    return {
        "service_date": f"{t.group(4)}-{t.group(3)}-{t.group(2)}",
        "train_no": t.group(1).lstrip("0") or "0",
        "category": _text(cat.group(1)) if cat else None,
        "delay_min": parse_delay(delay_raw),
        "delay_raw": delay_raw,
        "report_hhmm": report.group(1).zfill(5) if report else None,
        "passed_time": int(passed.group(1)) if passed else None,
        "lat": float(lat.group(1)),
        "lon": float(lon.group(1)),
        "bearing": float(bearing.group(1)) if bearing else None,
        "operator": op.group(1) if op else None,
    }


def parse(page: str) -> tuple[list[dict], int]:
    """Toți markerii parsabili din pagină și numărul celor ignorați (niciodată excepție
    pentru un singur marker defect)."""
    rows, bad = [], 0
    for block in _MARKER.split(page)[1:]:
        try:
            row = parse_marker(block)
        except (ValueError, IndexError):
            row = None
        if row is None:
            bad += 1
        else:
            rows.append(row)
    return rows, bad


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def store(conn: sqlite3.Connection, fetched_at: datetime, rows: list[dict],
          http_status: int | None, nbytes: int | None, error: str | None) -> None:
    """Inserează observațiile și rularea, apoi șterge ce e mai vechi de RETENTION_DAYS."""
    ts = fetched_at.isoformat(timespec="seconds")
    cutoff = (fetched_at - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
    with conn:
        conn.executemany(
            "INSERT INTO infofer_obs(fetched_at, service_date, train_no, category, delay_min,"
            " delay_raw, report_hhmm, passed_time, lat, lon, bearing, operator) VALUES"
            " (:fetched_at, :service_date, :train_no, :category, :delay_min, :delay_raw,"
            " :report_hhmm, :passed_time, :lat, :lon, :bearing, :operator)",
            [{**r, "fetched_at": ts} for r in rows])
        conn.execute("INSERT INTO infofer_runs VALUES (?, ?, ?, ?, ?)",
                     (ts, http_status, nbytes, len(rows), error))
        conn.execute("DELETE FROM infofer_obs WHERE fetched_at < ?", (cutoff,))
        conn.execute("DELETE FROM infofer_runs WHERE fetched_at < ?", (cutoff,))


def fetch() -> tuple[int, bytes]:
    req = urllib.request.Request(URL, headers={
        "User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8",
        "Accept-Encoding": "gzip", "Accept-Language": "ro-RO,ro;q=0.9"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        body = resp.read()
        if resp.headers.get("Content-Encoding", "").lower() == "gzip":
            body = gzip.decompress(body)
        return resp.status, body


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    status = nbytes = None
    rows: list[dict] = []
    error = None
    try:
        status, body = fetch()
        nbytes = len(body)
        rows, bad = parse(body.decode("utf-8", errors="replace"))
        if not rows:
            error = f"0 markeri parsati ({bad} ignorati) - format schimbat?"
        elif bad:
            error = f"{bad} markeri ignorati"
    except urllib.error.HTTPError as e:
        status, error = e.code, f"HTTP {e.code}"
    except (OSError, EOFError) as e:  # URLError, timeout, gzip trunchiat
        error = f"{type(e).__name__}: {e}"[:300]
    conn = connect(args.db)
    try:
        store(conn, now, rows, status, nbytes, error)
    finally:
        conn.close()
    print(f"infofer: http={status} bytes={nbytes} markeri={len(rows)}"
          + (f" eroare={error}" if error else ""))
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
