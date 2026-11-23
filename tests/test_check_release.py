# © 2026 Andy217Ace
"""scripts/check_release.py: the repo passes, and each kind of drift is caught."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_release as cr  # noqa: E402

CL = "# x\n## Beta 1.05 — 2026-01-01\n### Adăugat\n- ceva\n### English\n- thing\n## Beta 1.04 — 2026-01-01\n- old\n"
UI = 'var CHARTS_V = "1.05";'


def test_repo_is_consistent():
    assert cr.main() == 0


def test_ok_sample():
    assert cr.problems("Beta 1.05\n", CL, UI) == []


def test_drift_is_caught():
    assert cr.problems("Beta 1.06", CL, UI)                                  # version vs changelog
    assert cr.problems("Beta 1.05", CL, 'CHARTS_V = "1.04"')                 # cache buster
    assert cr.problems("Beta 1.05", CL.replace("### English\n- thing\n", ""), UI)   # no English
    assert cr.problems("Beta 1.05", CL.replace("- thing\n", ""), UI)         # empty English
    assert cr.problems("Beta 1.05", CL.replace("- ceva\n", ""), UI)          # no Romanian bullets
    assert cr.problems("v5", CL, UI)
