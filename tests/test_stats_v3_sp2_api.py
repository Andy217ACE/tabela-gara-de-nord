# © 2026 Andy217Ace
"""Statistici v3 sp2: `detail=train_list` — the journeys behind a chart mark, capped at 200 rows,
read-only, same cached data read as the overview."""
import pytest

from app import stats, stats_overview as so
from tests.test_stats_overview import P, TODAY, add, seed, store  # noqa: F401


def run(store, by, key, board=None, filters=None, limit=None):
    so.clear_cache()
    detail = so.parse_detail({"detail": "train_list", "by": by, "key": key, **({"board": board} if board else {})})
    return so.overview(store, P, filters or {}, today=TODAY, detail=detail)


def test_no_detail_is_the_plain_overview(store):
    assert so.parse_detail({}) is None
    d = so.overview(store, P, {}, today=TODAY)
    assert "train_list" not in d and "boards" in d


def test_operator_list_has_the_trains_behind_the_bar(store):
    d = run(store, "operator", "Transferoviar")
    tl = d["train_list"]
    assert tl["total"] == 2 and not tl["truncated"] and tl["limit"] == 200
    assert {r["train_no"] for r in tl["rows"]} == {1622}
    r = tl["rows"][0]
    assert set(r) >= {"board", "train", "train_no", "type", "operator", "route", "date", "time", "delay", "state"}
    # newest first
    assert [x["date"] for x in tl["rows"]] == sorted((x["date"] for x in tl["rows"]), reverse=True)


def test_route_hour_day_heat_and_type_keys(store):
    assert run(store, "route", "BRASOV")["train_list"]["total"] == 6          # ghost and low quality excluded
    assert run(store, "hour", "8")["train_list"]["total"] == 7                  # 08:15 departures
    assert run(store, "day", "2026-10-20")["train_list"]["total"] >= 1
    assert run(store, "type", "R")["train_list"]["total"] == 2
    # 2026-10-14 is a Wednesday (2); the 08:15 departures of that day
    h = run(store, "heat", "2-8")["train_list"]
    assert h["total"] >= 1 and all(r["time"].startswith("08") for r in h["rows"])


def test_board_and_filters_narrow_the_list(store):
    assert run(store, "hour", "8", board="arrival")["train_list"]["total"] == 0
    assert run(store, "route", "BRASOV", filters={"operator": "Nobody"})["train_list"]["total"] == 0


def test_unknown_delay_is_none_never_zero(store):
    rows = run(store, "route", "CONSTANTA")["train_list"]["rows"]
    unknown = [r for r in rows if r["state"] == "unknown"]
    assert unknown and all(r["delay"] is None for r in unknown)


def test_list_is_capped_at_200_with_truncation(store):
    c = store._conn
    for i in range(230):
        add(c, "arrival", 3000 + i, 1 + i % 20, "09:00", 1, station="BUZAU")
    d = run(store, "route", "BUZAU")
    tl = d["train_list"]
    assert tl["total"] == 230 and len(tl["rows"]) == 200 and tl["truncated"] is True


def test_invalid_detail_is_rejected():
    for q in ({"detail": "nope", "by": "operator", "key": "x"},
              {"detail": "train_list", "by": "wat", "key": "x"},
              {"detail": "train_list", "by": "operator"},
              {"detail": "train_list", "by": "hour", "key": "abc"},
              {"detail": "train_list", "by": "heat", "key": "9-1"},
              {"detail": "train_list", "by": "operator", "key": "x" * 200},
              {"detail": "train_list", "by": "operator", "key": "x", "board": "sideways"}):
        with pytest.raises(ValueError):
            so.parse_detail(q)
