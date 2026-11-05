# © 2026 Andy217Ace
"""Colectorul NVMe (scripts/nvme_collect.py). Rulează ca root din timer, dar în teste
comenzile sunt înlocuite cu un runner fals: nimic nu atinge discul."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

from app import nvme_status

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "nvme"
FORBIDDEN = {"format", "-t", "set-feature", "device-self-test", "sanitize", "reset",
             "--force", "-s", "-X", "-i", "write", "-W", "-e", "-d", "-S", "-o"}


def _load():
    spec = importlib.util.spec_from_file_location("nvme_collect", ROOT / "scripts" / "nvme_collect.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


nc = _load()


class Fake:
    """Runner care întoarce ieșirea fixture-urilor și ține minte fiecare comandă."""

    def __init__(self, fail=(), empty=()):
        self.calls = []
        self.fail = set(fail)
        self.empty = set(empty)

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        kind = nc.KIND_BY_ARGV[tuple(argv)]
        if kind in self.fail:
            raise OSError("nu exista")
        out = "" if kind in self.empty else (FIX / {
            "smart_log": "smart_log.txt", "error_log": "error_log.txt",
            "smartctl": "smartctl_a.txt"}[kind]).read_text(encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


def test_collect_reference_values():
    snap = nc.collect(runner=Fake(), now=1_000_000.0)
    assert snap["schema"] == nvme_status.SCHEMA
    assert snap["ok"] is True and snap["error"] is None
    assert snap["collected_ts"] == 1_000_000.0
    assert snap["device"]["model"] == "KINGSTON RBUSNS8154P3512GJ1"
    assert snap["smart_log"]["temperature_c"] == 32
    assert snap["smart_log"]["unsafe_shutdowns"] == 371
    assert snap["smart_log"]["num_err_log_entries"] == 3920
    assert snap["smartctl"]["overall_health"] == "PASSED"
    assert snap["error_log"][0]["error_count"] == 3920


def test_commands_are_read_only_and_fixed():
    fake = Fake()
    nc.collect(runner=fake, now=1.0)
    argvs = [a for a, _ in fake.calls]
    assert sorted(argvs) == sorted([
        ["nvme", "smart-log", "/dev/nvme0"],
        ["nvme", "error-log", "/dev/nvme0", "--log-entries=5"],
        ["smartctl", "-a", "/dev/nvme0"],
    ])
    for argv in argvs:
        assert not FORBIDDEN & set(argv), argv
    for _, kw in fake.calls:
        assert kw.get("shell") in (None, False)
        assert kw.get("timeout") == nc.CMD_TIMEOUT_S


def test_missing_smart_log_is_reported_not_zero():
    snap = nc.collect(runner=Fake(fail={"smart_log"}), now=1.0)
    assert snap["ok"] is False and snap["error"] == "smart_log"
    assert snap["smart_log"] is None
    assert snap["smartctl"]["overall_health"] == "PASSED"  # celelalte surse rămân


def test_empty_smartctl_output_is_error():
    snap = nc.collect(runner=Fake(empty={"smartctl"}), now=1.0)
    assert snap["ok"] is False and snap["error"] == "smartctl"


def test_snapshot_has_no_serial_or_device_path():
    text = json.dumps(nc.collect(runner=Fake(), now=1.0))
    assert "FIXTURE0000000" not in text
    assert "/dev/" not in text


def test_snapshot_readable_by_app(tmp_path):
    p = tmp_path / "nvme.json"
    nc.write_atomic(p, nc.collect(runner=Fake(), now=1_000_000.0))
    out = nvme_status.read_snapshot(p, 1_000_060.0)
    assert out["available"] is True and out["ok"] is True and out["age_s"] == 60
    assert out["smart_log"]["temperature_c"] == 32


def test_write_atomic_replaces_and_leaves_no_tmp(tmp_path):
    p = tmp_path / "nvme.json"
    p.write_text("vechi", encoding="utf-8")
    nc.write_atomic(p, {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}
    assert sorted(x.name for x in tmp_path.iterdir()) == ["nvme.json"]


@pytest.mark.skipif(os.name == "nt", reason="permisiunile POSIX nu există pe Windows")
def test_write_atomic_mode_0640(tmp_path):
    p = tmp_path / "nvme.json"
    nc.write_atomic(p, {"a": 1})
    assert oct(p.stat().st_mode & 0o777) == "0o640"


def test_main_writes_to_given_path(tmp_path, monkeypatch):
    p = tmp_path / "nvme.json"
    monkeypatch.setattr(nc, "_run", Fake())
    assert nc.main([str(p)]) == 0
    assert json.loads(p.read_text(encoding="utf-8"))["ok"] is True
