# © 2026 Andy217Ace
"""Statistici de calitate pe zi (admin): confirmare, citire, acoperirea panoului."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import admin, stats_quality_daily as sq
from app.api import create_app
from app.config import Settings
from app.store import Store

BUC = ZoneInfo("Europe/Bucharest")
ROOT = Path(__file__).resolve().parent.parent
TOKEN = "t" * 20 + "-secret-admin-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
NOW = datetime(2026, 10, 20, 12, 30, tzinfo=BUC)


def iso(day, h, m=0):
    return datetime(2026, 10, day, h, m, tzinfo=BUC).isoformat()


def add_service(store, day, no, state, *, hm="10:00"):
    """state: confirmed / unconfirmed / unknown / in_progress, through the real rules."""
    c = store._conn
    d = f"2026-10-{day:02d}"
    gone = state != "in_progress"
    read_at = None if state == "unknown" else iso(day, 10, 5)
    sid = c.execute(
        "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
        " sched_time, first_seen, last_seen, last_delay, status, delay_read_at)"
        " VALUES ('arrival', ?, 'IR', ?, 'X', 'CFR', ?, ?, ?, 0, ?, ?)",
        (d, no, hm, iso(day, 9), iso(day, 11), "gone" if gone else "listed", read_at)).lastrowid
    if state == "confirmed":  # gone event after the estimated time, delay read shortly before
        c.execute("INSERT INTO events(service_id, ts, kind) VALUES (?, ?, 'gone')",
                  (sid, iso(day, 10, 10)))
    c.commit()


def add_capture(store, day, h, m, ok=1):
    c = store._conn
    return c.execute("INSERT INTO captures(captured_at, image_hash, ok) VALUES (?, ?, ?)",
                     (iso(day, h, m), f"h{day}-{h}-{m}-{ok}", ok)).lastrowid


def add_obs(store, cap, day, h, m, state):
    store._conn.execute(
        "INSERT INTO observations(capture_id, board, row_index, observed_at, validation_state,"
        " processing_version) VALUES (?, 'arrival', 0, ?, ?, 'v')", (cap, iso(day, h, m), state))


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


# -- 1. rata de confirmare ------------------------------------------------------------

def test_confirmation_counts_percent_and_partial_today(store):
    for i in range(3):
        add_service(store, 19, 100 + i, "confirmed")
    add_service(store, 19, 110, "unconfirmed")
    add_service(store, 19, 111, "unknown")
    add_service(store, 20, 120, "confirmed")
    add_service(store, 20, 121, "in_progress")
    out = sq.confirmation_daily(store, NOW, days=14)
    by = {d["date"]: d for d in out["days"]}
    d19 = by["2026-10-19"]
    assert (d19["confirmed"], d19["unconfirmed"], d19["unknown"], d19["in_progress"]) == (3, 1, 1, 0)
    assert d19["total"] == 5
    assert d19["pct_confirmed"] == 60.0  # 3 of 5 decided
    d20 = by["2026-10-20"]
    assert d20["partial"] is True and d20["in_progress"] == 1
    assert d20["pct_confirmed"] == 100.0  # in_progress is not decided: 1 of 1


def test_first_day_of_data_is_partial(store):
    add_service(store, 18, 1, "confirmed")
    add_service(store, 19, 2, "confirmed")
    by = {d["date"]: d for d in sq.confirmation_daily(store, NOW, days=14)["days"]}
    assert by["2026-10-18"]["partial"] is True and by["2026-10-19"]["partial"] is False


def test_confirmation_trend(store):
    add_service(store, 17, 1, "confirmed")
    add_service(store, 17, 2, "unconfirmed")
    add_service(store, 18, 3, "confirmed")
    add_service(store, 18, 4, "confirmed")
    add_service(store, 19, 5, "confirmed")
    out = sq.confirmation_daily(store, NOW, days=14)
    # complete days only (17 is partial = first day): 18 -> 100, 19 -> 100 => flat
    assert out["trend"]["direction"] == "flat"
    assert sq.trend([60.0, 60.5])["direction"] == "flat"
    assert sq.trend([90.0, 80.0])["direction"] == "down"
    t = sq.trend([50.0, 100.0])
    assert t["direction"] == "up" and t["delta_pp"] == 50.0
    assert sq.trend([90.0])["direction"] == "unknown"


def test_confirmation_empty_and_out_of_window(store):
    assert sq.confirmation_daily(store, NOW, days=7)["days"] == []
    add_service(store, 1, 1, "confirmed")
    assert sq.confirmation_daily(store, NOW, days=7)["days"] == []  # 19 days ago


# -- 2. calitatea citirii -----------------------------------------------------------

def test_reading_quality_per_day(store):
    cap = add_capture(store, 19, 10, 0)
    for st in ("ok", "ok", "ok", "uncertain", "incomplete", "rejected_low_conf"):
        add_obs(store, cap, 19, 10, 0, st)
    cap2 = add_capture(store, 20, 10, 0)
    add_obs(store, cap2, 20, 10, 0, "ok")
    out = sq.reading_daily(store, NOW, days=7)
    by = {d["date"]: d for d in out["days"]}
    d = by["2026-10-19"]
    assert (d["ok"], d["uncertain"], d["incomplete"], d["rejected"], d["total"]) == (3, 1, 1, 1, 6)
    assert d["pct_ok"] == 50.0 and d["pct_uncertain"] == pytest.approx(16.7)
    assert by["2026-10-20"]["partial"] is True and by["2026-10-20"]["pct_ok"] == 100.0


# -- 3. acoperirea panoului ---------------------------------------------------------

def test_coverage_per_hour_and_gaps(store):
    for m in range(60):
        add_capture(store, 19, 10, m)
    for m in range(30):
        add_capture(store, 19, 11, m)
    for m in range(30, 35):
        add_capture(store, 19, 11, m, ok=0)
    now = datetime(2026, 10, 19, 13, 20, tzinfo=BUC)
    out = sq.coverage_hourly(store, now, days=2, threshold=0.9)
    hours = {(h["date"], h["hour"]): h for h in out["hours"]}
    h10, h11, h12 = hours[("2026-10-19", 10)], hours[("2026-10-19", 11)], hours[("2026-10-19", 12)]
    assert h10["ok"] == 60 and h10["expected"] == 60 and h10["pct"] == 100.0 and not h10["gap"]
    assert h11["ok"] == 30 and h11["failed"] == 5 and h11["pct"] == 50.0 and h11["gap"]
    assert h12["ok"] == 0 and h12["gap"]
    h13 = hours[("2026-10-19", 13)]  # current hour: only the minutes elapsed are expected
    assert h13["partial"] is True and h13["expected"] == 20 and h13["gap"] is False
    assert [g["hour"] for g in out["gaps"]] == [12, 11]  # newest first
    day = {d["date"]: d for d in out["days"]}["2026-10-19"]
    assert day["ok"] == 90 and day["hours_with_gap"] == 2
    assert ("2026-10-19", 9) not in hours  # before the first capture: not a gap


def test_coverage_threshold(store):
    add_capture(store, 19, 9, 0)  # earlier first hour: hour 10 is no longer the partial first one
    for m in range(55):
        add_capture(store, 19, 10, m)
    now = datetime(2026, 10, 19, 11, 59, tzinfo=BUC)
    key = ("2026-10-19", 10)
    out = sq.coverage_hourly(store, now, days=1, threshold=0.9)
    assert not {(h["date"], h["hour"]): h for h in out["hours"]}[key]["gap"]
    out = sq.coverage_hourly(store, now, days=1, threshold=0.95)
    assert {(h["date"], h["hour"]): h for h in out["hours"]}[key]["gap"]


def test_read_only(store):
    add_service(store, 19, 1, "confirmed")
    cap = add_capture(store, 19, 10, 0)
    add_obs(store, cap, 19, 10, 0, "ok")
    store._conn.commit()
    before = store._conn.total_changes
    sq.confirmation_daily(store, NOW, days=7)
    sq.reading_daily(store, NOW, days=7)
    sq.coverage_hourly(store, NOW, days=7)
    assert store._conn.total_changes == before


# -- HTTP: autentificare + formă -----------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    admin.reset_failures()
    s = Settings(db_path=":memory:", source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c",
                 tesseract_cmd="tesseract-does-not-exist", poller_restart_backoff=0.01)
    with TestClient(create_app(s, start_poller=False), base_url="https://testserver") as c:
        yield c
    admin.reset_failures()


PATHS = ["/api/admin/quality-daily/confirmation", "/api/admin/quality-daily/reading",
         "/api/admin/quality-daily/coverage"]


@pytest.mark.parametrize("path", PATHS)
def test_endpoints_require_admin(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401


@pytest.mark.parametrize("path", PATHS)
def test_endpoints_ok_on_empty_db_and_validate_days(client, path):
    r = client.get(path + "?days=90", headers=AUTH)
    assert r.status_code == 200
    assert client.get(path + "?days=9999", headers=AUTH).status_code == 422
    assert isinstance(r.json()["days"], list)
    assert client.get(path + "?days=abc", headers=AUTH).status_code == 422


# -- UI static ----------------------------------------------------------------------

def test_ui_js_safe_and_wired():
    js = (ROOT / "web" / "stat_quality_daily.js").read_text(encoding="utf-8")
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", "cssText", "localStorage"):
        assert bad not in js, bad
    for p in PATHS:
        assert p in js
    assert "statQualityDaily" in js
    sis = (ROOT / "web" / "sistem.js").read_text(encoding="utf-8")
    assert "statQualityDaily" in sis
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    assert "stat_quality_daily.js" in html and "stat_quality_daily.css" in html
    css = (ROOT / "web" / "stat_quality_daily.css").read_text(encoding="utf-8")
    assert "var(--" in css and "@import" not in css and "url(" not in css
