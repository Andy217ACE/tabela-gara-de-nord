# © 2026 Andy217Ace
"""scripts/ops_alerts.py: verificări cu date simulate, dedup/cooldown/„rezolvat”, no-op fără Telegram."""
import importlib.util
import sqlite3
from collections import namedtuple
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("ops_alerts", ROOT / "scripts" / "ops_alerts.py")
oa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oa)

HEALTHY = {"ok": True, "age_s": 30, "boards": {"arrivals": {"stale": False},
                                               "departures": {"stale": False}},
           "ocr": {"window": {"frames": 60, "full_frames": 58}}}


def _levels(results):
    return {k: lvl for k, lvl, _ in results}


def test_health_ok_stale_and_down():
    assert set(_levels(oa.check_health("local", "u", lambda u: HEALTHY)).values()) == {"ok"}
    stale = {**HEALTHY, "ok": False, "boards": {"arrivals": {"stale": True}}}
    assert _levels(oa.check_health("local", "u", lambda u: stale))["boards"] == "warn"
    bad_ocr = {**HEALTHY, "ocr": {"window": {"frames": 60, "full_frames": 10}}}
    assert _levels(oa.check_health("local", "u", lambda u: bad_ocr))["ocr"] == "warn"
    few = {**HEALTHY, "ocr": {"window": {"frames": 3, "full_frames": 0}}}
    assert _levels(oa.check_health("local", "u", lambda u: few))["ocr"] == "ok"

    def down(u):
        raise OSError("refused")
    assert oa.check_health("public", "u", down) == [
        ("health:public", "crit", "u nu răspunde (OSError)")]
    # public: doar răspunsul contează (panourile/OCR se judecă pe cel local)
    assert list(_levels(oa.check_health("public", "u", lambda u: stale))) == ["health:public"]


def test_disk_thresholds(tmp_path):
    U = namedtuple("U", "total used free")
    for used, level in ((50, "ok"), (90, "warn"), (96, "crit")):
        r = oa.check_disks([str(tmp_path), str(tmp_path / "missing")],
                           usage=lambda p: U(100, used, 100 - used))
        assert [x[1] for x in r] == [level]   # cale lipsă ignorată


def _run(timer_active, failed=""):
    def run(*args):
        if args[0] == "is-active":
            return SimpleNamespace(returncode=0 if timer_active else 3, stdout="")
        return SimpleNamespace(returncode=0, stdout=failed)
    return run


def test_infofer_stale_only_when_timer_active(tmp_path):
    db = tmp_path / "infofer.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE infofer_runs (fetched_at TEXT, n_markers INTEGER)")
    t0 = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
    c.execute("INSERT INTO infofer_runs VALUES (?, 40)", (t0.isoformat(timespec="seconds"),))
    c.execute("INSERT INTO infofer_runs VALUES (?, 0)", ("2026-11-28T12:30:00+00:00",))
    c.commit(); c.close()
    now = t0.timestamp()
    assert oa.check_infofer(now + 600, db, _run(True))[0][1] == "ok"
    assert oa.check_infofer(now + 1200, db, _run(True))[0][1] == "warn"   # eșecul de la 12:30 nu contează
    assert oa.check_infofer(now + 1200, db, _run(False))[0][1] == "ok"
    assert oa.check_infofer(now, tmp_path / "nu.db", _run(True))[0][1] == "warn"


def test_failed_units():
    assert oa.check_units(_run(True))[0][1] == "ok"
    r = oa.check_units(_run(True, "tabela-infofer.service loaded failed failed X\n"))
    assert r == [("units", "crit", "unități căzute: tabela-infofer.service")]


def test_evaluate_debounce_cooldown_escalation_and_recovery():
    st, warn, crit, ok = {}, [("d", "warn", "disc")], [("d", "crit", "disc")], [("d", "ok", "disc ok")]
    assert oa.evaluate(warn, st, 0) == []                       # prima rulare proastă: tăcere
    assert oa.evaluate(warn, st, 300) == ["[ATENȚIE] disc"]
    assert oa.evaluate(warn, st, 600) == []                     # cooldown
    assert oa.evaluate(crit, st, 900) == ["[CRITIC] disc"]      # agravare: imediat
    assert oa.evaluate(crit, st, 1200) == []
    assert oa.evaluate(crit, st, 900 + oa.COOLDOWN_S) == ["[CRITIC] disc"]  # reamintire
    assert oa.evaluate(ok, st, 99999) == ["[REZOLVAT] disc ok"] and st == {}
    # o singură rulare proastă, apoi ok: nimic de anunțat
    assert oa.evaluate(warn, st, 0) == [] and oa.evaluate(ok, st, 300) == [] and st == {}


def test_main_is_noop_without_telegram(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    def boom(now):
        raise AssertionError("nu trebuie să verifice nimic")
    state = tmp_path / "s.json"
    assert oa.main(["--state", str(state)], checks=boom) == 0
    assert not state.exists() and "nesetate" in capsys.readouterr().out


def test_main_sends_once_and_persists_state(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    sent, state = [], tmp_path / "s.json"
    checks = lambda now: [("units", "crit", "unități căzute: a")]  # noqa: E731
    for t in (0, 300, 600):
        oa.main(["--state", str(state)], checks=checks,
                sender=lambda cfg, m: sent.append(m), clock=lambda t=t: t)
    assert sent == ["[CRITIC] unități căzute: a"]
    oa.main(["--state", str(state)], checks=lambda now: [("units", "ok", "toate ok")],
            sender=lambda cfg, m: sent.append(m), clock=lambda: 900)
    assert sent[-1] == "[REZOLVAT] toate ok"
