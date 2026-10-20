# © 2026 Andy217Ace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import Row
from app.store import Store

BUC = ZoneInfo("Europe/Bucharest")
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=BUC)
DAY = date(2026, 10, 20)
KEYS = {"board", "train_type", "train_no", "station", "operator", "sched_time", "max_delay",
        "final_delay", "platform", "status", "first_seen", "last_seen"}


def R(board, no, t, delay=0, platform=None, station="Brasov"):
    return Row(board=board, train_type="IR", train_no=no, station=station,
               operator="CFR Calatori", sched_time=t, delay_min=delay, platform=platform)


def rows(d1=0, d2=0):
    return [
        R("arrival", 1621, "12:10", delay=d1, platform=3),
        R("arrival", 1622, "12:20", station="Ploiesti"),
        R("departure", 1731, "12:15", delay=d2, platform=5),
        R("departure", 1732, "12:30", station="Sinaia"),
    ]


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


@pytest.fixture
def filled(store):
    for i, d in enumerate((5, 10, 7)):
        store.ingest(rows(d1=d, d2=2 if i == 0 else 0), T0 + timedelta(minutes=i))
    return store


def by_no(res, no):
    return next(r for r in res if r["train_no"] == no)


def test_max_and_final_delay(filled):
    res = filled.history(DAY)
    assert len(res) == 4
    assert all(set(r) == KEYS for r in res)
    r = by_no(res, 1621)
    assert (r["max_delay"], r["final_delay"]) == (10, 7)
    assert r["platform"] == 3 and r["status"] == "listed"
    assert by_no(res, 1731)["max_delay"] == 2 and by_no(res, 1731)["final_delay"] == 0


def test_single_sighting_and_no_delay(store):
    store.ingest(rows(d1=7), T0)
    res = store.history(DAY)
    assert by_no(res, 1621)["max_delay"] == 7
    assert by_no(res, 1622)["max_delay"] == 0


def test_order_by_sched_time_then_board(filled):
    res = filled.history(DAY)
    assert [r["sched_time"] for r in res] == ["12:10", "12:15", "12:20", "12:30"]


def test_filter_train(filled):
    assert [r["train_no"] for r in filled.history(DAY, train=1731)] == [1731]


def test_filter_board(filled):
    assert {r["board"] for r in filled.history(DAY, board="arrival")} == {"arrival"}


def test_filter_station_case_and_diacritics(filled):
    assert [r["train_no"] for r in filled.history(DAY, station="brasov")] == [1621, 1731]
    assert [r["train_no"] for r in filled.history(DAY, station="PLOIES")] == [1622]
    assert [r["train_no"] for r in filled.history(DAY, station="ploiești")] == [1622]
    assert [r["train_no"] for r in filled.history(DAY, station="ina")] == [1732]


def test_station_like_wildcards_escaped(filled):
    assert filled.history(DAY, station="%") == []
    assert filled.history(DAY, station="_") == []
    assert filled.history(DAY, station="B_ASOV") == []


def test_time_interval_inclusive(filled):
    res = filled.history(DAY, time_from="12:15", time_to="12:20")
    assert [r["sched_time"] for r in res] == ["12:15", "12:20"]
    assert [r["sched_time"] for r in filled.history(DAY, time_from="12:21")] == ["12:30"]
    assert [r["sched_time"] for r in filled.history(DAY, time_to="12:10")] == ["12:10"]


def test_empty_day(filled):
    assert filled.history(date(2026, 10, 21)) == []


def test_train_events_chronological(filled):
    ev = filled.train_events(1621, DAY)
    assert [e["kind"] for e in ev] == ["appeared", "delay", "delay"]
    ev_delay = [e for e in ev if e["kind"] == "delay"]
    assert [(e["old"], e["new"]) for e in ev_delay] == [("5", "10"), ("10", "7")]
    assert ev[0]["ts"] <= ev[1]["ts"] <= ev[2]["ts"]
    assert set(ev[0]) == {"ts", "kind", "old", "new", "board", "sched_time", "station"}
    assert ev[0]["board"] == "arrival" and ev[0]["sched_time"] == "12:10"


def test_train_events_three_delay_events(store):
    for i, d in enumerate((0, 5, 10, 7)):
        store.ingest(rows(d1=d), T0 + timedelta(minutes=i))
    ev = [e for e in store.train_events(1621, DAY) if e["kind"] == "delay"]
    assert [e["new"] for e in ev] == ["5", "10", "7"]


def test_train_events_empty(filled):
    assert filled.train_events(9999, DAY) == []
    assert filled.train_events(1621, date(2026, 10, 21)) == []
