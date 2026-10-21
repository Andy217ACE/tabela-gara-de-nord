# © 2026 Andy217Ace
"""Data-quality rules, each tested on cases measured on the live database
(data-quality-report.md, 2026-10-21)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import quality as q

BUC = ZoneInfo("Europe/Bucharest")


# -- "+" read as a digit -------------------------------------------------------------

@pytest.mark.parametrize("value,ref", [
    (425, 25),   # RE 5002
    (410, 10),   # IC 538, RE 10056, RE 10110, RE 11066
    (190, 10),   # IR 1580, R 5012
    (190, 19),   # R 8122 (18 -> 190 -> 19)
    (240, 20),   # IR 16098, raw "+240" for "+20"
    (435, 45),   # RE 9212, raw "+435" for "+45"
])
def test_digit_dropped_real_cases(value, ref):
    assert q.digit_dropped(value, ref)
    assert q.delay_needs(value, ref) is None


@pytest.mark.parametrize("value,ref", [(45, 15), (100, 40), (945, 15), (25, None), (40, 10)])
def test_digit_dropped_negative(value, ref):
    assert not q.digit_dropped(value, ref)


def test_delay_needs():
    assert q.delay_needs(20, 15) == 2           # ordinary change: debounce
    assert q.delay_needs(945, 15) == 3          # R 10260: huge jump needs 3 frames
    assert q.delay_needs(120, 100) == 2         # big but close to the confirmed value
    assert q.delay_needs(30, None) == 2


# -- platform ---------------------------------------------------------------------

@pytest.mark.parametrize("old,new,need", [
    (None, 5, 1),     # first platform shown: immediate
    (5, 6, 3),        # RE 10111 / R 9101 flapping 5/6
    (11, 14, 3), (1, 4, 3), (14, 1, 3),  # IR 16087 / IR 16595: 11/4/14/1
    (9, None, 2),     # IR 16089: 9 / empty
    (3, 7, 2),
])
def test_platform_needs(old, new, need):
    assert q.platform_needs(old, new) == need


# -- retroactive delay classification -------------------------------------------------

def _t(hm: str) -> str:
    h, m, s = (hm.split(":") + ["0"])[:3]
    return datetime(2026, 10, 21, int(h), int(m), int(s), tzinfo=BUC).isoformat()


def _runs(t0: str, t1: str) -> list[float]:
    a, b = datetime.fromisoformat(_t(t0)), datetime.fromisoformat(_t(t1))
    out = []
    while a <= b:
        out.append(a.timestamp())
        a += timedelta(minutes=1)
    return out


def test_classify_re5002_spike_425():
    # RE 5002: ... 20 -> 25 -> 425 -> 25 (425 seen in one frame)
    ev = [(1, _t("07:33"), "0", "20"), (2, _t("07:48"), "20", "29"), (3, _t("07:51"), "29", "20"),
          (4, _t("07:52"), "20", "25"), (5, _t("07:55"), "25", "425"), (6, _t("07:56"), "425", "25")]
    res = q.classify_delays(_t("07:04"), _t("08:03"), 25, ev, _runs("07:04", "08:03"))
    assert res["suspect"][5] == "plus_misread"
    assert res["suspect"][6] == "revert"
    assert res["max"] == 29 and res["last"] == 25  # 29 lasted 3 frames: a confirmed reading


def test_classify_r10260_final_945_unconfirmed():
    # R 10260: last reading 945 in the very last frame -> last_delay 945 stored
    ev = [(1, _t("08:30"), "0", "15"), (2, _t("08:44"), "15", "19"), (3, _t("08:45"), "19", "16"),
          (4, _t("08:50"), "16", "15"), (5, _t("09:03"), "15", "945")]
    res = q.classify_delays(_t("08:04"), _t("09:03"), 945, ev, _runs("08:04", "09:03"))
    assert res["suspect"][5] == "unconfirmed"
    assert res["max"] == 16 and res["last"] == 15


def test_classify_re10056_final_410():
    ev = [(1, _t("09:12"), "0", "10"), (2, _t("09:34"), "10", "40"), (3, _t("09:35"), "40", "10"),
          (4, _t("09:37"), "10", "410")]
    res = q.classify_delays(_t("08:34"), _t("09:37"), 410, ev, _runs("08:34", "09:37"))
    assert res["suspect"][4] == "plus_misread"
    assert res["suspect"][2] == "unconfirmed" and res["suspect"][3] == "revert"
    assert res["max"] == 10 and res["last"] == 10


def test_classify_ir16098_repeated_240_bounces():
    ev = [(1, _t("16:33"), "0", "15"), (2, _t("16:54"), "15", "20"),
          (3, _t("17:30"), "20", "240"), (4, _t("17:31"), "240", "20"),
          (5, _t("17:33"), "20", "240"), (6, _t("17:34"), "240", "20"),
          (7, _t("17:35"), "20", "240"), (8, _t("17:36"), "240", "20")]
    res = q.classify_delays(_t("16:17"), _t("17:37"), 20, ev, _runs("16:17", "17:37"))
    assert {3, 5, 7} <= set(res["suspect"]) and res["suspect"][3] == "plus_misread"
    assert {4, 6, 8} <= set(res["suspect"])
    assert res["max"] == 20 and res["last"] == 20


def test_classify_r5030_bounce_and_genuine_changes_kept():
    # a genuine change seen for several frames is kept; a one-frame 45 between 15s is not
    ev = [(1, _t("10:00"), "0", "15"), (2, _t("10:05"), "15", "45"), (3, _t("10:06"), "45", "15"),
          (4, _t("10:20"), "15", "30")]
    res = q.classify_delays(_t("09:50"), _t("10:40"), 30, ev, _runs("09:50", "10:40"))
    assert set(res["suspect"]) == {2, 3}
    assert res["max"] == 30 and res["last"] == 30


def test_classify_no_events_and_unknown():
    assert q.classify_delays(_t("10:00"), _t("10:30"), 5, [], _runs("10:00", "10:30")) == {
        "suspect": {}, "max": 5, "last": 5}
    # a single frame: nothing confirmed -> unknown (None), never 0
    r = q.classify_delays(_t("10:00"), _t("10:00"), 0, [], _runs("10:00", "10:00"))
    assert r["max"] is None and r["last"] is None


# -- ghosts -------------------------------------------------------------------------------

def _svc(i, no, t, fs, ls, status="gone", station="BUZAU"):
    return {"id": i, "train_no": no, "sched_time": t, "station": station, "station_raw": station,
            "first_seen": _t(fs), "last_seen": _t(ls), "status": status}


def test_ghost_r5011_cluster():
    real = _svc(1, 5011, "04:47", "00:40", "05:01")
    dups = [_svc(10 + k, no, "04:47", "01:00", ls) for k, (no, ls) in enumerate(
        [(5014, "01:30"), (50141, "01:00"), (501, "02:00"), (50171, "01:00"),
         (5017, "01:01"), (50111, "01:00")])]
    allv = [real, *dups]
    assert q.ghost_verdict(real, allv, 0) is None
    for d in dups:
        v = q.ghost_verdict(d, allv, 0)
        assert v is not None and v[0] in ("near_dup", "short"), d["train_no"]
    assert q.ghost_verdict(dups[0], allv, 0) == ("near_dup", 1)


def test_ghost_short_life_and_listed_never():
    s = _svc(1, 8124, "00:00", "09:20", "09:20", station="SLOBOZIA VECHE")
    assert q.ghost_verdict(s, [s], 1) == ("short", None)
    live = _svc(2, 9999, "10:00", "09:20", "09:20", status="listed")
    assert q.ghost_verdict(live, [live], 0) is None


def test_ghost_r503_r5031_both_well_observed_kept():
    # both read for 75 min with many observations: undecidable -> neither is a ghost
    a = _svc(311, 503, "12:46", "12:00", "13:15", station="PLOIESTI SUD")
    b = _svc(312, 5031, "12:46", "12:00", "13:14", station="PLOIESTI SUD")
    assert q.ghost_verdict(b, [a, b], 40) is None
    assert q.ghost_verdict(a, [a, b], 40) is None


def test_ghost_other_station_is_a_different_train():
    real = _svc(1, 1658, "05:35", "01:00", "05:40", station="VATRA DORNEI BAI")
    other = _svc(2, 1656, "05:35", "02:00", "02:30", station="IASI")
    assert q.ghost_verdict(other, [real, other], 0) is None


def test_public_services_where_env(monkeypatch):
    monkeypatch.delenv("STATS_INCLUDE_LOW_QUALITY", raising=False)
    assert "low_quality" in q.public_services_where()
    monkeypatch.setenv("STATS_INCLUDE_LOW_QUALITY", "1")
    w = q.public_services_where("x")
    assert "low_quality" not in w and "x.id" in w
