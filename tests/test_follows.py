# © 2026 Andy217Ace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import Row
from app.store import Store, Subscription

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=BUC)
DAY = date(2026, 10, 20)
EP = "https://push.example.com/sub/abc"
EP2 = "https://push.example.com/sub/def"


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr("app.store._today", lambda: DAY)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def test_subscribe_returns_id_and_upserts(store):
    sid = store.subscribe(EP, "p1", "a1")
    assert isinstance(sid, int)
    assert store.subscribe(EP, "p2", "a2") == sid  # same endpoint -> same row, keys updated
    store.follow(EP, 1636, DAY)
    assert store.followers(1636, DAY) == [Subscription(EP, "p2", "a2")]


@pytest.mark.parametrize("bad", [
    "http://push.example.com/x", "ftp://x", "not a url", "", "https://",
    "https://example.com/" + "a" * 500,
    "https://127.0.0.1/x", "https://10.0.0.5:8443/x", "https://[::1]/x",
    "https://localhost/x", "https://LOCALHOST/x", "https://printer.local/x",
    "https://metadata.google.internal/x", "https://169.254.169.254/latest",
])
def test_subscribe_rejects_bad_endpoint(store, bad):
    with pytest.raises(ValueError):
        store.subscribe(bad, "p", "a")


@pytest.mark.parametrize("good", [
    "https://fcm.googleapis.com/fcm/send/abc", "https://updates.push.services.mozilla.com/wpush/v2/x",
    "https://web.push.apple.com/QX", "https://wns2-db5p.notify.windows.com/w/?token=x",
])
def test_subscribe_accepts_real_push_services(store, good):
    assert isinstance(store.subscribe(good, "p", "a"), int)


def test_subscribe_rejects_empty_keys(store):
    with pytest.raises(ValueError):
        store.subscribe(EP, "", "a")
    with pytest.raises(ValueError):
        store.subscribe(EP, "p", "")


def test_follow_unfollow_and_list(store):
    store.subscribe(EP, "p", "a")
    store.follow(EP, 1636, DAY)
    store.follow(EP, 1636, DAY)  # idempotent
    store.follow(EP, 1621, "2026-10-21")  # ISO string accepted too
    assert store.list_follows(EP) == [
        {"train_no": 1636, "date": "2026-10-20"},
        {"train_no": 1621, "date": "2026-10-21"},
    ]
    store.unfollow(EP, 1636, DAY)
    assert store.list_follows(EP) == [{"train_no": 1621, "date": "2026-10-21"}]
    assert store.followers(1636, DAY) == []


def test_follow_unknown_subscription(store):
    with pytest.raises(ValueError):
        store.follow(EP, 1636, DAY)
    assert store.list_follows(EP) == []


def test_follow_limit_20(store):
    store.subscribe(EP, "p", "a")
    for n in range(20):
        store.follow(EP, 1000 + n, DAY, today=DAY)
    with pytest.raises(ValueError, match="limită de 20 de trenuri"):
        store.follow(EP, 2000, DAY, today=DAY)
    store.follow(EP, 1000, DAY, today=DAY)  # re-following an existing one is fine
    assert len(store.list_follows(EP)) == 20


def test_follow_limit_counts_only_current_dates(store):
    store.subscribe(EP, "p", "a")
    old = DAY - timedelta(days=5)
    for n in range(20):
        store.follow(EP, 1000 + n, old, today=old)
    # The 20 follows from 5 days ago neither block nor survive...
    store.follow(EP, 2000, DAY, today=DAY)
    store.follow(EP, 1000, DAY - timedelta(days=1), today=DAY)  # ...yesterday is kept
    assert store.list_follows(EP) == [
        {"train_no": 2000, "date": "2026-10-20"},
        {"train_no": 1000, "date": "2026-10-19"},
    ]
    for n in range(18):
        store.follow(EP, 3000 + n, DAY, today=DAY)
    with pytest.raises(ValueError, match="limită de 20 de trenuri"):  # yesterday counts
        store.follow(EP, 4000, DAY, today=DAY)


def test_follow_default_today_is_bucharest(store, monkeypatch):
    from app.store import TZ
    monkeypatch.undo()  # real clock
    store.subscribe(EP, "p", "a")
    store.follow(EP, 1000, date(2020, 1, 1))
    store.follow(EP, 1001, datetime.now(TZ).date())  # old one pruned lazily
    assert [f["train_no"] for f in store.list_follows(EP)] == [1001]


def test_followers_only_for_train_and_date(store):
    store.subscribe(EP, "p", "a")
    store.subscribe(EP2, "q", "b")
    store.follow(EP, 1636, DAY)
    store.follow(EP2, 1636, DAY + timedelta(days=1))
    assert store.followers(1636, DAY) == [Subscription(EP, "p", "a")]
    assert store.followers(1637, DAY) == []


def test_unsubscribe_cascades_follows(store):
    store.subscribe(EP, "p", "a")
    store.follow(EP, 1636, DAY)
    store.unsubscribe(EP)
    store.unsubscribe(EP)  # unknown endpoint: no error
    assert store.followers(1636, DAY) == []
    assert store._conn.execute("SELECT COUNT(*) FROM follows").fetchone()[0] == 0


def test_service_state_and_last_run(store):
    assert store.last_ok_run_id() is None
    rows = [Row("arrival", "IR", n, "Brasov", "CFR", t, delay_min=5, platform=3)
            for n, t in ((1621, "12:10"), (1622, "12:20"))]
    rows += [Row("departure", "IR", n, "Brasov", "CFR", t)
             for n, t in ((1731, "12:15"), (1732, "12:30"))]
    store.ingest(rows, T0)
    rid = store.last_ok_run_id()
    assert isinstance(rid, int)
    st = store.service_state("arrival", "2026-10-20", 1621, "12:10")
    assert st == {"status": "listed", "delay": 5, "platform": 3,
                  "last_read": T0.isoformat(), "last_seen": T0.isoformat()}
    assert store.last_ok_run() == (rid, T0.isoformat())
    assert store.service_state("arrival", "2026-10-20", 9999, "12:10") is None
    store.ingest(rows[:1], T0 + timedelta(minutes=1))  # failed run: id unchanged
    assert store.last_ok_run_id() == rid


def test_history_null_safe(store):
    rows = [Row("arrival", "IR", 1621, "Brasov", "CFR", "12:10", delay_min=5),
            Row("arrival", "IR", 1622, "Brasov", "CFR", "12:20"),
            Row("departure", "IR", 1731, "Brasov", "CFR", "12:15"),
            Row("departure", "IR", 1732, "Brasov", "CFR", "12:30")]
    store.ingest(rows, T0)
    sid = store._conn.execute("SELECT id FROM services WHERE train_no=1621").fetchone()[0]
    store._conn.execute(
        "INSERT INTO events(service_id, ts, kind, old, new) VALUES (?,?,?,?,?)",
        (sid, T0.isoformat(), "delay", None, "9"))
    h = {r["train_no"]: r for r in store.history(DAY)}
    assert h[1621]["max_delay"] == 9


def test_lookup_indexes_used(store):
    def plan(sql, args):
        return " ".join(str(r[-1]) for r in store._conn.execute("EXPLAIN QUERY PLAN " + sql, args))
    assert "INDEX" in plan("SELECT * FROM events WHERE service_id=?", (1,))
    assert "INDEX" in plan("SELECT * FROM services WHERE service_date=? AND train_no=?",
                           ("2026-10-20", 1))
