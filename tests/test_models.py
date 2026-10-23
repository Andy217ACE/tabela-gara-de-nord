# © 2026 Andy217Ace
import json
from pathlib import Path

from app.models import Row


def test_row_key_and_defaults():
    r = Row("arrival", "IR", 1636, "BRASOV", "CFR Calatori", "20:04")
    assert r.key == ("arrival", 1636, "20:04")
    assert r.delay_min == 0
    assert r.platform is None
    assert r.flagged is False
    assert r.confidence == 1.0


def test_golden_fixture_loads():
    data = json.loads((Path(__file__).parent / "fixtures" / "board_1.json").read_text(encoding="utf-8"))
    assert len(data["arrival"]) == 12
    assert len(data["departure"]) == 12
    rows = [Row(board=b, **d) for b in ("arrival", "departure") for d in data[b]]
    assert rows[0].key == ("arrival", 1636, "20:04")
    assert rows[0].delay_min == 10 and rows[0].platform == 13 and rows[0].flagged
