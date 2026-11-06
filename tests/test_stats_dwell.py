# © 2026 Andy217Ace
"""Statistici — „Cât stă trenul pe panou” (app.stats_dwell): durata first_seen → last_seen a
serviciilor 'gone'. Mediană ȘI medie; sosiri vs plecări separate; top pe tip/stație cu grup minim."""
import re

import pytest
from fastapi.testclient import TestClient

from app import stats_dwell as sd
from app.api import create_app
from app.config import Settings
from app.store import Store


def row(board, ttype, station, minutes, no=1):
    return {"board": board, "train_type": ttype, "train_no": no, "station": station,
            "minutes": minutes}


# ---- minutes_between ------------------------------------------------------------------------

def test_minutes_between_iso():
    assert sd.minutes_between("2026-10-14T09:00:00+03:00", "2026-10-14T10:30:00+03:00") == 90.0


def test_minutes_between_rejects_bad_negative_and_huge():
    assert sd.minutes_between("zzz", "2026-10-14T10:30:00+03:00") is None
    assert sd.minutes_between("2026-10-14T10:30:00+03:00", "2026-10-14T09:00:00+03:00") is None
    assert sd.minutes_between("2026-10-14T00:00:00+03:00", "2026-10-16T00:00:00+03:00") is None


# ---- summarize ------------------------------------------------------------------------------

def test_summarize_median_and_mean_differ_on_outlier():
    s = sd.summarize([10, 20, 30, 40, 600])
    assert s["n"] == 5 and s["median"] == 30 and s["mean"] == 140 and s["p90"] is not None


def test_summarize_empty():
    assert sd.summarize([]) == {"n": 0, "median": None, "mean": None, "p90": None}


# ---- compute --------------------------------------------------------------------------------

def sample():
    r = []
    for m in (30, 40, 50, 60, 70, 80):
        r.append(row("arrival", "IR", "BRASOV", m, no=100 + m))
    for m in (100, 110, 120, 130, 140):
        r.append(row("departure", "R", "PLOIESTI", m, no=200 + m))
    r.append(row("departure", "R", "RARA", 500, no=1))     # grup mic (1 serviciu)
    return r


def test_compute_by_board():
    d = sd.compute(sample(), min_group=5)
    assert d["n"] == 12 and d["status"] == "ok"
    assert d["boards"]["arrival"]["median"] == 55 and d["boards"]["arrival"]["n"] == 6
    assert d["boards"]["departure"]["median"] == 125 and d["boards"]["departure"]["n"] == 6
    assert d["boards"]["departure"]["mean"] == pytest.approx(183.3, abs=0.1)


def test_compute_groups_filtered_by_min_and_sorted_by_n():
    d = sd.compute(sample(), min_group=5)
    assert [g["train_type"] for g in d["types"]] == ["IR", "R"]
    assert d["types"][1]["n"] == 6        # PLOIESTI(5) + RARA(1)
    assert [g["station"] for g in d["stations"]] == ["BRASOV", "PLOIESTI"]
    assert d["small_groups_omitted"] == 1  # RARA


def test_compute_empty_and_disclaimer():
    d = sd.compute([], min_group=5)
    assert d["status"] == "empty" and d["n"] == 0
    assert "orarul real" in d["note"]


# ---- DB + API -------------------------------------------------------------------------------

def add(c, board, no, ttype, station, first, last, status="gone"):
    c.execute("INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
              " sched_time, first_seen, last_seen, status) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (board, first[:10], ttype, no, station, "CFR", "10:00", first, last, status))


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.migrate()
    c = s._conn
    add(c, "arrival", 1, "IR", "BRASOV", "2026-10-14T09:00:00+03:00", "2026-10-14T10:00:00+03:00")
    add(c, "arrival", 2, "IR", "BRASOV", "2026-10-14T09:00:00+03:00", "2026-10-14T11:00:00+03:00")
    add(c, "departure", 3, "R", "PLOIESTI", "2026-10-14T09:00:00+03:00", "2026-10-14T09:30:00+03:00")
    add(c, "departure", 4, "R", "PLOIESTI", "2026-10-14T09:00:00+03:00", "2026-10-14T09:30:00+03:00",
        status="listed")                                   # încă pe panou: exclus
    c.commit()
    yield s
    s.close()


def test_fetch_only_gone(store):
    rows = sd.fetch(store, None, None, None)
    assert sorted(r["minutes"] for r in rows) == [30.0, 60.0, 120.0]
    assert len(sd.fetch(store, None, None, "arrival")) == 2


@pytest.fixture
def client(store):
    s = Settings(db_path=store.path, source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract",
                 poller_enabled=False, last_image_path=None)
    with TestClient(create_app(s, start_poller=False)) as c:
        yield c


def test_api_dwell(client):
    d = client.get("/api/stats/dwell").json()
    assert d["n"] == 3 and d["boards"]["arrival"]["median"] == 90
    assert client.get("/api/stats/dwell?board=departure").json()["n"] == 1
    assert client.get("/api/stats/dwell?perioada=zzz").status_code == 422


# ---- front-end (static) ---------------------------------------------------------------------

from pathlib import Path  # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "web"


def test_dwell_js_static_rules():
    js = (WEB / "stat_dwell.js").read_text(encoding="utf-8")
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", 'setAttribute("style"', "cssText", '"style"'):
        assert bad not in js, bad
    assert "/api/stats/dwell" in js and "App.statsExtra" in js and "textContent" in js
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", js)       # fără culori fixe (teme light/dark)


def test_dwell_wired_in_index_sw_and_statistici():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<script src="stat_dwell.js" defer></script>' in html
    assert html.index('src="statistici.js"') < html.index('src="stat_dwell.js"')
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    assert '"/stat_dwell.js"' in sw[sw.index("var SHELL"):sw.index("];", sw.index("var SHELL"))]
    assert "App.statsExtra" in (WEB / "statistici.js").read_text(encoding="utf-8")


def test_dwell_js_served():
    s = Settings(db_path=":memory:", source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract")
    with TestClient(create_app(s, start_poller=False)) as c:
        r = c.get("/stat_dwell.js")
        assert r.status_code == 200 and "Andy217Ace" in r.text
