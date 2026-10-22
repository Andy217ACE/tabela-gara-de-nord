# © 2026 Andy217Ace
"""/api/weather, /api/health weather_age_s, /api/config weather block, lifespan task."""
import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import EMPTY_OCR
from fastapi.testclient import TestClient

from app.version import __version__
from app import weather as wx
from app.api import create_app
from tests.test_api import BUC, ingest, settings

UTC = timezone.utc


def wcfg():
    return wx.WeatherConfig(url="https://example.invalid/forecast", latitude=44.4323,
                            longitude=26.1063, interval_s=900)


def seed(c, minutes_ago=5, **current):
    from tests.test_weather import payload
    now = datetime.now(UTC)
    t = (now - timedelta(minutes=minutes_ago)).replace(second=0, microsecond=0)
    o = wx.parse_observation(payload(time=t.strftime("%Y-%m-%dT%H:%M"), **current), now)
    c.app.state.store.add_weather(o)
    return o


@pytest.fixture
def client():
    with TestClient(create_app(settings(), start_poller=False)) as c:
        yield c


def test_weather_unavailable_without_data(client):
    r = client.get("/api/weather")
    assert r.status_code == 200
    j = r.json()
    assert j["available"] is False and j["kind"] == "model_current"
    assert j["attribution"] == {"source": "Open-Meteo.com", "url": "https://open-meteo.com/",
                                "license": "CC BY 4.0"}


def test_weather_shape(client):
    seed(client, 5)
    j = client.get("/api/weather").json()
    for k in ("available", "observed_at", "observed_local", "age_s", "stale", "kind",
              "temperature_c", "apparent_temperature_c", "precipitation_mm", "weather_code",
              "condition_ro", "icon", "wind_speed_kmh", "wind_direction_deg",
              "wind_direction_ro", "attribution"):
        assert k in j, k
    assert j["available"] is True and j["stale"] is False
    assert j["observed_at"].endswith("Z")
    assert 240 <= j["age_s"] <= 400
    assert len(j["observed_local"]) == 5 and j["observed_local"][2] == ":"
    assert j["condition_ro"] == "Ceață" and j["wind_direction_ro"] == "NE"
    assert j["precipitation_mm"] == 0.0


def test_weather_stale_and_null_precipitation(client):
    seed(client, 60, precipitation=None)
    j = client.get("/api/weather").json()
    assert j["stale"] is True and j["age_s"] > 2700
    assert j["precipitation_mm"] is None


def test_weather_read_only(client):
    assert client.post("/api/weather").status_code == 405


def test_health_has_weather_age_without_changing_ok(client):
    none = {"age_s": None, "ok": False, "stale": True}
    assert client.get("/api/health").json() == {
        "ok": False, "age_s": None, "weather_age_s": None, "version": __version__,
        "boards": {"arrivals": none, "departures": none}, "ocr": EMPTY_OCR}
    seed(client, 5)
    h = client.get("/api/health").json()
    assert h["ok"] is False and 240 <= h["weather_age_s"] <= 400   # weather never makes ok
    ingest(client, datetime.now(BUC) - timedelta(seconds=10))
    h = client.get("/api/health").json()
    assert h["ok"] is True
    seed(client, 600)  # very old weather (older slot) does not break ok either
    assert client.get("/api/health").json()["ok"] is True


def test_config_has_weather_block(client):
    c = client.get("/api/config").json()
    assert c["weather"] == {"enabled": False, "stale_after_s": 2700, "refresh_s": 300}
    with TestClient(create_app(settings(weather=wcfg()), start_poller=False)) as c2:
        assert c2.get("/api/config").json()["weather"]["enabled"] is True


# -- lifespan task ------------------------------------------------------------------

def _fake_poller(monkeypatch):
    async def fake_run_poller(settings, on_rows, client, stop, **kw):
        await stop.wait()
    monkeypatch.setattr("app.poller.run_poller", fake_run_poller)


def test_weather_task_not_started_when_disabled(monkeypatch):
    _fake_poller(monkeypatch)
    called = []

    async def fake(*a, **k):
        called.append(1)
    monkeypatch.setattr(wx, "run_weather", fake)
    with TestClient(create_app(settings(), start_poller=True)) as c:
        assert c.get("/api/weather").status_code == 200
    assert called == []


def test_weather_task_runs_stores_and_stops_on_shutdown(monkeypatch):
    _fake_poller(monkeypatch)
    started, stopped = threading.Event(), threading.Event()

    async def fake(cfg, client, on_obs, stop, **kw):
        from tests.test_weather import PAYLOAD
        now = datetime.now(UTC)
        p = dict(PAYLOAD, current=dict(PAYLOAD["current"],
                                       time=now.strftime("%Y-%m-%dT%H:%M")))
        await on_obs(wx.parse_observation(p, now))
        started.set()
        await stop.wait()
        stopped.set()

    monkeypatch.setattr(wx, "run_weather", fake)
    with TestClient(create_app(settings(weather=wcfg()), start_poller=True)) as c:
        assert started.wait(2)
        assert c.get("/api/weather").json()["available"] is True
    assert stopped.is_set()


def test_weather_initial_delay_respects_recent_fetch(monkeypatch, tmp_path):
    """A restart right after a fetch must not hit Open-Meteo again within 5 minutes."""
    _fake_poller(monkeypatch)
    db = str(tmp_path / "w.db")
    from app.store import Store
    s = Store(db)
    s.migrate()
    from tests.test_weather import payload
    now = datetime.now(UTC)
    s.add_weather(wx.parse_observation(payload(time="2026-10-21T03:15"),
                                       now - timedelta(seconds=60)))
    s.close()
    seen = {}
    got = threading.Event()

    async def fake(cfg, client, on_obs, stop, **kw):
        seen.update(kw)
        got.set()
        await stop.wait()
    monkeypatch.setattr(wx, "run_weather", fake)
    with TestClient(create_app(settings(db_path=db, weather=wcfg()), start_poller=True)):
        assert got.wait(2)
    assert 200 <= seen["initial_delay"] <= 241


def test_weather_crash_does_not_affect_board_or_health(monkeypatch, caplog):
    _fake_poller(monkeypatch)
    calls = []
    restarted = threading.Event()

    async def flaky(cfg, client, on_obs, stop, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("weather boom")
        restarted.set()
        await stop.wait()

    monkeypatch.setattr(wx, "run_weather", flaky)
    monkeypatch.setattr(wx, "RESTART_BACKOFF_S", 0.01)
    caplog.set_level(logging.ERROR)
    with TestClient(create_app(settings(weather=wcfg()), start_poller=True)) as c:
        ingest(c, datetime.now(BUC) - timedelta(seconds=5))
        assert restarted.wait(2)
        assert c.get("/api/board").status_code == 200
        assert c.get("/api/health").json()["ok"] is True
    assert len(calls) == 2
    assert any("weather" in r.getMessage().lower() for r in caplog.records)


def test_weather_task_that_ignores_stop_is_cancelled(monkeypatch):
    _fake_poller(monkeypatch)
    monkeypatch.setattr(wx, "STOP_TIMEOUT_S", 0.2)
    cancelled = threading.Event()

    async def stubborn(cfg, client, on_obs, stop, **kw):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise
    monkeypatch.setattr(wx, "run_weather", stubborn)
    with TestClient(create_app(settings(weather=wcfg()), start_poller=True)):
        pass
    assert cancelled.is_set()
