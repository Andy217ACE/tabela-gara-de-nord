# © 2026 Andy217Ace
"""Manual corrections from the admin (schema v9): validation, rules on new frames,
retroactive plan/apply/restore, backup-aware migration, admin API (auth + CSRF + audit),
no leaks in the public API."""
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import admin, corrections, dbbackup
from app.api import create_app
from app.config import Settings
from app.corrections import CorrectionError
from app.models import Row
from app.observations import line_version, parse_line_version
from app.store import SCHEMA_VERSION, Store

BUC = ZoneInfo("Europe/Bucharest")
TOKEN = "t" * 20 + "-secret-admin-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
WHEN = datetime(2026, 10, 27, 12, 0, tzinfo=BUC)
D1, D2 = "2026-10-26", "2026-10-27"


def _mem():
    s = Store(":memory:")
    s.migrate()
    return s


def rule(**kw):
    base = dict(board="departure", field="no", wrong_value="1584", correct_value="1581",
                note="Numărul real e 1581 (cadrul 123)")
    base.update(kw)
    return base


def row(no=1584, ttype="IR", station="BRASOV", sched="08:10", board="departure", **kw):
    return Row(board=board, train_type=ttype, train_no=no, station=station, operator="CFR",
               sched_time=sched, **kw)


# -- validation -------------------------------------------------------------------------------

def test_validate_ok_normalises():
    r = corrections.validate_rule(rule(station=" brașov ", sched_time="8:10",
                                       date_from="2026-10-01", date_to="2026-10-31"))
    assert r["station"] == "BRASOV" and r["sched_time"] == "08:10"
    assert r["wrong_value"] == "1584" and r["correct_value"] == "1581"


@pytest.mark.parametrize("bad", [
    rule(board="x"), rule(field="nope"), rule(wrong_value="abc"), rule(correct_value=""),
    rule(correct_value="1584"), rule(note=""), rule(note="ab"), rule(note="x" * 501),
    rule(sched_time="25:00"), rule(date_from="2026-13-01"),
    rule(date_from="2026-10-31", date_to="2026-10-01"), rule(extra=1),
    rule(correct_value="99999999"), rule(wrong_value="1584\x00"),
    rule(field="type", wrong_value="IR", correct_value="XYZ"),
    rule(field="station", wrong_value="A", correct_value="B<script>"),
    rule(field="delay", wrong_value="1", correct_value="9999"),
    rule(field="time", wrong_value="1:1", correct_value="08:10"),
])
def test_validate_rejects(bad):
    with pytest.raises(CorrectionError) as e:
        corrections.validate_rule(bad)
    assert e.value.status == 422


def test_validate_rejects_non_dict():
    with pytest.raises(CorrectionError):
        corrections.validate_rule(["x"])


def test_unread_is_valid_only_as_wrong_platform_or_delay():
    r = corrections.validate_rule(rule(field="platform", wrong_value="", correct_value="3"))
    assert r["wrong_value"] == ""  # "not read" is not 0
    with pytest.raises(CorrectionError):
        corrections.validate_rule(rule(field="no", wrong_value="", correct_value="3"))
    with pytest.raises(CorrectionError):
        corrections.validate_rule(rule(field="platform", wrong_value="2", correct_value=""))


# -- new frames --------------------------------------------------------------------------------

def test_correct_row_real_examples_and_scope():
    r1 = corrections.validate_rule(rule())  # IR 1584 -> 1581 (departures)
    r2 = corrections.validate_rule(rule(board="arrival", wrong_value="7911", correct_value="7914",
                                        station="CONSTANTA", note="7914 pe sosiri Constanța"))
    r1["id"], r2["id"] = 1, 2
    rules = [r1, r2]
    new, ap = corrections.correct_row(row(), rules, WHEN)
    assert new.train_no == 1581 and ap == [{"id": 1, "field": "no", "from": "1584", "to": "1581"}]
    assert corrections.correct_row(row(board="arrival"), rules, WHEN)[1] == []
    assert corrections.correct_row(row(no=1585), rules, WHEN)[1] == []
    a = row(no=7911, board="arrival", station="CONSTANTA")
    assert corrections.correct_row(a, rules, WHEN)[0].train_no == 7914
    assert corrections.correct_row(row(no=7911, board="arrival", station="BRASOV"),
                                   rules, WHEN)[1] == []


def test_date_and_time_limits():
    r = corrections.validate_rule(rule(sched_time="08:10", date_from=D2, date_to=D2))
    r["id"] = 3
    assert corrections.correct_row(row(), [r], WHEN)[1]
    assert not corrections.correct_row(row(sched="09:10"), [r], WHEN)[1]
    assert not corrections.correct_row(row(), [r], datetime(2026, 10, 28, 12, tzinfo=BUC))[1]


def test_delay_and_platform_unread_markers():
    rd = corrections.validate_rule(rule(field="delay", wrong_value="65", correct_value="5"))
    rd["id"] = 1
    new, ap = corrections.correct_row(row(delay_min=65, delay_read=True), [rd], WHEN)
    assert new.delay_min == 5 and ap
    assert not corrections.correct_row(row(delay_min=65, delay_read=False), [rd], WHEN)[1]
    rp = corrections.validate_rule(rule(field="platform", wrong_value="", correct_value="4"))
    rp["id"] = 2
    assert corrections.correct_row(row(platform=None), [rp], WHEN)[0].platform == 4
    assert not corrections.correct_row(row(platform=0), [rp], WHEN)[1]


def test_marker_in_line_version_roundtrip():
    v = line_version("t", {"state": "ok", "corr": [7, 9]})
    assert v.endswith("+corr:7+corr:9")
    assert parse_line_version(v)["corr"] == [7, 9]
    assert "corr" not in parse_line_version(line_version("t", {"state": "ok"}))


def test_correct_frame_marks_debug_and_keeps_raw():
    s = _mem()
    corrections.create_rule(s, corrections.validate_rule(rule()))
    entry = {"row": row(), "state": "ok",
             "fields": {"no": {"raw": "1584", "norm": "1584", "conf": 90}}}
    rows, dbg = corrections.correct_frame(s, [row()], [entry], WHEN)
    assert rows[0].train_no == 1581
    assert dbg[0]["corr"] == [1] and dbg[0]["row"].train_no == 1581
    assert dbg[0]["fields"]["no"]["raw"] == "1584"  # OCR evidence stays
    assert dbg[0]["fields"]["no"]["corr"]["to"] == "1581"
    assert entry["fields"]["no"].get("corr") is None  # input not mutated
    r2, d2 = corrections.correct_frame(s, [row(no=5)], [{"row": row(no=5)}], WHEN)
    assert r2[0].train_no == 5 and "corr" not in d2[0]


def test_deleted_rule_stops_acting():
    s = _mem()
    made = corrections.create_rule(s, corrections.validate_rule(rule()))
    corrections.soft_delete(s, made["id"])
    assert corrections.correct_rows(s, [row()], WHEN)[0].train_no == 1584


def test_duplicate_active_rule_refused():
    s = _mem()
    corrections.create_rule(s, corrections.validate_rule(rule()))
    with pytest.raises(CorrectionError) as e:
        corrections.create_rule(s, corrections.validate_rule(rule(note="altă notă")))
    assert e.value.status == 409


# -- retroactive ---------------------------------------------------------------------------------

def _svc(c, board, day, no, station, sched, *, ttype="IR", delay=0, delay_read_at=None,
         platform=None):
    sid = c.execute(
        "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
        " sched_time, first_seen, last_seen, last_delay, last_platform, status, station_raw,"
        " operator_raw, last_read, delay_read_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (board, day, ttype, no, station, "CFR", sched, f"{day}T07:00:00+03:00",
         f"{day}T08:00:00+03:00", delay, platform, "gone", station, "", None,
         delay_read_at)).lastrowid
    cap = c.execute("INSERT INTO captures(captured_at, image_hash, ok) VALUES (?,?,1)",
                    (f"{day}T07:00:00+03:00", f"h{sid}")).lastrowid
    c.execute("INSERT INTO observations(capture_id, service_id, board, row_index, observed_at,"
              " train_no, station, sched_time, delay_min, delay_read, platform,"
              " validation_state, processing_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,'ok','t')",
              (cap, sid, board, 0, f"{day}T07:00:00+03:00", no, station, sched, delay,
               1 if delay_read_at else 0, platform))
    c.execute("INSERT OR IGNORE INTO trains(train_no, journeys, observations) VALUES (?,1,1)",
              (no,))
    return sid


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    s = Store(path)
    s.migrate()
    c = s._conn
    ids = {
        "a": _svc(c, "departure", D1, 1584, "BRASOV", "08:10"),
        "b": _svc(c, "departure", D2, 1584, "BRASOV", "08:10"),
        "other_board": _svc(c, "arrival", D2, 1584, "BRASOV", "08:10"),
        "other_no": _svc(c, "departure", D2, 1585, "BRASOV", "09:10"),
        "d": _svc(c, "arrival", D2, 7911, "CONSTANTA", "10:00", ttype="IRN"),
    }
    yield s, ids
    s.close()


def _snapshot(path):
    c = sqlite3.connect(path)
    out = {t: c.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
           for t in ("services", "observations", "events", "trains", "captures")}
    c.close()
    return out


def test_preview_is_dry_run_and_apply_restore_roundtrip(db):
    s, ids = db
    r = corrections.create_rule(s, corrections.validate_rule(rule()))
    before = _snapshot(s.path)
    pv = corrections.preview(s, r)
    assert pv["services"]["count"] == 2 and pv["observations"]["count"] == 2
    assert {x["id"] for x in pv["services"]["sample"]} == {ids["a"], ids["b"]}
    assert _snapshot(s.path) == before  # the dry run wrote nothing
    with pytest.raises(CorrectionError) as e:
        corrections.apply(s, r["id"], "0" * 16)
    assert e.value.status == 409 and _snapshot(s.path) == before
    out = corrections.apply(s, r["id"], pv["plan_hash"], ip="1.2.3.4")
    assert out["services"] == 2 and out["observations"] == 2
    c = s._conn
    assert {x[0] for x in c.execute("SELECT train_no FROM services WHERE id IN (?,?)",
                                    (ids["a"], ids["b"]))} == {1581}
    assert c.execute("SELECT train_no FROM services WHERE id=?",
                     (ids["other_board"],)).fetchone()[0] == 1584
    assert c.execute("SELECT train_no FROM services WHERE id=?",
                     (ids["other_no"],)).fetchone()[0] == 1585
    pvs = [x[0] for x in c.execute("SELECT processing_version FROM observations"
                                   " WHERE train_no=1581")]
    assert pvs and all(v.endswith(f"+corr:{r['id']}") for v in pvs)
    with pytest.raises(CorrectionError):  # nothing left to apply
        corrections.apply(s, r["id"], corrections.preview(s, r)["plan_hash"])
    back = corrections.restore(s, out["batch"], ip="1.2.3.4")
    assert back["services"] == 2 and back["observations"] == 2 and back["skipped"] == 0
    after = _snapshot(s.path)
    assert after["services"] == before["services"]
    assert after["observations"] == before["observations"]
    with pytest.raises(CorrectionError) as e:
        corrections.restore(s, out["batch"])
    assert e.value.status == 409
    acts = [a["action"] for a in corrections.audit_log(s)]
    assert acts[:3] == ["restore", "apply", "create"]


def test_scope_station_and_days_narrow_the_plan(db):
    s, ids = db
    r = corrections.create_rule(s, corrections.validate_rule(
        rule(station="brasov", date_from=D2, date_to=D2)))
    pv = corrections.preview(s, r)
    assert [x["id"] for x in pv["services"]["sample"]] == [ids["b"]]
    assert corrections.preview(s, corrections.validate_rule(rule(station="SIBIU")))["empty"]


def test_real_example_7911_to_7914(db):
    s, ids = db
    r = corrections.create_rule(s, corrections.validate_rule(
        rule(board="arrival", wrong_value="7911", correct_value="7914", note="IRN 7914")))
    corrections.apply(s, r["id"], corrections.preview(s, r)["plan_hash"])
    assert s._conn.execute("SELECT train_no FROM services WHERE id=?",
                           (ids["d"],)).fetchone()[0] == 7914


def test_conflict_is_listed_not_changed(db):
    s, ids = db
    _svc(s._conn, "departure", D2, 1581, "BRASOV", "08:10")  # the right number already exists
    r = corrections.create_rule(s, corrections.validate_rule(rule(date_from=D2)))
    pv = corrections.preview(s, r)
    assert pv["conflicts"]["count"] == 1 and pv["services"]["count"] == 0
    assert pv["empty"]


def test_delay_unread_vs_zero(db):
    s, ids = db
    c = s._conn
    zero = _svc(c, "departure", D2, 2000, "SIBIU", "11:00", delay=0,
                delay_read_at=f"{D2}T07:00:00+03:00")
    unread = _svc(c, "departure", D2, 2001, "SIBIU", "11:10", delay=0)
    r = corrections.create_rule(s, corrections.validate_rule(
        rule(field="delay", wrong_value="0", correct_value="5", note="citit 0, real +5")))
    pv = corrections.preview(s, r)
    assert [x["id"] for x in pv["services"]["sample"]] == [zero]  # unread ≠ 0
    r2 = corrections.validate_rule(rule(field="delay", wrong_value="", correct_value="5"))
    assert unread in [x["id"] for x in corrections.preview(s, r2)["services"]["sample"]]


def test_delete_with_applied_batch_needs_restore(db):
    s, ids = db
    r = corrections.create_rule(s, corrections.validate_rule(rule()))
    corrections.apply(s, r["id"], corrections.preview(s, r)["plan_hash"])
    with pytest.raises(CorrectionError) as e:
        corrections.soft_delete(s, r["id"])
    assert e.value.status == 409
    out = corrections.soft_delete(s, r["id"], restore_batches=True)
    assert out["status"] == "deleted" and len(out["restored"]) == 1
    assert s._conn.execute("SELECT train_no FROM services WHERE id=?",
                           (ids["a"],)).fetchone()[0] == 1584
    assert s._conn.execute("SELECT status FROM corrections WHERE id=?",
                           (r["id"],)).fetchone()[0] == "deleted"  # soft delete


# -- migration -------------------------------------------------------------------------------------

def test_schema_is_v9_with_tables():
    assert SCHEMA_VERSION == 9
    s = _mem()
    names = {r[0] for r in s._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"corrections", "correction_batches", "correction_archive",
            "correction_audit"} <= names


def test_migration_v8_to_v9_takes_backup_first(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "bk"))
    path = str(tmp_path / "t.db")
    s = Store(path)
    s.migrate()
    _svc(s._conn, "departure", D2, 1584, "BRASOV", "08:10")
    s.close()
    c = sqlite3.connect(path)
    for t in ("correction_audit", "correction_archive", "correction_batches", "corrections"):
        c.execute(f"DROP TABLE {t}")
    c.execute("PRAGMA user_version = 8")
    c.commit()
    c.close()
    s = Store(path)
    s.migrate()
    assert s._conn.execute("PRAGMA user_version").fetchone()[0] == 9
    bks = list((tmp_path / "bk").glob("tabela-*-v8.db"))
    assert len(bks) == 1
    b = sqlite3.connect(bks[0])
    assert b.execute("PRAGMA user_version").fetchone()[0] == 8
    assert b.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 1
    b.close()
    assert dbbackup.recent_backup(path, 8) == bks[0]
    s.close()
    s2 = Store(path)
    s2.migrate()
    s2.close()  # already v9: no second backup
    assert len(list((tmp_path / "bk").glob("*.db"))) == 1


# -- admin API -------------------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("CAPTURE_DIR", str(tmp_path / "captures"))
    monkeypatch.setattr(admin, "FAIL_DELAY_S", 0.0)
    admin.reset_failures()
    st = Settings(db_path=":memory:", source_url="https://example.com/x", vapid_private_key="",
                  vapid_public_key="", vapid_subject="mailto:a@b.c",
                  tesseract_cmd="tesseract-does-not-exist", poller_restart_backoff=0.01)
    with TestClient(create_app(st, start_poller=False), base_url="https://testserver") as c:
        yield c
    admin.reset_failures()


def test_requires_admin(client):
    for method, path in (("get", ""), ("get", "/audit"), ("post", ""), ("post", "/preview"),
                         ("post", "/1/apply"), ("delete", "/1"),
                         ("post", "/batches/x/restore")):
        r = getattr(client, method)("/api/admin/corrections" + path)
        assert r.status_code == 401, (method, path)


def test_disabled_without_token(client, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN")
    assert client.get("/api/admin/corrections", headers=AUTH).status_code == 503


def test_cookie_session_needs_csrf(client):
    assert client.post("/api/admin/login", json={"token": TOKEN}).status_code == 200
    assert client.post("/api/admin/corrections", json=rule()).status_code == 403
    r = client.post("/api/admin/corrections", json=rule(), headers={"X-CSRF-Token": "bad"})
    assert r.status_code == 403
    good = client.get("/api/admin/csrf").json()["token"]
    assert len(good) == 64
    r = client.post("/api/admin/corrections", json=rule(),
                    headers={"X-CSRF-Token": good, "Origin": "https://evil.example"})
    assert r.status_code == 403  # foreign Origin even with a valid token
    r = client.post("/api/admin/corrections", json=rule(),
                    headers={"X-CSRF-Token": good, "Origin": "https://testserver"})
    assert r.status_code == 201
    assert client.get("/api/admin/corrections").status_code == 200  # reads need no token


def test_bearer_needs_no_csrf_and_full_flow(client):
    r = client.post("/api/admin/corrections/preview", json=rule(), headers=AUTH)
    assert r.status_code == 200 and r.json()["preview"]["empty"] is True
    r = client.post("/api/admin/corrections", json=rule(), headers=AUTH)
    assert r.status_code == 201
    rid = r.json()["correction"]["id"]
    assert client.post("/api/admin/corrections", json=rule(), headers=AUTH).status_code == 409
    assert client.post("/api/admin/corrections", json=rule(wrong_value="x"),
                       headers=AUTH).status_code == 422
    listed = client.get("/api/admin/corrections", headers=AUTH).json()["corrections"]
    assert [x["id"] for x in listed] == [rid] and listed[0]["note"].startswith("Numărul")
    assert client.post(f"/api/admin/corrections/{rid}/apply", json={},
                       headers=AUTH).status_code == 422
    assert client.post(f"/api/admin/corrections/{rid}/apply", json={"plan_hash": "0" * 16},
                       headers=AUTH).status_code == 409
    assert client.post("/api/admin/corrections/999/preview", headers=AUTH).status_code == 404
    assert client.post("/api/admin/corrections/abc/preview", headers=AUTH).status_code == 422
    assert client.delete(f"/api/admin/corrections/{rid}", headers=AUTH).status_code == 200
    assert client.get("/api/admin/corrections", headers=AUTH).json()["corrections"] == []
    deleted = client.get("/api/admin/corrections?status=deleted", headers=AUTH).json()
    assert deleted["corrections"][0]["status"] == "deleted"
    audit = client.get("/api/admin/corrections/audit", headers=AUTH).json()["audit"]
    assert [a["action"] for a in audit] == ["delete", "create"]
    assert client.get("/api/admin/corrections?status=zzz", headers=AUTH).status_code == 422


def test_oversized_or_bad_body(client):
    assert client.post("/api/admin/corrections", content=b"x" * 9000, headers=AUTH
                       ).status_code == 413
    assert client.post("/api/admin/corrections", content=b"{not json", headers=AUTH
                       ).status_code == 422
    assert client.post("/api/admin/corrections", content=b"[1]", headers=AUTH
                       ).status_code == 422


def test_end_to_end_apply_via_api(client):
    store = client.app.state.store
    sid = _svc(store._conn, "departure", D2, 1584, "BRASOV", "08:10")
    rid = client.post("/api/admin/corrections", json=rule(), headers=AUTH
                      ).json()["correction"]["id"]
    pv = client.post(f"/api/admin/corrections/{rid}/preview", headers=AUTH).json()["preview"]
    assert pv["services"]["count"] == 1
    out = client.post(f"/api/admin/corrections/{rid}/apply",
                      json={"plan_hash": pv["plan_hash"]}, headers=AUTH).json()
    assert store._conn.execute("SELECT train_no FROM services WHERE id=?",
                               (sid,)).fetchone()[0] == 1581
    r = client.post(f"/api/admin/corrections/batches/{out['batch']}/restore", headers=AUTH)
    assert r.status_code == 200 and r.json()["services"] == 1
    assert client.post("/api/admin/corrections/batches/a%20b/restore",
                       headers=AUTH).status_code in (404, 422)


def test_no_leak_in_public_api(client):
    store = client.app.state.store
    _svc(store._conn, "departure", D2, 1584, "BRASOV", "08:10")
    rid = client.post("/api/admin/corrections", json=rule(note="NOTA-SECRETA-123"),
                      headers=AUTH).json()["correction"]["id"]
    pv = client.post(f"/api/admin/corrections/{rid}/preview", headers=AUTH).json()["preview"]
    client.post(f"/api/admin/corrections/{rid}/apply", json={"plan_hash": pv["plan_hash"]},
                headers=AUTH)
    public = ["/api/board", "/api/health", "/api/history?train=1581&all=1", "/api/trains",
              "/api/trains/1581/journeys", "/api/journeys", "/api/stats/overview",
              "/api/stations"]
    anon = TestClient(client.app, base_url="https://testserver")  # no cookie
    for p in public:
        text = anon.get(p).text
        assert "NOTA-SECRETA" not in text and "+corr" not in text and "correction" not in text, p
    paths = {getattr(r, "path", "") for r in client.app.routes}
    assert all(p.startswith("/api/admin/") for p in paths if "correction" in p)
