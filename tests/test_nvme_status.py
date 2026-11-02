# © 2026 Andy217Ace
"""Parserele pentru `nvme smart-log`, `nvme error-log` și `smartctl -a` (fixture-uri din
tests/fixtures/nvme/) și citirea fișierului JSON scris de colector."""
import json
from pathlib import Path

import pytest

from app import nvme_status

FIX = Path(__file__).resolve().parent / "fixtures" / "nvme"


def _read(name):
    return (FIX / name).read_text(encoding="utf-8")


# -- nvme smart-log ----------------------------------------------------------------------

def test_smart_log_reference_values():
    s = nvme_status.parse_smart_log(_read("smart_log.txt"))
    assert s["critical_warning"] == 0
    assert s["temperature_c"] == 32
    assert s["available_spare"] == 100
    assert s["available_spare_threshold"] == 10
    assert s["percentage_used"] == 0
    assert s["data_units_read"] == 12345678
    assert s["data_units_written"] == 9876543
    assert s["host_read_commands"] == 123456789
    assert s["host_write_commands"] == 98765432
    assert s["controller_busy_time"] == 1234
    assert s["power_cycles"] == 412
    assert s["power_on_hours"] == 6736
    assert s["unsafe_shutdowns"] == 371
    assert s["media_errors"] == 0
    assert s["num_err_log_entries"] == 3920


def test_smart_log_keeps_every_field_and_no_header():
    s = nvme_status.parse_smart_log(_read("smart_log.txt"))
    assert "endurance_group_critical_warning_summary" in s
    assert s["warning_temperature_time"] == 0
    assert s["critical_composite_temperature_time"] == 0
    assert not any(k.startswith("smart_log") for k in s)


def test_smart_log_ignores_garbage_lines():
    s = nvme_status.parse_smart_log("nimic util\ntemperature : 40 C (313 Kelvin)\n\n")
    assert s == {"temperature_c": 40}


# -- smartctl -a (sectiunea NVMe) --------------------------------------------------------

def test_smartctl_health_and_model():
    c = nvme_status.parse_smartctl(_read("smartctl_a.txt"))
    assert c["overall_health"] == "PASSED"
    assert c["model"] == "KINGSTON RBUSNS8154P3512GJ1"
    assert "serial" not in c and "serial_number" not in c["health"]


def test_smartctl_health_fields():
    h = nvme_status.parse_smartctl(_read("smartctl_a.txt"))["health"]
    assert h["temperature"] == 32
    assert h["available_spare"] == 100
    assert h["percentage_used"] == 0
    assert h["unsafe_shutdowns"] == 371
    assert h["media_and_data_integrity_errors"] == 0
    assert h["error_information_log_entries"] == 3920
    assert h["power_on_hours"] == 6736
    assert h["critical_warning"] == 0


def test_smartctl_failed_health():
    c = nvme_status.parse_smartctl("SMART overall-health self-assessment test result: FAILED!\n")
    assert c["overall_health"] == "FAILED!"


def test_smartctl_missing_health_is_none():
    assert nvme_status.parse_smartctl("")["overall_health"] is None


# -- nvme error-log ----------------------------------------------------------------------

def test_error_log_entries_in_order_with_fields():
    e = nvme_status.parse_error_log(_read("error_log.txt"))
    assert len(e) == 2
    assert e[0]["error_count"] == 3920
    assert e[0]["sqid"] == 0
    assert e[0]["cmdid"] == 0x1F
    assert e[0]["status_field"] == "0x4004 (INVALID_FIELD)"
    assert e[0]["parm_err_loc"] == 0x28
    assert e[0]["lba"] == 0 and e[0]["nsid"] == 0
    assert e[1]["error_count"] == 3919


def test_error_log_limited_to_five():
    text = _read("error_log.txt")
    block = text[text.index(" Entry[ 0]"):]
    many = "".join(block.replace("Entry[ 0]", f"Entry[{i:2d}]") for i in range(8))
    assert len(nvme_status.parse_error_log(many)) == 5


def test_error_log_empty():
    assert nvme_status.parse_error_log("Error Log Entries for device:nvme0 entries:0\n") == []


# -- fisierul colectorului ---------------------------------------------------------------

def _snapshot(**kw):
    base = {
        "schema": 1,
        "collected_ts": 1_000_000.0,
        "collected_at": "2026-11-02T10:00:00+02:00",
        "ok": True,
        "error": None,
        "device": {"model": "KINGSTON RBUSNS8154P3512GJ1"},
        "smart_log": {"temperature_c": 32},
        "smartctl": {"overall_health": "PASSED", "health": {}},
        "error_log": [],
    }
    base.update(kw)
    return base


def test_snapshot_missing_file(tmp_path):
    out = nvme_status.read_snapshot(tmp_path / "nvme.json", 1_000_100.0)
    assert out == {"available": False}


def test_snapshot_invalid_json_is_missing(tmp_path):
    p = tmp_path / "nvme.json"
    p.write_text("{nu-e-json", encoding="utf-8")
    assert nvme_status.read_snapshot(p, 1_000_100.0) == {"available": False}


def test_snapshot_age_and_stale(tmp_path):
    p = tmp_path / "nvme.json"
    p.write_text(json.dumps(_snapshot()), encoding="utf-8")
    fresh = nvme_status.read_snapshot(p, 1_000_100.0)
    assert fresh["available"] is True and fresh["age_s"] == 100
    assert fresh["stale"] is False
    assert fresh["collected_at"] == "2026-11-02T10:00:00+02:00"
    assert fresh["smart_log"] == {"temperature_c": 32}
    old = nvme_status.read_snapshot(p, 1_000_000.0 + nvme_status.STALE_S + 1)
    assert old["stale"] is True


def test_snapshot_drops_unknown_top_level_keys(tmp_path):
    p = tmp_path / "nvme.json"
    p.write_text(json.dumps(_snapshot(path="/dev/nvme0", secret="x")), encoding="utf-8")
    out = nvme_status.read_snapshot(p, 1_000_100.0)
    assert "path" not in out and "secret" not in out


# -- endpoint-ul admin -------------------------------------------------------------------

TOKEN = "t" * 20 + "-secret-admin-token"  # 40 caractere
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def nvme_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.api import create_app
    from app.config import Settings
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.delenv("ADMIN_TOKEN_STRICT", raising=False)
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "bk"))
    db = tmp_path / "tabela.db"
    s = Settings(db_path=str(db), source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c",
                 tesseract_cmd="tesseract-does-not-exist", poller_restart_backoff=0.01)
    app = create_app(s, start_poller=False)
    with TestClient(app, base_url="https://testserver") as c:
        yield c, tmp_path


def test_nvme_endpoint_needs_admin(nvme_client):
    c, _ = nvme_client
    assert c.get("/api/admin/tools/nvme").status_code == 401


def test_nvme_endpoint_missing_file(nvme_client):
    c, _ = nvme_client
    r = c.get("/api/admin/tools/nvme", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "generated_at" in body


def test_nvme_endpoint_serves_snapshot_without_paths(nvme_client):
    import time
    c, tmp = nvme_client
    snap = {"schema": 1, "collected_ts": time.time(), "collected_at": "2026-11-02T10:00:00+02:00",
            "ok": True, "error": None, "device": {"model": "KINGSTON RBUSNS8154P3512GJ1"},
            "smart_log": {"temperature_c": 32, "unsafe_shutdowns": 371},
            "smartctl": {"overall_health": "PASSED", "health": {"temperature": 32}},
            "error_log": [{"error_count": 3920}]}
    (tmp / "nvme.json").write_text(json.dumps(snap), encoding="utf-8")
    body = c.get("/api/admin/tools/nvme", headers=AUTH).json()
    assert body["available"] is True and body["stale"] is False
    assert body["smart_log"]["unsafe_shutdowns"] == 371
    assert body["smartctl"]["overall_health"] == "PASSED"
    assert body["error_log"] == [{"error_count": 3920}]
    text = json.dumps(body)
    assert str(tmp) not in text and "/dev/" not in text
