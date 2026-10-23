# © 2026 Andy217Ace
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models import Row
from app.store import MIN_ROWS, SCHEMA_VERSION, Store, service_date

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=BUC)


def R(board, no, t, delay=0, platform=None, **kw):
    return Row(board=board, train_type="IR", train_no=no, station="Brasov",
               operator="CFR Calatori", sched_time=t, delay_min=delay,
               platform=platform, **kw)


def base_rows():
    rows = [
        R("arrival", 1621, "12:10", platform=3),
        R("arrival", 1622, "12:20"),
        R("departure", 1731, "12:15", platform=5),
        R("departure", 1732, "12:30"),
    ]
    return rows


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def count(store, table, where="1=1"):
    return store._conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def test_min_rows_constant():
    assert MIN_ROWS == 4


def test_migrate_idempotent_and_versioned(store):
    store.migrate()
    assert store._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    names = {r[0] for r in store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"runs", "services", "events", "subscriptions", "follows"} <= names


def test_migrate_v1_db_adds_last_read(tmp_path):
    s = Store(str(tmp_path / "old.db"))
    s.migrate()
    # Simulate a database created by schema version 1 (no last_read column).
    s._conn.execute("ALTER TABLE services DROP COLUMN last_read")
    s._conn.execute("PRAGMA user_version = 1")
    s.migrate()
    s.migrate()  # idempotent
    cols = {r[1] for r in s._conn.execute("PRAGMA table_info(services)")}
    assert "last_read" in cols
    assert s._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    s.close()


def test_last_read_only_set_by_confident_rows(store):
    store.ingest(base_rows(), T0)
    t1 = T0 + timedelta(minutes=1)
    # stays a valid reading (each panel keeps >= 2 confident rows)
    rows = base_rows() + [R("departure", 1733, "12:45"), R("arrival", 1623, "12:40")]
    rows[0] = R("arrival", 1621, "12:10", platform=3, confidence=0.1)
    store.ingest(rows, t1)
    assert store.last_ok_run()[1] == t1.isoformat()
    st = store.service_state("arrival", "2026-10-20", 1621, "12:10")
    assert st["last_read"] == T0.isoformat()
    st2 = store.service_state("arrival", "2026-10-20", 1622, "12:20")
    assert st2["last_read"] == t1.isoformat()


def test_wal_on_file_db(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.migrate()
    assert s._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    s.close()


def test_first_read_all_appeared(store):
    ev = store.ingest(base_rows(), T0, "h1")
    assert len(ev) == 4
    assert all(e.kind == "appeared" for e in ev)
    assert count(store, "services") == 4
    assert count(store, "events", "kind='appeared'") == 4
    assert count(store, "runs", "ok=1") == 1


def test_delay_change_event(store):
    store.ingest(base_rows(), T0)
    rows = base_rows()
    rows[0] = R("arrival", 1621, "12:10", delay=15, platform=3)
    assert store.ingest(rows, T0 + timedelta(minutes=1)) == []  # first reading: pending
    ev = store.ingest(rows, T0 + timedelta(minutes=2))  # confirmed by the second one
    assert len(ev) == 1
    e = ev[0]
    assert e.kind == "delay" and e.old == "0" and e.new == "15"
    assert e.row.train_no == 1621
    assert count(store, "events", "kind='delay'") == 1


def test_platform_assigned_and_changed(store):
    store.ingest(base_rows(), T0)
    rows = base_rows()
    rows[1] = R("arrival", 1622, "12:20", platform=7)
    ev = store.ingest(rows, T0 + timedelta(minutes=1))
    assert [(e.kind, e.old, e.new) for e in ev] == [("platform", None, "7")]
    rows[1] = R("arrival", 1622, "12:20", platform=8)
    assert store.ingest(rows, T0 + timedelta(minutes=2)) == []  # a change waits one frame
    ev = store.ingest(rows, T0 + timedelta(minutes=3))
    assert [(e.kind, e.old, e.new) for e in ev] == [("platform", "7", "8")]


def test_unchanged_read_no_events(store):
    store.ingest(base_rows(), T0)
    assert store.ingest(base_rows(), T0 + timedelta(minutes=1)) == []


def test_too_few_rows_records_failed_run_only(store):
    store.ingest(base_rows(), T0)
    before = store._conn.execute("SELECT * FROM services ORDER BY id").fetchall()
    ev = store.ingest([R("arrival", 1621, "12:10", delay=99)], T0 + timedelta(minutes=1))
    assert ev == []
    assert store._conn.execute("SELECT * FROM services ORDER BY id").fetchall() == before
    assert count(store, "runs", "ok=0") == 1
    assert count(store, "events") == 4


def test_one_board_empty_ingests_the_other_board(store):
    """Per-panel ingest: an unreadable (empty) panel no longer blocks the other."""
    rows = [R("arrival", n, f"12:{n % 60:02d}") for n in range(1, 7)]
    assert len(store.ingest(rows, T0)) == 6
    assert count(store, "runs", "ok=1") == 1
    assert count(store, "services", "board='arrival'") == 6
    assert store.last_rejected == {"departure": "too few rows (0)"}


def test_failed_run_does_not_count_as_miss(store):
    store.ingest(base_rows(), T0)
    store.ingest(base_rows()[1:], T0 + timedelta(minutes=1))  # 3 rows -> fail
    store.ingest(base_rows()[1:], T0 + timedelta(minutes=2))  # 3 rows -> fail
    assert count(store, "services", "status='gone'") == 0


def test_same_number_both_boards_and_two_times_are_separate(store):
    rows = [
        R("arrival", 1621, "12:10"),
        R("departure", 1621, "12:40"),
        R("arrival", 1621, "18:10"),
        R("departure", 1732, "12:30"),
    ]
    ev = store.ingest(rows, T0)
    assert len(ev) == 4
    assert count(store, "services", "train_no=1621") == 3


def test_service_date_after_midnight():
    assert service_date("00:05", datetime(2026, 10, 20, 23, 58)) == date(2026, 10, 21)


def test_service_date_before_midnight_seen_after():
    assert service_date("23:50", datetime(2026, 10, 21, 0, 10)) == date(2026, 10, 20)


def test_service_date_same_day_and_tz_conversion():
    assert service_date("12:10", datetime(2026, 10, 20, 11, 0)) == date(2026, 10, 20)
    # 22:30 UTC == 01:30 Bucharest (EEST, +3) on the 21st
    now = datetime(2026, 10, 20, 22, 30, tzinfo=timezone.utc)
    assert service_date("01:40", now) == date(2026, 10, 21)
    assert Store.service_date("01:40", now) == date(2026, 10, 21)


def test_ingest_uses_bucharest_service_date(store):
    now = datetime(2026, 10, 20, 20, 58, tzinfo=timezone.utc)  # 23:58 local
    rows = [
        R("arrival", 1, "00:05"),
        R("arrival", 2, "23:50"),
        R("departure", 3, "00:20"),
        R("departure", 4, "23:59"),
    ]
    store.ingest(rows, now)
    got = dict(store._conn.execute("SELECT train_no, service_date FROM services"))
    assert got == {1: "2026-10-21", 2: "2026-10-20", 3: "2026-10-21", 4: "2026-10-20"}
    ts = store._conn.execute("SELECT ts FROM runs").fetchone()[0]
    assert ts.endswith("+03:00")


def test_gone_after_three_consecutive_misses(store):
    store.ingest(base_rows(), T0 - timedelta(minutes=5))  # listed for minutes: not a ghost
    store.ingest(base_rows(), T0)
    rows = base_rows()[1:] + [R("arrival", 1650, "13:00")]
    ev = store.ingest(rows, T0 + timedelta(minutes=1))
    assert [(e.kind, e.row.train_no) for e in ev] == [("appeared", 1650)]
    assert count(store, "services", "train_no=1621 AND status='listed'") == 1
    assert store.ingest(rows, T0 + timedelta(minutes=2)) == []  # 2 misses: still listed
    ev = store.ingest(rows, T0 + timedelta(minutes=3))
    assert [(e.kind, e.row.train_no) for e in ev] == [("gone", 1621)]
    assert count(store, "services", "train_no=1621 AND status='gone'") == 1
    assert count(store, "events", "kind='gone'") == 1
    # stays gone, no duplicate event
    assert store.ingest(rows, T0 + timedelta(minutes=4)) == []


def test_miss_reset_when_seen_again(store):
    store.ingest(base_rows(), T0)
    rows = base_rows()[1:] + [R("arrival", 1650, "13:00")]
    store.ingest(rows, T0 + timedelta(minutes=1))
    store.ingest(base_rows() + [R("arrival", 1650, "13:00")], T0 + timedelta(minutes=2))
    ev = store.ingest(rows, T0 + timedelta(minutes=3))
    assert ev == []
    assert count(store, "services", "status='gone'") == 0


def test_gone_service_reappears(store):
    store.ingest(base_rows(), T0)
    rows = base_rows()[1:] + [R("arrival", 1650, "13:00")]
    for m in (1, 2, 3):
        store.ingest(rows, T0 + timedelta(minutes=m))
    # back after a long absence (> REAPPEAR_QUIET_MIN): a new 'appeared'
    ev = store.ingest(base_rows() + [R("arrival", 1650, "13:00")], T0 + timedelta(minutes=20))
    assert [(e.kind, e.row.train_no) for e in ev] == [("appeared", 1621)]
    row = store._conn.execute(
        "SELECT status, miss_count FROM services WHERE train_no=1621").fetchone()
    assert tuple(row) == ("listed", 0)


def test_current_board(store):
    assert store.current_board() == {"updated_at": None, "arrivals": [], "departures": []}
    rows = [
        R("arrival", 1622, "12:20"),
        R("arrival", 1621, "12:10", delay=5, platform=3, flagged=True),
        R("departure", 1732, "12:30"),
        R("departure", 1731, "12:15", platform=5),
    ]
    store.ingest(rows, T0)
    b = store.current_board()
    assert b["updated_at"] == T0.isoformat()
    assert [r["train_no"] for r in b["arrivals"]] == [1621, 1622]
    assert [r["train_no"] for r in b["departures"]] == [1731, 1732]
    a = b["arrivals"][0]
    assert a == {"train_type": "IR", "train_no": 1621, "station": "Brasov",
                 "operator": "CFR Calatori", "sched_time": "12:10", "delay_min": 5,
                 "platform": 3, "flagged": True, "status": "listed",
                 "service_date": T0.date().isoformat(), "uncertain": False,
                 "delay_read": True}
    assert a["flagged"] is True and b["arrivals"][1]["flagged"] is False
    # failed run doesn't move updated_at
    store.ingest([], T0 + timedelta(minutes=1))
    assert store.current_board()["updated_at"] == T0.isoformat()


def test_current_board_orders_across_midnight_and_hides_gone(store):
    now = datetime(2026, 10, 20, 23, 50, tzinfo=BUC)
    rows = [
        R("arrival", 1, "00:05"), R("arrival", 2, "23:55"),
        R("departure", 3, "00:20"), R("departure", 4, "23:59"),
    ]
    store.ingest(rows, now)
    b = store.current_board()
    assert [r["train_no"] for r in b["arrivals"]] == [2, 1]
    rows2 = rows[1:] + [R("arrival", 5, "00:30")]
    for m in (1, 2, 3):
        store.ingest(rows2, now + timedelta(minutes=m))
    assert [r["train_no"] for r in store.current_board()["arrivals"]] == [2, 5]


def test_last_ok_age(store):
    assert store.last_ok_age(T0) is None
    store.ingest(base_rows(), T0)
    store.ingest([], T0 + timedelta(seconds=30))
    assert store.last_ok_age(T0 + timedelta(seconds=90)) == pytest.approx(90.0)


def test_ingest_rolls_back_on_error(store, monkeypatch):
    store.ingest(base_rows(), T0)
    rows = base_rows()
    rows[0] = R("arrival", 1621, "12:10", delay=20, platform=3)

    def boom(*a, **k):
        raise RuntimeError("boom")

    store.ingest(rows, T0 + timedelta(minutes=1))  # first reading of 20: pending
    monkeypatch.setattr(store, "_insert_event", boom)
    with pytest.raises(RuntimeError):
        store.ingest(rows, T0 + timedelta(minutes=2))  # confirming one: event insert fails
    assert count(store, "runs") == 2
    assert store._conn.execute(
        "SELECT last_delay FROM services WHERE train_no=1621").fetchone()[0] == 0


# --- fix round 1 -----------------------------------------------------------

def test_min_confidence_constant():
    from app.store import MIN_CONFIDENCE
    assert MIN_CONFIDENCE == 0.5


def test_low_confidence_delay_misread_is_ignored(store):
    rows = base_rows() + [R("arrival", 1650, "13:00")]  # stays valid without the low row
    rows[0] = R("arrival", 1621, "12:10", delay=10, platform=3)
    store.ingest(rows, T0)
    low = list(rows)
    low[0] = R("arrival", 1621, "12:10", delay=16, platform=4, confidence=0.3)
    assert store.ingest(low, T0 + timedelta(minutes=1)) == []
    s = store._conn.execute(
        "SELECT last_delay, last_platform, last_seen FROM services WHERE train_no=1621").fetchone()
    assert (s[0], s[1]) == (10, 3)
    assert s[2] == (T0 + timedelta(minutes=1)).isoformat()  # last_seen refreshed
    assert store.ingest(rows, T0 + timedelta(minutes=2)) == []
    assert count(store, "events", "kind IN ('delay','platform')") == 0


@pytest.mark.usefixtures("legacy_rules")  # mechanics of matching, not debounce
def test_low_confidence_misread_train_no_creates_nothing(store):
    store.ingest(base_rows() + [R("arrival", 1650, "13:00")], T0)
    rows = base_rows() + [R("arrival", 1650, "13:00")]
    rows[0] = R("arrival", 1627, "12:10", platform=3, confidence=0.2)  # misread 1621
    assert store.ingest(rows, T0 + timedelta(minutes=1)) == []
    ev = store.ingest(rows, T0 + timedelta(minutes=2))
    # the misread row creates nothing; the real 1621 (unmatched) follows normal miss rules
    assert [(e.kind, e.row.train_no) for e in ev] == [("gone", 1621)]
    assert count(store, "services", "train_no=1627") == 0
    assert count(store, "events", "kind='appeared'") == 5


def test_low_confidence_rows_do_not_count_for_validity(store):
    rows = [R("arrival", 1, "12:00"), R("arrival", 2, "12:05"), R("departure", 3, "12:10"),
            R("departure", 4, "12:15", confidence=0.1)]
    assert store.ingest(rows, T0) == []
    assert count(store, "runs", "ok=0") == 1
    rows = [R("arrival", 1, "12:00"), R("arrival", 2, "12:05"), R("arrival", 5, "12:20"),
            R("departure", 4, "12:15", confidence=0.1)]
    assert store.ingest(rows, T0) == []  # departure board only low-confidence
    assert count(store, "services") == 0


def test_validity_uses_deduplicated_rows(store):
    rows = [R("arrival", 1, "12:00"), R("arrival", 1, "12:00"),
            R("departure", 3, "12:10"), R("departure", 3, "12:10")]
    assert store.ingest(rows, T0) == []
    assert count(store, "runs", "ok=0") == 1


@pytest.mark.usefixtures("legacy_rules")  # mechanics of matching, not debounce
def test_sched_time_jitter_merges(store):
    rows = base_rows() + [R("arrival", 1636, "20:04", delay=5)]
    store.ingest(rows, T0)
    jit = base_rows() + [R("arrival", 1636, "20:01", delay=10)]
    ev = store.ingest(jit, T0 + timedelta(minutes=1))
    assert [(e.kind, e.row.train_no, e.row.sched_time, e.old, e.new) for e in ev] == [
        ("delay", 1636, "20:04", "5", "10")]
    ev = store.ingest(jit, T0 + timedelta(minutes=2))
    assert ev == []
    assert count(store, "services", "train_no=1636") == 1
    assert store._conn.execute(
        "SELECT sched_time, status FROM services WHERE train_no=1636").fetchone()[:] == ("20:04", "listed")
    arr = store.current_board()["arrivals"]
    assert [r["train_no"] for r in arr].count(1636) == 1


def test_jitter_does_not_merge_far_apart_or_claimed(store):
    rows = base_rows() + [R("arrival", 1636, "20:04"), R("arrival", 1636, "21:04")]
    ev = store.ingest(rows, T0)
    assert count(store, "services", "train_no=1636") == 2
    # exact match for 20:04 must not be stolen by a jittered 20:06 row
    rows2 = base_rows() + [R("arrival", 1636, "20:04"), R("arrival", 1636, "20:06"),
                           R("arrival", 1636, "21:04")]
    ev = store.ingest(rows2, T0 + timedelta(minutes=1))
    assert [(e.kind, e.row.sched_time) for e in ev] == [("appeared", "20:06")]


def test_stale_services_go_silently(store):
    store.ingest(base_rows(), T0)
    rows = [R("arrival", 1, "13:00"), R("arrival", 2, "13:05"),
            R("departure", 3, "13:10"), R("departure", 4, "13:15")]
    ev = store.ingest(rows, T0 + timedelta(minutes=45))
    assert all(e.kind == "appeared" for e in ev) and len(ev) == 4
    assert count(store, "services", "status='gone'") == 4
    assert count(store, "events", "kind='gone'") == 0


@pytest.mark.usefixtures("legacy_rules")  # mechanics of matching, not debounce
def test_events_carry_service_date(store):
    now = datetime(2026, 10, 20, 23, 58, tzinfo=BUC)
    rows = [R("arrival", 1, "00:05"), R("arrival", 2, "23:50"),
            R("departure", 3, "00:20"), R("departure", 4, "23:59")]
    ev = store.ingest(rows, now)
    assert {e.row.train_no: e.service_date for e in ev} == {
        1: "2026-10-21", 2: "2026-10-20", 3: "2026-10-21", 4: "2026-10-20"}
    rows[0] = R("arrival", 1, "00:05", delay=3)
    ev = store.ingest(rows[:3] + [R("departure", 5, "00:30")], now + timedelta(minutes=1))
    ev += store.ingest(rows[:3] + [R("departure", 5, "00:30")], now + timedelta(minutes=2))
    assert ev and all(e.service_date for e in ev)
    assert ("gone", 4, "2026-10-20") in {(e.kind, e.row.train_no, e.service_date) for e in ev}


def test_event_service_date_default():
    from app.models import Event
    e = Event("delay", base_rows()[0], "0", "5")
    assert e.service_date is None


@pytest.mark.usefixtures("legacy_rules")  # mechanics of matching, not debounce
def test_jitter_claim_is_globally_closest_not_row_order():
    # two listed services of one train; two incoming rows each within 10 min of both
    for order in (0, 1):
        a, b = R("arrival", 1636, "20:05", delay=5), R("arrival", 1636, "20:09", delay=9)
        rows = base_rows() + ([a, b] if order == 0 else [b, a])
        s = Store(":memory:")
        s.migrate()
        s.ingest(base_rows() + [R("arrival", 1636, "20:00"), R("arrival", 1636, "20:08")], T0)
        s.ingest(rows, T0 + timedelta(minutes=1))
        got = dict(s._conn.execute(
            "SELECT sched_time, last_delay FROM services WHERE train_no=1636").fetchall())
        s.close()
        # globally closest pair first: 20:09->20:08 (1 min), then 20:05->20:00
        assert got == {"20:00": 5, "20:08": 9}, order


@pytest.mark.usefixtures("legacy_rules")  # mechanics of matching, not debounce
def test_low_confidence_row_does_not_touch_gone_service(store):
    store.ingest(base_rows() + [R("arrival", 1636, "12:40")], T0)
    store.ingest(base_rows(), T0 + timedelta(minutes=1))
    store.ingest(base_rows(), T0 + timedelta(minutes=2))
    before = tuple(store._conn.execute(
        "SELECT status, last_seen, miss_count FROM services WHERE train_no=1636").fetchone())
    assert before[0] == "gone"
    low = replace(R("arrival", 1636, "12:40"), confidence=0.1)
    ev = store.ingest(base_rows() + [low], T0 + timedelta(minutes=3))
    assert ev == []
    after = tuple(store._conn.execute(
        "SELECT status, last_seen, miss_count FROM services WHERE train_no=1636").fetchone())
    assert after == before


# -- schema v3: raw OCR text + uncertain flag ---------------------------------

V3_COLS = {"operator_raw", "station_raw", "uncertain"}


def _cols(s):
    return {r[1] for r in s._conn.execute("PRAGMA table_info(services)")}


def _downgrade(s, version):
    for col in V3_COLS:
        s._conn.execute(f"ALTER TABLE services DROP COLUMN {col}")
    if version == 1:
        s._conn.execute("ALTER TABLE services DROP COLUMN last_read")
    s._conn.execute(f"PRAGMA user_version = {version}")


def test_fresh_db_has_v3_columns(store):
    assert V3_COLS <= _cols(store)


@pytest.mark.parametrize("version", [1, 2])
def test_migrate_old_db_to_v3_keeps_data(tmp_path, version):
    s = Store(str(tmp_path / "old.db"))
    s.migrate()
    s.ingest(base_rows(), T0)
    _downgrade(s, version)
    s.migrate()
    s.migrate()  # idempotent
    assert V3_COLS | {"last_read"} <= _cols(s)
    assert s._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert count(s, "services") == 4
    row = s._conn.execute("SELECT operator_raw, station_raw, uncertain FROM services"
                          " LIMIT 1").fetchone()
    assert tuple(row) == ("", "", 0)
    assert all(not r["uncertain"] for r in s.current_board()["arrivals"])
    s.close()


def test_migrate_partially_applied_v3_columns(tmp_path):
    """A column already present (e.g. interrupted earlier attempt) is not re-added."""
    s = Store(str(tmp_path / "p.db"))
    s.migrate()
    s._conn.execute("ALTER TABLE services DROP COLUMN uncertain")
    s._conn.execute("PRAGMA user_version = 2")
    s.migrate()
    assert V3_COLS <= _cols(s)
    assert s._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    s.close()


def test_ingest_stores_raw_and_uncertain(store):
    rows = base_rows()
    rows[0] = R("arrival", 1621, "12:10", platform=3, operator_raw="CFR Calatorl",
                station_raw="BRASOY", uncertain=True)
    store.ingest(rows, T0)
    got = store._conn.execute(
        "SELECT operator, operator_raw, station, station_raw, uncertain FROM services"
        " WHERE train_no=1621").fetchone()
    assert tuple(got) == ("CFR Calatori", "CFR Calatorl", "Brasov", "BRASOY", 1)
    a = store.current_board()["arrivals"]
    assert a[0]["uncertain"] is True and a[1]["uncertain"] is False
    h = store.history(date(2026, 10, 20), train=1621)
    assert h[0]["uncertain"] is True and h[0]["operator"] == "CFR Calatori"


def test_canonical_value_does_not_create_new_service(store):
    rows = base_rows()
    rows[0] = R("arrival", 1621, "12:10", platform=3, operator_raw="Calatorl",
                uncertain=True)
    rows[0] = Row(**{**rows[0].__dict__, "operator": "Calatorl", "station": "BRASOY"})
    store.ingest(rows, T0)
    store.ingest(base_rows(), T0 + timedelta(minutes=1))
    assert count(store, "services") == 4
    got = store._conn.execute(
        "SELECT operator, station, uncertain FROM services WHERE train_no=1621").fetchone()
    assert tuple(got) == ("CFR Calatori", "Brasov", 0)


def test_uncertain_reading_does_not_overwrite_certain_names(store):
    store.ingest(base_rows(), T0)
    rows = base_rows()
    rows[0] = Row(**{**rows[0].__dict__, "operator": "Xyz", "station": "BRAS",
                     "operator_raw": "Xyz", "station_raw": "BRAS", "uncertain": True})
    ev = store.ingest(rows, T0 + timedelta(minutes=1))
    assert ev == []
    got = store._conn.execute(
        "SELECT operator, station, uncertain FROM services WHERE train_no=1621").fetchone()
    assert tuple(got) == ("CFR Calatori", "Brasov", 0)


def _as_read(r, station, **kw):
    """A row whose station was stored exactly as OCR read it."""
    return Row(**{**r.__dict__, "station": station, "station_raw": station, **kw})


def test_known_stations_learns_only_repeated_verbatim_reads(store):
    assert store.known_stations() == set()
    day1 = base_rows()
    day1[0] = _as_read(day1[0], "SUCEAVA")                    # 1621
    day1[1] = _as_read(day1[1], "SUCEAVA")                    # 1622
    day1[2] = _as_read(day1[2], "BRASOY")                     # one misread
    day1[3] = Row(**{**day1[3].__dict__, "station": "BRASOV", "station_raw": "BRASOU",
                     "uncertain": True})                     # corrected, not verbatim
    store.ingest(day1, T0)
    # 2 trains but only 1 day -> not yet
    assert store.known_stations() == set()
    day2 = [_as_read(r, "SUCEAVA") if r.train_no in (1621, 1622) else r for r in base_rows()]
    store.ingest(day2, T0 + timedelta(days=1))
    store._known_cache = None  # new day in tests: drop the per-day cache
    assert store.known_stations() == {"SUCEAVA"}
    # pre-v3 rows (no raw text) never teach anything
    store._conn.execute("UPDATE services SET station_raw='' WHERE station='SUCEAVA'")
    store._known_cache = None
    assert store.known_stations() == set()


def test_known_stations_cached_per_day_and_capped(store, monkeypatch):
    import app.store as st
    calls = []
    real = store._conn

    class Spy:
        def __getattr__(self, name):
            return getattr(real, name)

        def execute(self, sql, *a):
            calls.append(sql)
            return real.execute(sql, *a)
    store._conn = Spy()
    store.known_stations()
    store.known_stations()
    assert sum("station_raw" in c for c in calls) == 1   # second call served from cache
    store._conn = real
    assert st.KNOWN_STATIONS_MAX == 2000


def test_migrate_live_v2_db_from_production_code(tmp_path):
    """tests/fixtures/live_v2.db was written by the store.py deployed at 83a2218
    (schema v2: services rows, no *_raw/uncertain columns)."""
    import shutil
    from pathlib import Path

    src = Path(__file__).parent / "fixtures" / "live_v2.db"
    db = tmp_path / "live.db"
    shutil.copy(src, db)
    s = Store(str(db))
    assert s._conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert not (V3_COLS & _cols(s))
    s.migrate()
    assert s._conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert V3_COLS <= _cols(s)
    assert count(s, "services") == 4 and count(s, "events") == 5
    rows = s._conn.execute("SELECT operator, operator_raw, station_raw, uncertain"
                           " FROM services ORDER BY id").fetchall()
    assert [tuple(r) for r in rows][2] == ("Transferbviar", "", "", 0)
    board = s.current_board()
    assert {r["uncertain"] for r in board["arrivals"] + board["departures"]} == {False}
    assert s.history(date(2026, 10, 20))  # history query works on migrated rows
    s.close()


@pytest.mark.usefixtures("legacy_rules")  # mechanics of matching, not debounce
def test_unread_delay_keeps_last_value_and_emits_nothing(store):
    rows = base_rows()
    rows[0] = R("arrival", 1621, "12:10", delay=15, platform=3)
    store.ingest(rows, T0)
    unread = base_rows()
    unread[0] = R("arrival", 1621, "12:10", delay=0, platform=3, delay_read=False)
    ev = store.ingest(unread, T0 + timedelta(minutes=1))
    assert [e for e in ev if e.kind == "delay"] == []
    a = {r["train_no"]: r for r in store.current_board()["arrivals"]}
    assert a[1621]["delay_min"] == 15 and a[1621]["delay_read"] is False
    assert a[1622]["delay_read"] is True
    # read again -> flag back, real change emitted
    again = base_rows()
    again[0] = R("arrival", 1621, "12:10", delay=20, platform=3)
    ev = store.ingest(again, T0 + timedelta(minutes=2))
    assert [(e.kind, e.old, e.new) for e in ev] == [("delay", "15", "20")]
    assert store.current_board()["arrivals"][0]["delay_read"] is True


def test_new_service_with_unread_delay_is_flagged(store):
    rows = base_rows()
    rows[1] = R("arrival", 1622, "12:20", delay_read=False)
    store.ingest(rows, T0)
    a = {r["train_no"]: r for r in store.current_board()["arrivals"]}
    assert a[1622]["delay_read"] is False and a[1621]["delay_read"] is True


def test_known_stations_cache_follows_patchable_today(store, monkeypatch):
    import app.store as st
    monkeypatch.setattr(st, "_today", lambda: date(2026, 10, 20))
    store.known_stations()
    assert store._known_cache[0][0][0] == date(2026, 10, 20)  # (day, hour)
    monkeypatch.setattr(st, "_today", lambda: date(2026, 10, 21))
    store.known_stations()
    assert store._known_cache[0][0][0] == date(2026, 10, 21)  # new day -> recomputed
