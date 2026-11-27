# © 2026 Andy217Ace
"""GET /api/admin/infofer (pagina admin #infofer): auth, no-store, DB lipsă/stricată, sănătatea
colectării, potrivirea „live” cu tabela și acuratețea preliminară pe baze sintetice."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import admin, infofer_api
from app.api import create_app
from app.config import Settings
from tests.test_infofer_spike import _main_db, col

TOKEN = "t" * 20 + "-secret-admin-token"
B = "/api/admin/infofer"
NOW = datetime(2026, 11, 28, 10, 0, tzinfo=timezone.utc)  # 12:00 la București


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    monkeypatch.setattr(infofer_api, "_acc", {"key": None, "at": 0.0, "value": None})


@pytest.fixture
def raw(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("INFOFER_DB", str(tmp_path / "missing.db"))
    monkeypatch.setattr(admin, "FAIL_DELAY_S", 0.0)
    admin.reset_failures()
    st = Settings(db_path=":memory:", source_url="https://example.com/x", vapid_private_key="",
                  vapid_public_key="", vapid_subject="mailto:a@b.c",
                  tesseract_cmd="tesseract-does-not-exist", poller_restart_backoff=0.01)
    with TestClient(create_app(st, start_poller=False), base_url="https://testserver") as c:
        yield c
    admin.reset_failures()


def test_requires_admin(raw):
    assert raw.get(B).status_code == 401


def test_missing_db_disabled_no_store(raw):
    r = raw.get(B, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200 and r.json() == {"enabled": False}
    assert "no-store" in r.headers["cache-control"]


def test_corrupt_db_reports_error_not_500(raw, tmp_path, monkeypatch):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"not a sqlite database" * 100)
    monkeypatch.setenv("INFOFER_DB", str(bad))
    r = raw.get(B, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    d = r.json()
    assert d["enabled"] is True and "Error" in d["error"] and "health" not in d


def _dbs(tmp_path):
    main_p, inf_p = str(tmp_path / "m.db"), str(tmp_path / "i.db")
    _main_db(main_p)  # servicii pe 27-28.11 (cu finală confirmată) pentru analiză
    m = sqlite3.connect(main_p)
    for sid, board, no, st, delay in ((10, "arrival", 1641, "12:30", 7),
                                      (11, "arrival", 555, "13:00", 0),
                                      (12, "arrival", 79, "18:00", 0),       # peste 3 h
                                      (13, "departure", 2000, "12:10", 0)):  # plecare
        m.execute("INSERT INTO services (id, board, service_date, train_type, train_no, station,"
                  " operator, sched_time, first_seen, last_seen, last_delay) VALUES"
                  " (?, ?, '2026-11-28', 'IR', ?, 'Iasi', 'CFR', ?, '', '', ?)",
                  (sid, board, no, st, delay))
    m.commit()
    m.close()
    conn = col.connect(inf_p)
    base = {"category": "IR", "delay_raw": "", "lat": 0.0, "lon": 0.0, "bearing": None,
            "operator": "1153", "report_hhmm": "11:50"}

    def row(no, delay, passed, sd="2026-11-28"):
        return {**base, "service_date": sd, "train_no": no, "delay_min": delay, "passed_time": passed}

    col.store(conn, NOW - timedelta(hours=36), [row("1", 0, 1)] * 4, 200, 100, None)  # în afara 24 h
    col.store(conn, NOW - timedelta(hours=2), [row("1641", 3, 1)] * 4, 200, 100, None)
    col.store(conn, NOW - timedelta(hours=1), [], 200, 50, "0 markeri")
    col.store(conn, NOW - timedelta(minutes=5),
              [row("1641", 12, 3), row("555", 4, 20), row("79", 1, 0), row("2000", 9, 0)],
              200, 120, None)
    conn.close()
    return inf_p, main_p


def test_overview_health_live_accuracy(tmp_path):
    inf_p, main_p = _dbs(tmp_path)
    d = infofer_api.overview(inf_p, main_p, now=NOW)
    assert d["enabled"] is True and "error" not in d, d
    h = d["health"]
    assert (h["runs_total"], h["runs_24h"], h["failed_24h"], h["fail_pct_24h"]) == (4, 3, 1, 33.3)
    assert h["ok"] is False and h["problems"] == ["failures"]  # 33% eșuate > 20%
    assert h["avg_markers_24h"] == round((4 + 0 + 4) / 3, 1)
    assert h["last_run"]["n_markers"] == 4 and h["last_run"]["bytes"] == 120
    assert h["last_ok_at"] == h["last_run"]["at"] and h["days_elapsed"] == 1.5 and h["days_target"] == 7
    assert sum(x["runs"] for x in d["hourly"]) == 3 and sum(x["failed"] for x in d["hourly"]) == 1
    lv = d["live"]
    assert lv["fetched_at"] == h["last_run"]["at"]
    assert [(t["train_no"], t["infofer_delay"], t["board_delay"], t["stale"]) for t in lv["trains"]] \
        == [(1641, 12, 7, False), (555, 4, 0, True)]  # 79 peste 3 h, 2000 e plecare
    assert lv["trains"][0]["sched_time"] == "12:30" and lv["trains"][0]["report_hhmm"] == "11:50"
    acc = d["accuracy"]
    assert set(acc["horizons"]) == {"60", "30", "15"}
    assert acc["horizons"]["60"]["eligible"] >= 1 and "mae" in acc["horizons"]["60"]["infofer"]


def test_health_ok_when_fresh_and_cached_accuracy(tmp_path, monkeypatch):
    inf_p, main_p = _dbs(tmp_path)
    conn = col.connect(inf_p)
    for k in range(1, 4):  # mai multe rulări reușite: eșecurile scad sub 20%
        col.store(conn, NOW - timedelta(minutes=10 + k), [], 200, 1, None)
        conn.execute("UPDATE infofer_runs SET n_markers = 4 WHERE n_markers = 0 AND error IS NULL")
    conn.commit()
    conn.close()
    first = infofer_api.overview(inf_p, main_p, now=NOW)
    assert first["health"]["ok"] is True and first["health"]["problems"] == []
    calls = []
    monkeypatch.setattr(infofer_api, "_ro", lambda p: calls.append(p) or sqlite3.connect(p))
    again = infofer_api.overview(inf_p, main_p, now=NOW)
    assert again["accuracy"] is first["accuracy"] and len(calls) == 2  # analiza: din cache
    stale = infofer_api.overview(inf_p, main_p, now=NOW + timedelta(minutes=11))
    assert stale["health"]["problems"] == ["stale"]
