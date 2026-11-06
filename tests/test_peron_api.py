# © 2026 Andy217Ace
"""GET /api/predict/peron: estimări de peron etichetate, read-only, doar pentru trenuri
fără peron anunțat și doar peste pragul din backtest."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.store import TZ, Store


def _svc(c, sid, no, day, platform, status="gone", board="departure", station="Iași"):
    c.execute("INSERT INTO services(id, board, service_date, train_type, train_no, station,"
              " operator, sched_time, first_seen, last_seen, status, last_platform)"
              " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (sid, board, day, "R", no, station, "CFR", "10:00", day + "T09:00:00+03:00",
               day + "T10:00:00+03:00", status, platform))


def _obs(c, sid, no, platform, board="departure"):
    c.execute("INSERT INTO captures(captured_at, last_seen_at, image_hash, ok, n_rows,"
              " processing_version) VALUES ('2026-10-20T10:00:00+00:00',"
              " '2026-10-20T10:00:00+00:00', ?, 1, 1, 'test')", (f"h{sid}",))
    cid = c.execute("SELECT id FROM captures WHERE image_hash=?", (f"h{sid}",)).fetchone()[0]
    c.execute("INSERT INTO observations(capture_id, service_id, board, row_index, observed_at,"
              " train_no, sched_time, platform, station, validation_state, processing_version)"
              " VALUES (?,?,?,0,'',?,?,?,?,'ok','test')",
              (cid, sid, board, no, "10:00", platform, "Iași"))


@pytest.fixture
def client(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.migrate()
    c = s._conn
    today = datetime.now(TZ).date()
    for k in range(1, 7):  # 6 zile de istoric: tren 100 pe peron 4 (5 din 6 = 83%)
        d = (today - timedelta(days=k)).isoformat()
        _svc(c, k, 100, d, 4 if k != 6 else 6)
        _obs(c, k, 100, 4 if k != 6 else 6)
        _svc(c, 100 + k, 200, d, 3 if k % 2 else 5)  # tren instabil: sub prag
        _obs(c, 100 + k, 200, 3 if k % 2 else 5)
        _svc(c, 300 + k, 300, d, 4)  # istoric stabil, dar azi peronul e deja anunțat
        _obs(c, 300 + k, 300, 4)
    t = today.isoformat()
    _svc(c, 900, 100, t, None, status="listed")           # fără peron anunțat -> estimat
    _svc(c, 901, 200, t, None, status="listed")           # sub prag -> nimic
    _svc(c, 902, 300, t, 7, status="listed")               # peron anunțat -> fără estimare
    c.commit()
    st = Settings(db_path=s.path, source_url="https://example.com/x", vapid_private_key="",
                  vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract",
                  poller_enabled=False, last_image_path=None)
    with TestClient(create_app(st, start_poller=False)) as cl:
        yield cl
    s.close()


def test_estimates_only_for_unannounced_trains_above_threshold(client):
    d = client.get("/api/predict/peron").json()
    deps = d["estimates"]["departures"]
    assert [(e["train_no"], e["platform"], e["n"], e["share_pct"]) for e in deps] == [(100, 4, 6, 83)]
    assert d["estimates"]["arrivals"] == []


def test_response_carries_label_threshold_and_backtest_figures(client):
    d = client.get("/api/predict/peron").json()
    assert "estimare" in d["note"].lower() and "nu informație oficială CFR" in d["note"]
    assert d["threshold"] == {"min_n": 5, "min_share_pct": 80}
    assert d["backtest"]["accuracy_pct"] < 80  # cifra reală, nu inventată
    assert d["backtest"]["n"] >= 50


def test_endpoint_is_get_only_and_writes_nothing(client):
    assert client.post("/api/predict/peron").status_code in (404, 405)
    s = client.app.state.store
    before = s._conn.total_changes
    client.get("/api/predict/peron")
    assert s._conn.total_changes == before
