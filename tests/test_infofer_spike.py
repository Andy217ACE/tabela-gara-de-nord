# © 2026 Andy217Ace
"""Spike-ul intern Infofer: parserul pe fixture (fără rețea), inserarea + retenția, analiza
pe două baze sintetice mici."""
import gzip
import importlib.util
import io
import sqlite3
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import quality as dq

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "infofer_map.html"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


col = _load("infofer_collect")
ana = _load("infofer_analyze")


def _rows():
    rows, bad = col.parse(FIXTURE.read_text(encoding="utf-8"))
    return {r["train_no"]: r for r in rows}, bad


def test_parser_all_fields_on_fixture():
    rows, bad = _rows()
    assert bad == 1  # markerul defect e ignorat, nu oprește parsarea
    assert set(rows) == {"1641", "10122", "79", "11413", "9999"}  # fără zerouri în față
    r = rows["1641"]
    assert r == {"service_date": "2026-11-27", "train_no": "1641", "category": "IRN",
                 "delay_min": 4, "delay_raw": "4 min întârziere", "report_hhmm": "22:50",
                 "passed_time": 4, "lat": 45.3526321, "lon": 25.552929, "bearing": None,
                 "operator": "1153"}


def test_parser_delay_variants_and_entities():
    rows, _ = _rows()
    assert (rows["10122"]["delay_min"], rows["10122"]["delay_raw"]) == (0, "fără întârziere")
    assert rows["10122"]["category"] == "R-E" and rows["10122"]["bearing"] == 314.0
    assert rows["10122"]["report_hhmm"] == "22:54"  # „Ultima poziție GPS la”
    assert (rows["79"]["delay_min"], rows["79"]["delay_raw"]) == (-1, "1 min mai devreme")
    assert rows["11413"]["passed_time"] == 27 and rows["11413"]["report_hhmm"] == "22:27"
    assert rows["9999"]["delay_min"] is None and rows["9999"]["delay_raw"] is None


def test_parse_delay():
    assert col.parse_delay("16 min întârziere") == 16
    assert col.parse_delay("fără întârziere") == 0
    assert col.parse_delay("3 min mai devreme") == -3
    assert col.parse_delay("altceva") is None and col.parse_delay(None) is None


def test_store_and_retention(tmp_path):
    conn = col.connect(str(tmp_path / "i.db"))
    rows, _ = _rows()
    now = datetime(2026, 11, 27, 21, 0, tzinfo=timezone.utc)
    col.store(conn, now - timedelta(days=31), list(rows.values()), 200, 10, None)
    col.store(conn, now, list(rows.values()), 200, 10, None)
    col.store(conn, now, [], 200, 5, "0 markeri")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("SELECT COUNT(DISTINCT fetched_at), COUNT(*) FROM infofer_obs"
                        ).fetchone() == (1, 5)
    assert conn.execute("SELECT n_markers, error FROM infofer_runs ORDER BY rowid").fetchall() \
        == [(5, None), (0, "0 markeri")]


def test_main_logs_failure_and_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr(col, "fetch", lambda: (200, b"<html>fara markeri</html>"))
    db = str(tmp_path / "i.db")
    assert col.main(["--db", db]) == 1
    run = sqlite3.connect(db).execute("SELECT http_status, n_markers, error FROM infofer_runs"
                                      ).fetchone()
    assert run[:2] == (200, 0) and "format" in run[2]



class _Resp:
    """Răspuns HTTP fals (fără rețea); `read(n)` respectă n, ca http.client."""
    def __init__(self, body: bytes, headers: dict | None = None):
        self._buf, self.headers, self.status, self.max_read = io.BytesIO(body), headers or {}, 200, 0

    def read(self, n=-1):
        self.max_read = max(self.max_read, n)
        return self._buf.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _gzip_bomb(n: int) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, 16 + zlib.MAX_WBITS)
    chunk = bytes(1 << 20)
    out = [c.compress(chunk) for _ in range(n >> 20)]
    return b"".join(out) + c.flush()


def test_read_body_normal_plain_and_gzip():
    page = FIXTURE.read_bytes()
    assert col.read_body(_Resp(page)) == page
    assert col.read_body(_Resp(gzip.compress(page), {"Content-Encoding": "gzip"})) == page


def test_read_body_rejects_big_content_length_without_reading():
    r = _Resp(b"x", {"Content-Length": str(col.MAX_RAW + 1)})
    with pytest.raises(col.TooLarge):
        col.read_body(r)
    assert r.max_read == 0


def test_read_body_caps_raw_read():
    r = _Resp(b"x" * (col.MAX_RAW + 100))      # no Content-Length (chunked)
    with pytest.raises(col.TooLarge):
        col.read_body(r)
    assert r.max_read == col.MAX_RAW + 1


def test_gzip_bomb_rejected_with_bounded_output():
    bomb = _gzip_bomb(64 << 20)                  # 64 MB of zeros -> ~64 KB compressed
    assert len(bomb) < col.MAX_RAW
    with pytest.raises(col.TooLarge):
        col.read_body(_Resp(bomb, {"Content-Encoding": "gzip"}))


def test_truncated_gzip_is_eof_error():
    with pytest.raises(EOFError):
        col.gunzip_capped(gzip.compress(b"a" * 1000)[:-12])


def test_main_logs_oversized_response(tmp_path, monkeypatch):
    bomb = _gzip_bomb(16 << 20)
    monkeypatch.setattr(col.urllib.request, "urlopen",
                        lambda req, timeout: _Resp(bomb, {"Content-Encoding": "gzip"}))
    db = str(tmp_path / "i.db")
    assert col.main(["--db", db]) == 1
    run = sqlite3.connect(db).execute("SELECT n_markers, error FROM infofer_runs").fetchone()
    assert run[0] == 0 and run[1].startswith("TooLarge")


def _main_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE services (id INTEGER PRIMARY KEY, board TEXT, service_date TEXT,"
        " train_type TEXT, train_no INTEGER, station TEXT, operator TEXT, sched_time TEXT,"
        " first_seen TEXT, last_seen TEXT, last_delay INTEGER NOT NULL DEFAULT 0,"
        " last_platform INTEGER, status TEXT NOT NULL DEFAULT 'listed');"
        "CREATE TABLE events (id INTEGER PRIMARY KEY, service_id INTEGER, ts TEXT,"
        " kind TEXT, old TEXT, new TEXT);")
    dq.ensure_schema(conn)
    for sid, board, sd, no, st, final in (
            (1, "arrival", "2026-11-27", 1641, "10:00", 20),   # Infofer vede 15, tabela 0
            (2, "arrival", "2026-11-28", 79, "00:20", 5),      # după miezul nopții
            (3, "arrival", "2026-11-27", 555, "10:00", 3),     # fără observație Infofer
            (4, "departure", "2026-11-27", 1641, "10:00", 9)):  # plecările nu contează
        conn.execute("INSERT INTO services (id, board, service_date, train_type, train_no,"
                     " station, operator, sched_time, first_seen, last_seen) VALUES"
                     " (?, ?, ?, 'IR', ?, 'X', 'CFR', ?, '', '')", (sid, board, sd, no, st))
        conn.execute("INSERT INTO service_quality (service_id, delay_checked, last_delay_clean,"
                     " updated_at) VALUES (?, 1, ?, '')", (sid, final))
    conn.execute("INSERT INTO events (service_id, ts, kind, old, new) VALUES"
                 " (1, '2026-11-27T09:50:00+02:00', 'delay', '0', '20')")
    conn.commit()
    conn.close()


def test_analyze_synthetic(tmp_path):
    main_p, inf_p = str(tmp_path / "m.db"), str(tmp_path / "i.db")
    _main_db(main_p)
    conn = col.connect(inf_p)
    base = {"category": "IR", "delay_raw": "", "lat": 0.0, "lon": 0.0, "bearing": None,
            "operator": "1153"}

    def obs(utc, sd, no, delay, hhmm, passed=3):
        col.store(conn, utc, [{**base, "service_date": sd, "train_no": no, "delay_min": delay,
                               "report_hhmm": hhmm, "passed_time": passed}], 200, 1, None)

    u = timezone.utc
    obs(datetime(2026, 11, 27, 6, 40, tzinfo=u), "2026-11-27", "1641", 15, "08:38")  # 08:40 local
    obs(datetime(2026, 11, 27, 6, 44, tzinfo=u), "2026-11-27", "1641", 50, "08:00", 44)  # veche
    obs(datetime(2026, 11, 27, 21, 10, tzinfo=u), "2026-11-27", "79", 4, "23:08")  # Date = ziua dinainte
    obs(datetime(2026, 11, 27, 22, 30, tzinfo=u), "2026-11-28", "1", 0, "00:28")  # alt tren
    conn.close()
    with sqlite3.connect(f"file:{inf_p}?mode=ro", uri=True) as i, \
            sqlite3.connect(f"file:{main_p}?mode=ro", uri=True) as m:
        r = ana.analyze(i, m)
    h60 = r["horizons"][60]  # 1641: T-60 = 09:00 local; 79: T-60 = 23:20 local (27.11)
    assert (h60["eligible"], h60["covered"]) == (3, 2)  # 555: fără observație
    assert h60["infofer"] == {"mae": 3.0, "bias": -3.0}  # |15-20| și |4-5|
    assert h60["tabela"] == {"mae": 12.5, "bias": -12.5}  # tabela arăta 0 la acel moment
    assert h60["infofer_better_pct"] == 100.0
    assert r["horizons"][15]["covered"] == 1  # 1641: ultima observație > 60 min în urmă
    assert r["worst"][0]["train_no"] == 1641 and r["worst"][0]["err"] == -5
    assert "Infofer" in ana.text_report(r)


def test_analyze_empty_infofer(tmp_path):
    main_p, inf_p = str(tmp_path / "m.db"), str(tmp_path / "i.db")
    _main_db(main_p)
    col.connect(inf_p).close()
    with sqlite3.connect(f"file:{inf_p}?mode=ro", uri=True) as i, \
            sqlite3.connect(f"file:{main_p}?mode=ro", uri=True) as m:
        r = ana.analyze(i, m)
    assert r["horizons"] == {} and "Nicio observație" in ana.text_report(r)
