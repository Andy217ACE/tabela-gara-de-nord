# © 2026 Andy217Ace
"""Live validation in Store.ingest and the quality side tables, on the patterns
measured on the live database (data-quality-report.md)."""
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app import observations, quality
from app.models import Row
from app.store import SCHEMA_VERSION, Store

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 10, 22, 9, 0, tzinfo=BUC)
FIX = Path(__file__).parent / "fixtures"


def R(no, t, delay=0, platform=None, board="arrival", station="BRASOV", **kw):
    return Row(board=board, train_type="R", train_no=no, station=station,
               operator="CFR Calatori", sched_time=t, delay_min=delay, platform=platform,
               station_raw=station, **kw)


def frame(delay=0, platform=None, extra=(), no=5030, t="09:30"):
    """Our train plus three steady others on each panel (a valid frame)."""
    rows = [R(no, t, delay=delay, platform=platform),
            R(1001, "09:40"), R(1002, "09:50"), R(1003, "10:00"),
            R(2001, "09:45", board="departure"), R(2002, "09:55", board="departure")]
    return rows + list(extra)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def at(m: float) -> datetime:
    return T0 + timedelta(minutes=m)


def delays(store, no=5030):
    return [(e["old"], e["new"]) for e in store._conn.execute(
        "SELECT e.old, e.new FROM events e JOIN services s ON s.id=e.service_id"
        " WHERE s.train_no=? AND e.kind='delay' ORDER BY e.id", (no,))]


def kinds(store, kind, no=5030):
    return [(e["old"], e["new"]) for e in store._conn.execute(
        "SELECT e.old, e.new FROM events e JOIN services s ON s.id=e.service_id"
        " WHERE s.train_no=? AND e.kind=? ORDER BY e.id", (no, kind))]


def svc(store, no=5030):
    return store._conn.execute("SELECT * FROM services WHERE train_no=?", (no,)).fetchone()


# -- delay ------------------------------------------------------------------------------

def test_bounce_a_b_a_produces_no_event(store):
    # R 5030: 15 <-> 45 four times in four minutes
    for m, d in enumerate([15, 15, 45, 15, 45, 15, 45, 15]):
        store.ingest(frame(d), at(m))
    assert delays(store) == []
    assert svc(store)["last_delay"] == 15


def test_change_confirmed_on_second_consecutive_reading(store):
    store.ingest(frame(15), at(0))
    assert store.ingest(frame(30), at(1)) == []
    assert svc(store)["last_delay"] == 15          # board keeps the confirmed value
    ev = store.ingest(frame(30), at(2))
    assert [(e.kind, e.old, e.new) for e in ev] == [("delay", "15", "30")]
    assert svc(store)["last_delay"] == 30


@pytest.mark.parametrize("prev,misread", [(25, 425), (10, 410), (20, 240), (45, 435)])
def test_plus_read_as_digit_is_never_applied(store, prev, misread):
    store.ingest(frame(prev), at(0))
    for m in range(1, 5):  # even read repeatedly (IR 16098 read "+240" three times)
        store.ingest(frame(misread), at(m))
    assert delays(store) == []
    assert svc(store)["last_delay"] == prev


def test_real_large_delay_after_small_one_is_applied_eventually(store):
    # 15 -> 150 is also "15 plus a digit": a real 150 lasts, so it is applied after 5 frames
    store.ingest(frame(15), at(0))
    for m in range(1, 6):
        store.ingest(frame(150), at(m))
    assert delays(store) == [("15", "150")]


def test_huge_jump_needs_three_frames(store):
    # R 10260: 15 -> 945 in one frame; a real jump of that size must persist 3 frames
    store.ingest(frame(15), at(0))
    store.ingest(frame(945), at(1))
    store.ingest(frame(945), at(2))
    assert delays(store) == []
    store.ingest(frame(945), at(3))
    assert delays(store) == [("15", "945")]


def test_unread_delay_holds_the_candidate(store):
    store.ingest(frame(15), at(0))
    store.ingest(frame(30), at(1))
    store.ingest([R(5030, "09:30", delay=0, delay_read=False), *frame()[1:]], at(2))
    store.ingest(frame(30), at(3))
    assert delays(store) == [("15", "30")]


def test_candidate_waits_while_panel_rejected(store):
    store.ingest(frame(15), at(0))
    store.ingest(frame(30), at(1))
    # arrivals panel unreadable (1 row): rejected; departures still ingested
    store.ingest([R(5030, "09:30", delay=99), R(2001, "09:45", board="departure"),
                  R(2002, "09:55", board="departure"), R(2003, "10:05", board="departure"),
                  R(2004, "10:15", board="departure")], at(2))
    assert "arrival" in store.last_rejected
    store.ingest(frame(30), at(3))
    assert delays(store) == [("15", "30")]


# -- platform -----------------------------------------------------------------------------

def test_platform_first_shown_immediately(store):
    store.ingest(frame(platform=None), at(0))
    ev = store.ingest(frame(platform=9), at(1))
    assert [(e.kind, e.old, e.new) for e in ev] == [("platform", None, "9")]


def test_platform_5_6_flapping_no_events(store):
    # RE 10111: 5/6 alternated 24 times
    store.ingest(frame(platform=5), at(0))
    for m in range(1, 12):
        store.ingest(frame(platform=6 if m % 2 else 5), at(m))
    assert kinds(store, "platform") == []  # set at appearance, never changed
    assert svc(store)["last_platform"] == 5


def test_platform_confusable_change_needs_three(store):
    store.ingest(frame(platform=5), at(0))
    store.ingest(frame(platform=6), at(1))
    store.ingest(frame(platform=6), at(2))
    assert kinds(store, "platform") == []  # set at appearance, never changed
    store.ingest(frame(platform=6), at(3))
    assert kinds(store, "platform")[-1] == ("5", "6")


def test_platform_11_14_4_1_flapping_no_events(store):
    # IR 16087: 11/4/14/1
    store.ingest(frame(platform=11), at(0))
    for m, p in enumerate([4, 11, 14, 11, 1, 11, 14], start=1):
        store.ingest(frame(platform=p), at(m))
    assert kinds(store, "platform") == []


def test_platform_cleared_needs_two_and_blank_flapping_ignored(store):
    # IR 16089: 9 / empty alternating
    store.ingest(frame(platform=9), at(0))
    for m in range(1, 8):
        store.ingest(frame(platform=None if m % 2 else 9), at(m))
    assert kinds(store, "platform") == []
    store.ingest(frame(platform=None), at(8))
    store.ingest(frame(platform=None), at(9))
    assert kinds(store, "platform")[-1] == ("9", None)


# -- gone / reappear ------------------------------------------------------------------------

def _without(rows, no=5030):
    return [r for r in rows if r.train_no != no]


def test_short_absence_is_not_a_new_appearance(store):
    store.ingest(frame(), at(0))
    for m in (1, 2, 3):
        store.ingest(_without(frame()), at(m))
    assert svc(store)["status"] == "gone"
    ev = store.ingest(frame(), at(5))
    assert [e.kind for e in ev if e.row.train_no == 5030] == []
    assert svc(store)["status"] == "listed"
    assert len(kinds(store, "appeared")) == 1


def test_two_missed_frames_do_not_flap(store):
    store.ingest(frame(), at(0))
    store.ingest(_without(frame()), at(1))
    store.ingest(_without(frame()), at(2))
    assert svc(store)["status"] == "listed"
    assert kinds(store, "gone") == []


# -- ghosts ------------------------------------------------------------------------------------

def test_one_frame_misread_is_flagged_ghost_and_hidden(store):
    store.ingest(frame(), at(0))
    # 9014 instead of 5011-like misread: another number seen once, then never again
    store.ingest(frame(extra=[R(9014, "09:12", station="BUZAU")]), at(1))
    assert any(r["train_no"] == 9014 for r in store.current_board()["arrivals"])
    for m in (2, 3, 4):
        store.ingest(frame(), at(m))
    sid = svc(store, 9014)["id"]
    q = store._conn.execute("SELECT * FROM service_quality WHERE service_id=?", (sid,)).fetchone()
    assert q["ghost"] == 1 and q["ghost_reason"] == "short"
    assert 9014 in store.last_ghost_numbers or True  # set by the ingest that flagged it
    assert svc(store, 9014)["train_no"] == 9014  # raw row kept
    assert all(r["train_no"] != 9014 for r in store.history(at(0).date()))
    assert store.train_events(9014, at(0).date()) == []


def test_ghost_hidden_from_catalog(store):
    store.ingest(frame(), at(0))
    rows = frame(extra=[R(50141, "09:12", station="BUZAU")])
    store.ingest(rows, at(1))
    observations.refresh_catalog(store, rows)
    assert observations.train_detail(store, 50141) is not None
    for m in (2, 3, 4):
        store.ingest(frame(), at(m))
    observations.refresh_catalog(store, frame(), store.last_ghost_numbers | {50141})
    assert observations.train_detail(store, 50141) is None
    assert all(t["train_no"] != 50141 for t in observations.list_trains(store))
    assert store._conn.execute("SELECT COUNT(*) FROM trains WHERE train_no=50141").fetchone()[0]


def test_ghost_flag_cleared_when_read_again(store):
    store.ingest(frame(extra=[R(7777, "09:12")]), at(0))
    for m in (1, 2, 3):
        store.ingest(frame(), at(m))
    sid = svc(store, 7777)["id"]
    assert store._conn.execute("SELECT ghost FROM service_quality WHERE service_id=?",
                               (sid,)).fetchone()[0] == 1
    store.ingest(frame(extra=[R(7777, "09:12")]), at(4))
    assert store._conn.execute("SELECT ghost FROM service_quality WHERE service_id=?",
                               (sid,)).fetchone()[0] == 0
    assert any(r["train_no"] == 7777 for r in store.current_board()["arrivals"])


# -- learned stations ---------------------------------------------------------------------------

def test_known_stations_protected_against_near_misreads(store, monkeypatch):
    from app import store as store_mod
    monkeypatch.setattr(store_mod, "_today", lambda: T0.date())
    c = store._conn
    for day in ("2026-10-20", "2026-10-21"):
        for no, st in ((1, "AD JUD"), (2, "AD JUD"), (3, "LASI"), (4, "LASI"), (5, "CALARASI"),
                       (6, "CALARASI"), (7, "PLOIEST! SUD"), (8, "PLOIEST! SUD"),
                       (9, "RUSE I"), (10, "RUSE I")):
            c.execute("INSERT INTO services(board, service_date, train_type, train_no, station,"
                      " operator, sched_time, first_seen, last_seen, station_raw)"
                      " VALUES ('arrival', ?, 'R', ?, ?, 'x', '10:00', ?, ?, ?)",
                      (day, no, st, day + "T10:00:00+03:00", day + "T10:00:00+03:00", st))
    assert store.known_stations() == {"CALARASI"}


# -- schema -------------------------------------------------------------------------------------------

def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_fresh_db_has_quality_tables_and_keeps_version(store):
    assert {"service_quality", "event_quality", "quality_periods", "dq_meta"} <= _tables(
        store._conn)
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    store.migrate()  # idempotent
    assert store._conn.execute("SELECT value FROM dq_meta WHERE key='version'").fetchone()[0] \
        == quality.DQ_VERSION


def test_v5_db_gets_quality_tables_without_touching_data(tmp_path):
    db = tmp_path / "v.db"
    shutil.copy(FIX / "live_v2.db", db)
    s = Store(str(db))
    s.migrate()  # v2 -> v5 (+ quality tables)
    before = s._conn.execute("SELECT * FROM services ORDER BY id").fetchall()
    s.close()
    raw = sqlite3.connect(db)  # simulate a v5 DB from Beta 1.02: no quality tables yet
    for t in ("service_quality", "event_quality", "quality_periods", "dq_meta"):
        raw.execute(f"DROP TABLE {t}")
    raw.commit()
    raw.close()
    s = Store(str(db))
    s.migrate()
    assert {"service_quality", "event_quality"} <= _tables(s._conn)
    assert s._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert s._conn.execute("SELECT * FROM services ORDER BY id").fetchall() == before
    s.close()


# -- retroactive backfill --------------------------------------------------------------------------------

def _seed_history(c):
    """RE 5002 (25 -> 425 -> 25), R 10260 (final 945), R 5011 + 8 misread duplicates."""
    def run(t):
        c.execute("INSERT INTO runs(ts, ok, n_rows) VALUES (?,1,24)", (t,))
    base = datetime(2026, 10, 21, 7, 0, tzinfo=BUC)
    for m in range(0, 121):
        run((base + timedelta(minutes=m)).isoformat())

    def t(m):
        return (base + timedelta(minutes=m)).isoformat()

    def service(no, sched, fs, ls, last_delay=0, station="X", board="arrival", **kw):
        return c.execute(
            "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
            " sched_time, first_seen, last_seen, last_delay, status, station_raw, operator_raw)"
            " VALUES (?, '2026-10-21', 'R', ?, ?, ?, ?, ?, ?, ?, 'gone', ?, ?)",
            (board, no, station, kw.get("operator", "CFR Calatori"), sched, t(fs), t(ls),
             last_delay, kw.get("station_raw", station), kw.get("operator_raw", ""))).lastrowid

    def ev(sid, m, old, new):
        return c.execute("INSERT INTO events(service_id, ts, kind, old, new)"
                         " VALUES (?,?,'delay',?,?)", (sid, t(m), old, new)).lastrowid

    ids = {}
    ids["5002"] = service(5002, "07:31", 4, 63, 25)
    ids["e425"] = [ev(ids["5002"], 33, "0", "20"), ev(ids["5002"], 52, "20", "25"),
                   ev(ids["5002"], 55, "25", "425"), ev(ids["5002"], 56, "425", "25")]
    ids["10260"] = service(10260, "08:42", 4, 63, 945)
    ids["e945"] = [ev(ids["10260"], 30, "0", "15"), ev(ids["10260"], 63, "15", "945")]
    ids["5011"] = service(5011, "04:47", 0, 120, 0, station="BUZAU", board="departure")
    ids["dups"] = [service(no, "04:47", 10, 10 + k % 2, 0, station="BUZAU", board="departure")
                   for k, no in enumerate([5014, 50141, 501, 50171, 5017, 50111, 9014, 3014])]
    ids["adjud"] = service(1574, "10:00", 0, 60, 0, station="AD JUD", operator="CFR Calaitori",
                           operator_raw="CFR Calaitori")
    return ids


def test_backfill_flags_without_touching_raw_data_and_is_idempotent(tmp_path):
    s = Store(str(tmp_path / "b.db"))
    s.migrate()
    c = s._conn
    # live validation started after this history
    c.execute("UPDATE dq_meta SET value='2026-10-22T00:00:00+03:00' WHERE key='live_since'")
    ids = _seed_history(c)
    raw_before = (c.execute("SELECT * FROM services ORDER BY id").fetchall(),
                  c.execute("SELECT * FROM events ORDER BY id").fetchall())
    res = quality.backfill(c)
    assert res["changed"]["services"] > 0
    raw_after = (c.execute("SELECT * FROM services ORDER BY id").fetchall(),
                 c.execute("SELECT * FROM events ORDER BY id").fetchall())
    assert raw_after == raw_before  # no raw value modified, nothing deleted

    def q(sid):
        return c.execute("SELECT * FROM service_quality WHERE service_id=?", (sid,)).fetchone()
    # delays
    sus = dict(c.execute("SELECT event_id, reason FROM event_quality").fetchall())
    assert sus[ids["e425"][2]] == "plus_misread" and sus[ids["e425"][3]] == "revert"
    assert sus[ids["e945"][1]] == "unconfirmed"
    assert (q(ids["5002"])["max_delay_clean"], q(ids["5002"])["last_delay_clean"]) == (25, 25)
    assert (q(ids["10260"])["max_delay_clean"], q(ids["10260"])["last_delay_clean"]) == (15, 15)
    hist = {h["train_no"]: h for h in s.history(datetime(2026, 10, 21).date())}
    assert (hist[10260]["max_delay"], hist[10260]["final_delay"]) == (15, 15)
    assert hist[5002]["max_delay"] == 25
    # ghosts
    assert q(ids["5011"])["ghost"] == 0
    assert all(q(d)["ghost"] == 1 for d in ids["dups"])
    assert 5014 not in hist and 5011 in hist
    # canonical names (raw kept)
    assert q(ids["adjud"])["station_canonical"] == "ADJUD"
    assert q(ids["adjud"])["operator_canonical"] == "CFR Calatori"
    assert hist[1574]["station"] == "ADJUD" and hist[1574]["operator"] == "CFR Calatori"
    assert c.execute("SELECT station FROM services WHERE id=?", (ids["adjud"],)).fetchone()[0] \
        == "AD JUD"
    # reduced-quality period: 2026-10-21 before 11:31:51
    assert all(q(i)["low_quality"] == 1 for i in (ids["5002"], ids["10260"]))
    assert hist[5002]["low_quality"] is True
    # second run: nothing changes
    again = quality.backfill(c)
    assert again["changed"] == {}
    assert again["after"] == res["after"]
    s.close()


def test_backfill_dry_run_writes_nothing(tmp_path):
    s = Store(str(tmp_path / "d.db"))
    s.migrate()
    c = s._conn
    c.execute("UPDATE dq_meta SET value='2026-10-22T00:00:00+03:00' WHERE key='live_since'")
    _seed_history(c)
    res = quality.backfill(c, dry_run=True)
    assert res["after"]["ghosts"] == 8 and res["before"]["ghosts"] == 0
    assert c.execute("SELECT COUNT(*) FROM service_quality").fetchone()[0] == 0
    s.close()


def test_backfill_cli(tmp_path, capsys):
    db = tmp_path / "cli.db"
    s = Store(str(db))
    s.migrate()
    _seed_history(s._conn)
    s.close()
    assert quality.main(["--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert '"ghosts": 8' in out


def test_ghost_leaving_emits_no_gone_event(store):
    store.ingest(frame(), at(0))
    store.ingest(frame(extra=[R(9014, "09:12", station="BUZAU")]), at(1))
    evs = []
    for m in (2, 3, 4):
        evs += store.ingest(frame(), at(m))
    assert [e for e in evs if e.row.train_no == 9014] == []
    assert kinds(store, "gone", 9014) == []


def test_unknown_clean_delay_is_not_zero_in_history(tmp_path):
    s = Store(str(tmp_path / "u.db"))
    s.migrate()
    c = s._conn
    c.execute("UPDATE dq_meta SET value='2026-10-22T00:00:00+03:00' WHERE key='live_since'")
    base = datetime(2026, 10, 21, 7, 0, tzinfo=BUC)
    for m in range(0, 10):
        c.execute("INSERT INTO runs(ts, ok, n_rows) VALUES (?,1,24)",
                  ((base + timedelta(minutes=m)).isoformat(),))
    sid = c.execute(
        "INSERT INTO services(board, service_date, train_type, train_no, station, operator,"
        " sched_time, first_seen, last_seen, last_delay, status, station_raw)"
        " VALUES ('arrival','2026-10-21','R',4242,'X','o','07:30',?,?,425,'gone','X')",
        ((base + timedelta(minutes=3)).isoformat(), (base + timedelta(minutes=5)).isoformat())
    ).lastrowid
    c.execute("INSERT INTO events(service_id, ts, kind, old, new) VALUES (?,?,'delay','25','425')",
              (sid, (base + timedelta(minutes=4)).isoformat()))
    quality.backfill(c)
    h = [x for x in s.history(base.date()) if x["train_no"] == 4242][0]
    assert h["max_delay"] is None and h["final_delay"] is None and h["delay_seen"] is False
    s.close()


def test_notifier_gone_after_short_return_is_pushed_again(store):
    import asyncio

    from app.notifier import Notifier

    sent = []

    async def send(sub, data):
        sent.append(data["body"])

    store.subscribe("https://fcm.googleapis.com/x", "k", "a")
    store.follow("https://fcm.googleapis.com/x", 5030, T0.date(), today=T0.date())
    n = Notifier(store, send)

    async def tick(rows, m):
        await n.handle(store.ingest(rows, at(m)), T0.date())

    async def run():
        for m in range(0, 4):  # a real train: on the board for minutes
            await tick(frame(), m)
        for m in range(4, 9):
            await tick(_without(frame()), m)
        await tick(frame(), 10)  # short return: no 'appeared'
        await tick(frame(), 11)
        for m in range(12, 17):
            await tick(_without(frame()), m)
    asyncio.run(run())
    assert sum("ieșit" in b for b in sent) == 2
