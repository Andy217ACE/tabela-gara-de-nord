# © 2026 Andy217Ace
import importlib.util
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app.models import Row
from app.store import TZ, Store

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "dev_seed.py"


def test_dev_seed_has_no_test_dependency():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "tests.conftest" not in src and "pytest" not in src


def test_golden_rows_are_the_expected_reading_of_board_1():
    spec = importlib.util.spec_from_file_location("dev_seed", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rows = mod.golden_rows()
    assert len(rows) == 24
    assert rows[0].key == ("arrival", 1636, "20:04") and rows[0].delay_min == 10
    assert sum(r.board == "departure" for r in rows) == 12


def test_dev_seed_refuses_non_empty_db_without_force(tmp_path):
    db = tmp_path / "x.db"
    s = Store(str(db))
    s.migrate()
    rows = [Row(board=b, train_type="IR", train_no=n, station="Brasov", operator="CFR",
                sched_time=t, delay_min=0, platform=None)
            for b, n, t in (("arrival", 1, "12:10"), ("arrival", 2, "12:20"),
                            ("departure", 3, "12:15"), ("departure", 4, "12:30"))]
    s.ingest(rows, datetime.now(TZ))
    s.close()
    p = subprocess.run([sys.executable, str(SCRIPT), str(db)], capture_output=True, text=True)
    assert p.returncode != 0
    assert "--force" in (p.stderr + p.stdout)
