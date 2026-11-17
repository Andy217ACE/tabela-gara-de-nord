# © 2026 Andy217Ace
"""Watchdog: repornire de serviciu / deploy în timpul verificării (Review Focus 5)."""
import json

from app import watchdog


def _run(tmp_path, monkeypatch, healthy):
    calls = []
    monkeypatch.setattr(watchdog, "health_ok", lambda url, timeout_s=0: healthy())
    monkeypatch.setattr(watchdog, "restart_service", lambda name: calls.append(name))
    st = tmp_path / "w.json"
    rc = watchdog.main(["--state", str(st)])
    return rc, st, calls


def test_corrupt_state_file_starts_clean(tmp_path, monkeypatch):
    (tmp_path / "w.json").write_text("{not json", encoding="utf-8")
    rc, st, calls = _run(tmp_path, monkeypatch, lambda: False)
    assert rc == 0 and calls == []
    assert json.loads(st.read_text())["failures"] == 1


def test_connection_refused_during_restart_counts_as_failure(tmp_path, monkeypatch):
    def boom():
        raise ConnectionError("refused")
    rc, st, _ = _run(tmp_path, monkeypatch, boom)
    assert rc == 0 and json.loads(st.read_text())["failures"] == 1


def test_three_runs_restart_once_across_processes(tmp_path, monkeypatch):
    for _ in range(3):
        _, _, calls = _run(tmp_path, monkeypatch, lambda: False)
    assert calls == ["tabela"]


def test_nginx_never_restarted(tmp_path, monkeypatch):
    for _ in range(6):
        _, _, calls = _run(tmp_path, monkeypatch, lambda: False)
    assert set(calls) <= {"tabela"}
