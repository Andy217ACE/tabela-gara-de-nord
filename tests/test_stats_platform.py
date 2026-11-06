# © 2026 Andy217Ace
"""Statistici — „Peroane schimbate după anunț” (app.stats_platform).
Reguli: schimbarea se deduce din valorile DISTINCTE de peron per serviciu (events 'platform');
valorile ne-numerice sau în afara 1..PLATFORM_MAX se ignoră (OCR); eșantion mic = mențiune."""
from datetime import date

import re

import pytest
from fastapi.testclient import TestClient

from app import stats_platform as sp
from app.api import create_app
from app.config import Settings
from app.store import Store


def svc(sid, no, station, values, board="arrival", ttype="IR"):
    return {"id": sid, "board": board, "train_type": ttype, "train_no": no,
            "station": station, "values": values}


# ---- clean_values ---------------------------------------------------------------------------

def test_clean_values_drops_garbage_and_out_of_range():
    vals, ign = sp.clean_values(["6", "x", "", None, "0", "15", "4", " 11 "])
    assert vals == [6, 4, 11] and ign == 5


def test_clean_values_collapses_consecutive_duplicates():
    vals, _ = sp.clean_values(["6", "6", "4", "4", "6"])
    assert vals == [6, 4, 6]


# ---- transitions ----------------------------------------------------------------------------

def test_transitions_consecutive_pairs():
    assert sp.transitions([6, 4]) == [(6, 4)]
    assert sp.transitions([6, 4, 3]) == [(6, 4), (4, 3)]
    assert sp.transitions([5]) == [] and sp.transitions([]) == []


# ---- compute --------------------------------------------------------------------------------

def sample():
    s = []
    for i in range(30):                      # 30 servicii cu peron stabil
        s.append(svc(i, 1000 + i, "BRASOV", ["3"]))
    s.append(svc(100, 9103, "TARGOVISTE", ["6", "4"], board="departure"))
    s.append(svc(101, 9103, "TARGOVISTE", ["6", "4"], board="departure"))
    s.append(svc(102, 7911, "AEROPORT H COANDA", ["11", "9"]))
    s.append(svc(103, 2000, "CLUJ", ["x", "99"]))          # numai gunoi: nu are peron valid
    s.append(svc(104, 2001, "CLUJ", []))                   # fără eveniment de peron
    return s


def test_compute_counts_and_percent():
    d = sp.compute(sample(), min_sample=5)
    assert d["status"] == "ok"
    assert d["n_with_platform"] == 33 and d["n_changed"] == 3
    assert d["pct_changed"] == pytest.approx(9.1, abs=0.05)
    assert d["ignored_values"] == 2
    assert d["small_sample"] is True      # doar 3 schimbări (< SMALL_CHANGED)


def test_compute_pairs_and_tops():
    d = sp.compute(sample(), min_sample=5)
    assert d["pairs"][0] == {"from": 6, "to": 4, "n": 2}
    assert {"from": 11, "to": 9, "n": 1} in d["pairs"]
    t = d["trains"][0]
    assert t["train_no"] == 9103 and t["changed"] == 2 and t["seen"] == 2
    assert t["station"] == "TARGOVISTE" and t["pair"] == {"from": 6, "to": 4}
    assert d["stations"][0]["station"] == "TARGOVISTE" and d["stations"][0]["changed"] == 2


def test_compute_by_board_keeps_boards_separate():
    d = sp.compute(sample(), min_sample=5)
    assert d["boards"]["departure"] == {"n": 2, "changed": 2, "pct": None}  # n < min_sample
    assert d["boards"]["arrival"]["n"] == 31 and d["boards"]["arrival"]["changed"] == 1


def test_small_sample_withholds_percent_and_flags():
    d = sp.compute([svc(1, 9103, "TARGOVISTE", ["6", "4"]), svc(2, 1, "X", ["3"])], min_sample=5)
    assert d["small_sample"] is True and d["pct_changed"] is None
    assert d["n_changed"] == 1 and d["n_with_platform"] == 2


def test_empty():
    d = sp.compute([], min_sample=5)
    assert d["status"] == "empty" and d["n_with_platform"] == 0 and d["trains"] == []


def test_returning_to_first_platform_counts_as_changed():
    d = sp.compute([svc(1, 5, "X", ["3", "4", "3"])] * 1, min_sample=1)
    assert d["n_changed"] == 1
    assert {(p["from"], p["to"]) for p in d["pairs"]} == {(3, 4), (4, 3)}


# ---- DB + API -------------------------------------------------------------------------------

def add(c, board, no, day, station, platforms, ttype="IR"):
    sid = c.execute(
        "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
        " sched_time, first_seen, last_seen, status) VALUES (?,?,?,?,?,?,?,?,?,'gone')",
        (board, f"2026-10-{day:02d}", ttype, no, station, "CFR", "10:00",
         f"2026-10-{day:02d}T09:00:00+03:00", f"2026-10-{day:02d}T10:00:00+03:00")).lastrowid
    for i, p in enumerate(platforms):
        c.execute("INSERT INTO events(service_id, ts, kind, old, new) VALUES (?,?,'platform',NULL,?)",
                  (sid, f"2026-10-{day:02d}T09:{10 + i}:00+03:00", p))
    return sid


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.migrate()
    c = s._conn
    add(c, "departure", 9103, 14, "TARGOVISTE", ["6", "4"])
    add(c, "arrival", 7911, 14, "AEROPORT H COANDA", ["11", "9"])
    add(c, "arrival", 1621, 14, "BRASOV", ["3"])
    add(c, "arrival", 1621, 1, "BRASOV", ["3", "5"])        # veche, în afara perioadei
    c.commit()
    yield s
    s.close()


def test_fetch_and_filters(store):
    rows = sp.fetch(store, None, None, None)
    assert len(rows) == 4
    byno = {(r["train_no"], r["id"]): r for r in rows}
    assert any(r["train_no"] == 9103 and r["values"] == ["6", "4"] for r in rows)
    assert len(sp.fetch(store, date(2026, 10, 10), None, None)) == 3
    assert len(sp.fetch(store, None, None, "departure")) == 1
    assert byno


@pytest.fixture
def client(store):
    s = Settings(db_path=store.path, source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract",
                 poller_enabled=False, last_image_path=None)
    with TestClient(create_app(s, start_poller=False)) as c:
        yield c


def test_api_platform_changes(client):
    r = client.get("/api/stats/platform-changes")
    assert r.status_code == 200
    d = r.json()
    assert d["n_with_platform"] == 4 and d["n_changed"] == 3
    assert d["small_sample"] is True and d["pct_changed"] is None
    assert d["trains"][0]["train_no"] in (9103, 7911, 1621)


def test_api_platform_changes_filters_and_errors(client):
    assert client.get("/api/stats/platform-changes?board=departure").json()["n_changed"] == 1
    assert client.get("/api/stats/platform-changes?perioada=zzz").status_code == 422
    assert client.get("/api/stats/platform-changes?board=x").status_code == 422


def test_enough_data_is_not_small_sample():
    s = [svc(i, 100 + i, "X", ["3", "4"] if i < 6 else ["3"]) for i in range(40)]
    d = sp.compute(s, min_sample=5)
    assert d["small_sample"] is False and d["pct_changed"] == 15.0


# ---- front-end (static) ---------------------------------------------------------------------

from pathlib import Path  # noqa: E402

WEB = Path(__file__).resolve().parent.parent / "web"


def test_platform_js_static_rules():
    js = (WEB / "stat_platform.js").read_text(encoding="utf-8")
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", 'setAttribute("style"', "cssText", '"style"'):
        assert bad not in js, bad
    assert "/api/stats/platform-changes" in js and "App.statsExtra" in js and "textContent" in js
    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", js)       # fără culori fixe (teme light/dark)


def test_platform_wired_in_index_sw_and_statistici():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert '<script src="stat_platform.js" defer></script>' in html
    assert html.index('src="statistici.js"') < html.index('src="stat_platform.js"')
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    assert '"/stat_platform.js"' in sw[sw.index("var SHELL"):sw.index("];", sw.index("var SHELL"))]
    assert "App.statsExtra" in (WEB / "statistici.js").read_text(encoding="utf-8")


def test_platform_js_served():
    s = Settings(db_path=":memory:", source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract")
    with TestClient(create_app(s, start_poller=False)) as c:
        r = c.get("/stat_platform.js")
        assert r.status_code == 200 and "Andy217Ace" in r.text
