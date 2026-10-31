# © 2026 Andy217Ace
"""Pagina „Sistem”: starea panoului (LIVE / date vechi / necunoscut), rata de rânduri
necitite din ultima oră, spațiu și mărimea bazei. Valoarea lipsă e „necunoscut”, nu 0."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app import system_status
from app.ocr import stats as ocr_stats
from app.store import SCHEMA_VERSION, Store
from app.version import __version__

TZ = ZoneInfo("Europe/Bucharest")
NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=TZ)


def _frame(rows, unread, empty=0):
    """One frame summary as app.ocr.reader._summary builds it (one panel shown)."""
    board = {"lines": rows + unread + empty, "rows": rows, "unread": unread, "empty": empty,
             "groups_repaired": 0, "retried": 0, "recovered": 0}
    return {"boards": {"arrival": board, "departure": dict(board, rows=0, unread=0)},
            "retried": 0, "recovered": 0, "retry_ms": 0, "duration_ms": 1}


@pytest.fixture(autouse=True)
def _no_error_leak(monkeypatch):
    """The last poller error is process-wide: every test starts without one."""
    monkeypatch.setattr(system_status, "_last_error", None)


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "tabela.db"))
    s.migrate()
    yield s
    s.close()


def _ok_run(store, when: datetime):
    """A successful reading stored at `when` (same timestamp format as Store.ingest)."""
    store._conn.execute("INSERT INTO runs(ts, image_hash, ok, n_rows) VALUES (?,'',1,12)",
                        (when.isoformat(),))


def _settings(db_path):
    return SimpleNamespace(db_path=str(db_path))


# -- panel state ---------------------------------------------------------------------

def test_panel_state_live_old_unknown():
    assert system_status.STALE_PANEL_S == 600  # 10 minutes without a good reading
    assert system_status.panel_state(0) == "live"
    assert system_status.panel_state(600) == "live"
    assert system_status.panel_state(601) == "date_vechi"
    assert system_status.panel_state(None) == "necunoscut"


# -- OCR unread rate (last hour = the last 60 frames) ---------------------------------

def test_unread_rate_is_unread_over_text_lines():
    for _ in range(10):
        ocr_stats.record(_frame(rows=6, unread=2, empty=4))
    rate, n = ocr_stats.unread_rate_1h()
    assert n == 10
    assert rate == pytest.approx(2 / 8)  # text lines = rows + unread; empty lines ignored


def test_unread_rate_missing_is_none_not_zero():
    assert ocr_stats.unread_rate_1h() == (None, 0)
    ocr_stats.record(_frame(rows=0, unread=0, empty=12))  # only empty lines: no text
    assert ocr_stats.unread_rate_1h() == (None, 1)


def test_unread_rate_window_is_last_60_frames():
    for _ in range(60):
        ocr_stats.record(_frame(rows=1, unread=1))  # 50 % unread
    for _ in range(60):
        ocr_stats.record(_frame(rows=4, unread=0))  # pushes the old frames out
    rate, n = ocr_stats.unread_rate_1h()
    assert n == 60
    assert rate == 0.0


# -- collect_status -------------------------------------------------------------------

def test_public_status_fields_and_live(store, tmp_path):
    _ok_run(store, NOW - timedelta(seconds=30))
    st = system_status.collect_status(store, _settings(tmp_path / "tabela.db"), NOW)
    assert st["version"] == __version__
    assert st["schema"] == SCHEMA_VERSION
    assert st["stare"] == "live"
    assert st["poller"]["last_ok_age_s"] == pytest.approx(30, abs=1)
    assert st["poller"]["last_error"] is None
    assert st["ocr"] == {"unread_rate_1h": None, "n": 0, "insufficient": True}
    assert isinstance(st["uptime_s"], int) and st["uptime_s"] >= 0
    assert st["disk"]["free_gb"] > 0
    assert set(st["db"]) == {"size_mb", "wal_mb"}


def test_old_reading_shows_date_vechi_not_live(store, tmp_path):
    _ok_run(store, NOW - timedelta(minutes=11))
    st = system_status.collect_status(store, _settings(tmp_path / "tabela.db"), NOW)
    assert st["stare"] == "date_vechi"


def test_never_read_is_necunoscut_with_null_age(store, tmp_path):
    st = system_status.collect_status(store, _settings(tmp_path / "tabela.db"), NOW)
    assert st["stare"] == "necunoscut"
    assert st["poller"]["last_ok_age_s"] is None  # missing, not 0


def test_missing_db_file_gives_null_size(store, tmp_path):
    st = system_status.collect_status(store, _settings(tmp_path / "nu-exista.db"), NOW)
    assert st["db"]["size_mb"] is None


def test_insufficient_ocr_data_is_flagged(store, tmp_path):
    for _ in range(3):
        ocr_stats.record(_frame(rows=2, unread=2))
    st = system_status.collect_status(store, _settings(tmp_path / "tabela.db"), NOW)
    assert st["ocr"]["n"] == 3
    assert st["ocr"]["unread_rate_1h"] == pytest.approx(0.5)
    assert st["ocr"]["insufficient"] is True


def test_last_error_is_a_short_code_only(store, tmp_path, monkeypatch):
    monkeypatch.setattr(system_status, "_last_error", None)
    system_status.record_error("fetch", NOW.timestamp())
    system_status.record_error("ocr", NOW.timestamp())
    st = system_status.collect_status(store, _settings(tmp_path / "tabela.db"), NOW)
    assert st["poller"]["last_error"] == "ocr"


def test_unknown_error_code_becomes_other(monkeypatch):
    monkeypatch.setattr(system_status, "_last_error", None)
    system_status.record_error("Traceback (most recent call last): /etc/x", NOW.timestamp())
    assert system_status.last_error() == ("other", NOW.timestamp())


def test_public_output_leaks_no_paths_tokens_or_env(store, tmp_path, monkeypatch):
    secret = "tok-SECRET-123456"
    monkeypatch.setenv("ADMIN_TOKEN", secret)
    db = tmp_path / "tabela.db"
    _ok_run(store, NOW - timedelta(seconds=5))
    st = system_status.collect_status(store, _settings(db), NOW)
    text = json.dumps(st)
    assert secret not in text
    assert str(tmp_path) not in text
    assert "tabela.db" not in text
    assert "ADMIN_TOKEN" not in text


def test_admin_adds_details_but_still_no_paths(store, tmp_path):
    db = tmp_path / "tabela.db"
    _ok_run(store, NOW - timedelta(seconds=5))
    pub = system_status.collect_status(store, _settings(db), NOW)
    adm = system_status.collect_status(store, _settings(db), NOW, admin=True)
    assert set(pub) < set(adm)
    assert "ocr_window" in adm and "total_gb" in adm["disk"]
    assert str(tmp_path) not in json.dumps(adm)
    assert "tabela.db" not in json.dumps(adm)
