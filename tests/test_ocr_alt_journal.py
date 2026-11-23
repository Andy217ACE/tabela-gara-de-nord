# © 2026 Andy217Ace
"""Jurnalul alternativei OCR: inregistrare (umbra/activ), crop-uri, retentie, verdicte, totaluri."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.ocr import alt_journal as j
from app.ocr import alt_reader as alt
from tests.test_ocr_alt_reader import MODEL, fake_panels, make_cell, read_entries  # noqa: F401

NOW = datetime(2026, 11, 23, 12, 0, 0, tzinfo=timezone.utc)


def _apply(monkeypatch, fake_panels, shadow):  # noqa: F811
    monkeypatch.setenv("OCR_ALT", "1")
    if shadow:
        monkeypatch.setenv("OCR_ALT_SHADOW", "1")
    es = read_entries()
    fake_panels({"arrival": {2: {"no": make_cell("7942"), "time": make_cell("10:20")}}})
    return es, alt.apply(b"img", es, MODEL)


@pytest.mark.parametrize("shadow", [True, False])
def test_records_in_both_modes(monkeypatch, fake_panels, shadow):  # noqa: F811
    es, info = _apply(monkeypatch, fake_panels, shadow)
    assert info["recovered"] == 1 and "cells" not in info
    json.dumps(info)
    (ev,), nxt = j.list_events()
    assert nxt is None and ev["shadow"] is shadow and ev["board"] == "arrival"
    assert ev["row_index"] == 2 and ev["cols"] == ["no", "time"]
    assert ev["values"] == {"no": 7942, "time": "10:20"} and 0.99 <= ev["prob"] <= 1
    assert ev["context"]["type"] == "R" and ev["context"]["station"] == "BRASOV"
    for c in ev["cols"]:
        assert j.crop_path(ev["id"], c).read_bytes()[:4] == b"\x89PNG"


def test_journal_error_does_not_break_apply(monkeypatch, fake_panels, caplog):  # noqa: F811
    monkeypatch.setattr(j, "_png", lambda cell: 1 / 0)
    with caplog.at_level("WARNING"):
        es, info = _apply(monkeypatch, fake_panels, False)
    assert info["recovered"] == 1 and es[2]["row"].train_no == 7942
    assert any("jurnalul" in r.getMessage() for r in caplog.records)


def _seed(ids_ts, verdicts=True):
    """Evenimente + crop-uri (+ verdicte 'correct') scrise direct."""
    d = j.journal_dir()
    (d / "crops").mkdir(parents=True, exist_ok=True)
    v = {}
    with open(d / "events.jsonl", "w") as fh:
        for eid, ts in ids_ts:
            fh.write(json.dumps({"id": eid, "ts": ts.isoformat(timespec="seconds"), "shadow": True,
                                 "board": "arrival", "row_index": 1, "cols": ["no"],
                                 "values": {"no": 1}, "prob": 0.99, "context": {}}) + "\n")
            (d / "crops" / f"{eid}_no.png").write_bytes(b"x")
            v[eid] = {"verdict": "correct", "at": "x"}
    if verdicts:
        (d / "verdicts.json").write_text(json.dumps(v))


def _id(n):
    return f"20261123T1200{n:02d}-arrival-1"


def test_retention_by_age():
    _seed([(_id(1), NOW - timedelta(days=31)), (_id(2), NOW - timedelta(days=1))])
    j.prune(NOW, force=True)
    assert [e["id"] for e in j.list_events()[0]] == [_id(2)]
    assert j.crop_path(_id(1), "no") is None and j.crop_path(_id(2), "no")
    assert list(json.loads((j.journal_dir() / "verdicts.json").read_text())) == [_id(2)]


def test_retention_by_count(monkeypatch):
    monkeypatch.setattr(j, "MAX_EVENTS", 3)
    _seed([(_id(n), NOW) for n in range(1, 6)])
    j.prune(NOW, force=True)
    assert [e["id"] for e in j.list_events()[0]] == [_id(5), _id(4), _id(3)]
    assert j.crop_path(_id(1), "no") is None and j.crop_path(_id(3), "no")
    kept = json.loads((j.journal_dir() / "verdicts.json").read_text())
    assert set(kept) == {_id(3), _id(4), _id(5)}


def test_prune_runs_at_most_hourly():
    _seed([(_id(1), NOW - timedelta(days=40))])
    j.prune(NOW)  # prima rulare: sterge
    assert j.list_events()[0] == []
    with open(j.journal_dir() / "events.jsonl", "a") as fh:
        fh.write(json.dumps({"id": _id(9), "ts": "2000-01-01T00:00:00", "cols": []}) + "\n")
    j.prune(NOW)  # sub o ora: nu atinge nimic
    assert [e["id"] for e in j._events()] == [_id(9)]


def test_verdict_set_clear_and_totals():
    _seed([(_id(n), NOW) for n in range(1, 5)], verdicts=False)
    assert j.totals() == {"events": 4, "verified": 0, "correct": 0, "wrong": 0, "unclear": 0,
                          "precision": None, "n_precision": 0}
    assert j.set_verdict(_id(1), "correct") and j.set_verdict(_id(2), "correct")
    assert j.set_verdict(_id(3), "wrong") and j.set_verdict(_id(4), "unclear")
    t = j.totals()
    assert t["verified"] == 4 and t["precision"] == pytest.approx(0.6667, abs=1e-4)
    assert t["n_precision"] == 3
    assert j.set_verdict(_id(3), None) and j.totals()["precision"] == 1.0
    assert not j.set_verdict("20200101T000000-arrival-9", "correct")
    assert not (j.journal_dir() / "verdicts.json.tmp").exists()


def test_paging_and_unverified_filter():
    _seed([(_id(n), NOW) for n in range(1, 6)], verdicts=False)
    (j.journal_dir() / "verdicts.json").write_text(json.dumps({_id(4): {"verdict": "wrong"}}))
    page, nxt = j.list_events(limit=2)
    assert [e["id"] for e in page] == [_id(5), _id(4)] and nxt == _id(4)
    page, nxt = j.list_events(limit=2, before=nxt)
    assert [e["id"] for e in page] == [_id(3), _id(2)] and nxt == _id(2)
    page, nxt = j.list_events(limit=2, before=nxt)
    assert [e["id"] for e in page] == [_id(1)] and nxt is None
    page, _ = j.list_events(limit=10, only="unverified")
    assert [e["id"] for e in page] == [_id(5), _id(3), _id(2), _id(1)]
