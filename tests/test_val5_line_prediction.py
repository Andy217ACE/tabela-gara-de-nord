# © 2026 Andy217Ace
"""Val 5b: estimarea întârzierii finale pentru un tren (payload pentru GET
/api/trains/{no}/prediction). Pur, fără scriere; poarta decide dacă se arată ceva."""
import sqlite3
from datetime import date, timedelta

from app import line_prediction as lp
from app import predict as pr


def jr(i, day, final, no=100, station="Brasov", board="arrival", base=0, sched="10:05"):
    return pr.Journey(i, no, board, station, day.isoformat(), sched, final, base)


def _hist(n, no=100, finals=None):
    d0 = date(2026, 10, 1)
    return [jr(i, d0 + timedelta(days=i), (finals or [5])[i % len(finals or [5])], no=no)
            for i in range(n)]


def test_below_threshold_returns_no_estimate():
    out = lp.estimate(_hist(5), 100, date(2026, 11, 20), published=True)
    assert out["estimates"] == [] and out["label"] == "Estimare"


def test_estimate_has_n_interval_and_basis():
    out = lp.estimate(_hist(12, finals=[2, 4, 6, 8]), 100, date(2026, 11, 20), published=True)
    e = out["estimates"][0]
    assert e["n"] >= 10 and e["low"] <= e["delay_min"] <= e["high"]
    assert e["basis"] in ("a", "b", "c") and e["board"] == "arrival"


def test_not_published_hides_estimates_and_gives_reason():
    out = lp.estimate(_hist(40), 100, date(2026, 11, 20), published=False, reason="nepublicat: x")
    assert out["published"] is False and out["estimates"] == [] and out["reason"] == "nepublicat: x"


def test_other_train_is_not_used():
    out = lp.estimate(_hist(40, no=200), 100, date(2026, 11, 20), published=True)
    assert out["estimates"] == []


def test_future_target_day_not_in_history_and_read_only(tmp_path):
    p = tmp_path / "t.db"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE t(x)")
    c.commit()
    before = c.total_changes
    lp.estimate(_hist(12), 100, date(2026, 11, 20), published=True)
    assert c.total_changes == before


def test_payload_text_is_not_causal():
    out = lp.estimate(_hist(12), 100, date(2026, 11, 20), published=True)
    for w in ("din cauza", "provocat", "datorită"):
        assert w not in out["note"].lower()
    assert "estimare" in out["note"].lower()
