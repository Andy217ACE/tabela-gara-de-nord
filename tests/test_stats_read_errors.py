# © 2026 Andy217Ace
"""Erori de citire pe ferestre (app.stats_read_errors): 24 h / 48 h / 5 z / 7 z / 30 z glisante,
numărători agregate (nimic privat), cache, plus front-end-ul lazy de pe #statistici."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import stats_read_errors as re_
from app import system_status
from app.api import create_app
from app.config import Settings
from app.store import Store

NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
WEB = Path(__file__).resolve().parent.parent / "web"


def _iso(age):
    return (NOW - age).isoformat(timespec="seconds")


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.migrate()
    c = s._conn
    # captures: age, ok
    caps = [(timedelta(hours=1), 1), (timedelta(hours=2), 0), (timedelta(hours=30), 0),
            (timedelta(days=4), 1), (timedelta(days=6), 1), (timedelta(days=20), 0),
            (timedelta(days=40), 0)]
    for i, (age, ok) in enumerate(caps):
        c.execute("INSERT INTO captures(id, captured_at, image_hash, ok) VALUES (?,?,?,?)",
                  (i + 1, _iso(age), f"h{i}", ok))
    # observations: age, state, processing_version
    obs = [(timedelta(hours=1), "ok", "g"), (timedelta(hours=1), "ok", "g"),
           (timedelta(hours=1), "incomplete", "g+empty"),            # blank line: not an error
           (timedelta(hours=1), "incomplete", "g+unread"),           # unread
           (timedelta(hours=1), "uncertain", "g"),                   # partial
           (timedelta(hours=30), "rejected_low_conf", "g"),          # unread (48 h on)
           (timedelta(days=6), "incomplete", "g+retry:none:6"),      # unread (7 d on)
           (timedelta(days=20), "uncertain", "g"),                   # partial (30 d only)
           (timedelta(days=40), "incomplete", "g+unread")]           # outside every window
    for i, (age, state, pv) in enumerate(obs):
        c.execute("INSERT INTO observations(capture_id, board, row_index, observed_at, validation_state,"
                  " processing_version, raw_text) VALUES (1, 'arrival', ?, ?, ?, ?, 'SECRET TEXT')",
                  (i, _iso(age), state, pv))
    # services: one ghost 3 days ago (local offset), one ghost 40 days ago, one real train
    local = timezone(timedelta(hours=2))
    for sid, age, ghost in ((1, timedelta(days=3), 1), (2, timedelta(days=40), 1), (3, timedelta(hours=1), 0)):
        first = (NOW - age).astimezone(local).isoformat()
        c.execute("INSERT INTO services(id, board, service_date, train_type, train_no, station, operator,"
                  " sched_time, first_seen, last_seen) VALUES (?, 'arrival', ?, 'R', ?, 'X', 'CFR', '10:00', ?, ?)",
                  (sid, first[:10], 100 + sid, first, first))
        c.execute("INSERT INTO service_quality(service_id, ghost, updated_at) VALUES (?,?,?)",
                  (sid, ghost, first))
    c.commit()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    monkeypatch.setattr(re_, "_cache", None)
    monkeypatch.setattr(system_status, "_quality_cache", None)


def test_windows_and_counts(store):
    d = re_.read_errors(store, NOW)
    assert d["windows"] == ["h24", "h48", "d5", "d7", "d30"]
    w = d["data"]
    assert w["h24"] == {"frames": 2, "frames_failed": 1, "rows": 4, "rows_unread": 1, "rows_partial": 1,
                        "ghosts": 0, "error_rate_pct": 50.0}
    assert (w["h48"]["frames"], w["h48"]["frames_failed"], w["h48"]["rows_unread"]) == (3, 2, 2)
    assert (w["d5"]["frames"], w["d5"]["ghosts"]) == (4, 1)
    assert (w["d7"]["frames"], w["d7"]["rows"], w["d7"]["rows_unread"]) == (5, 6, 3)
    assert w["d30"] == {"frames": 6, "frames_failed": 3, "rows": 7, "rows_unread": 3, "rows_partial": 2,
                        "ghosts": 1, "error_rate_pct": 71.4}


def test_empty_db_rates_are_none(tmp_path):
    s = Store(str(tmp_path / "e.db"))
    s.migrate()
    w = re_.read_errors(s, NOW)["data"]["d30"]
    assert w["frames"] == 0 and w["rows"] == 0 and w["error_rate_pct"] is None
    s.close()


def test_cached_until_ttl(store, monkeypatch):
    first = re_.read_errors(store, NOW)
    store._conn.execute("INSERT INTO captures(captured_at, image_hash, ok) VALUES (?, 'new', 0)",
                        (_iso(timedelta(minutes=5)),))
    store._conn.commit()
    assert re_.read_errors(store, NOW) is first
    t = re_.time.monotonic()
    monkeypatch.setattr(re_.time, "monotonic", lambda: t + re_.CACHE_TTL_S + 1)
    assert re_.read_errors(store, NOW)["data"]["h24"]["frames"] == 3


def test_ocr_quality_shares_the_counts(store):
    q = system_status.ocr_quality(store, NOW)
    # #sistem keeps its own definition: every observation line, `ok` share
    assert q["h24"] == {"frames": 2, "frames_ok_pct": 50.0, "rows": 5, "rows_ok_pct": 40.0}
    assert q["d7"]["frames"] == 5


@pytest.fixture
def client(store):
    s = Settings(db_path=store.path, source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract",
                 poller_enabled=False, last_image_path=None)
    with TestClient(create_app(s, start_poller=False)) as c:
        yield c


def test_api_public_and_aggregate_only(client):
    r = client.get("/api/stats/read-errors")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {"windows", "data", "generated_at", "cache_ttl_s"}
    assert set(d["data"]) == set(d["windows"])
    keys = {"frames", "frames_failed", "rows", "rows_unread", "rows_partial", "ghosts", "error_rate_pct"}
    assert all(set(v) == keys for v in d["data"].values())
    body = json.dumps(d)
    for bad in ("SECRET", "path", "image", "hash", "ip", "train_no", "infofer"):
        assert bad not in body, bad


# ---- front-end (static) ---------------------------------------------------------------------

def test_js_static_rules():
    js = (WEB / "stat_read_errors.js").read_text(encoding="utf-8")
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", 'setAttribute("style"', "cssText"):
        assert bad not in js, bad
    assert "/api/stats/read-errors" in js and "caption" in js and 'scope = "col"' in js
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", js)


def test_lazy_not_in_shell_and_wired():
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    shell = re.search(r"var SHELL = \[(.*?)\];", sw, re.S).group(1)
    assert "stat_read_errors" not in shell
    assert "stat_read_errors" not in (WEB / "index.html").read_text(encoding="utf-8")
    st = (WEB / "statistici.js").read_text(encoding="utf-8")
    assert "stat_read_errors.js" in st and "App.statReadErrors" in st
