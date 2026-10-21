# © 2026 Andy217Ace
"""Schema v4: weather_observations table + Store weather methods."""
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import weather as wx
from app.store import SCHEMA_VERSION, Store
from tests.test_store import T0, base_rows

UTC = timezone.utc
NOW = datetime(2026, 10, 21, 3, 20, tzinfo=UTC)
COLS = {"id", "observed_at", "fetched_at", "source", "kind", "latitude", "longitude",
        "temperature_c", "apparent_temperature_c", "precipitation_mm", "weather_code",
        "wind_speed_kmh", "wind_direction_deg", "units_json", "raw_json"}


def obs(t="2026-10-21T03:15", **current):
    from tests.test_weather import payload
    return wx.parse_observation(payload(time=t, **current), NOW)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def version(s):
    return s._conn.execute("PRAGMA user_version").fetchone()[0]


def wcols(s):
    return {r[1] for r in s._conn.execute("PRAGMA table_info(weather_observations)")}


def test_schema_version_is_4():
    assert SCHEMA_VERSION == 4


def test_fresh_db_has_weather_table(store):
    assert version(store) == 4
    assert wcols(store) == COLS
    store.migrate()  # idempotent
    assert version(store) == 4


def test_observed_at_unique_and_defaults(store):
    store._conn.execute("INSERT INTO weather_observations(observed_at, fetched_at)"
                        " VALUES ('2026-10-21T03:15:00Z', '2026-10-21T03:20:00Z')")
    r = store._conn.execute("SELECT source, kind, temperature_c, precipitation_mm"
                            " FROM weather_observations").fetchone()
    assert tuple(r) == ("open-meteo", "model_current", None, None)
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("INSERT INTO weather_observations(observed_at, fetched_at)"
                            " VALUES ('2026-10-21T03:15:00Z', 'x')")


def _make_v3(path):
    """A database as the deployed v3 code leaves it (no weather table)."""
    s = Store(str(path))
    s.migrate()
    s.ingest(base_rows(), T0)
    s._conn.execute("DROP TABLE weather_observations")
    s._conn.execute("PRAGMA user_version = 3")
    return s


def test_migrate_v3_with_data_to_v4_keeps_all_rows(tmp_path):
    s = _make_v3(tmp_path / "v3.db")
    before = {t: s._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("runs", "services", "events")}
    assert before["services"] == 4
    s.migrate()
    s.migrate()  # idempotent
    assert version(s) == 4 and wcols(s) == COLS
    after = {t: s._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ("runs", "services", "events")}
    assert after == before
    assert s.latest_weather() is None
    s.close()


@pytest.mark.parametrize("old", [1, 2])
def test_migrate_v1_v2_to_v4(tmp_path, old):
    from tests.test_store import _downgrade
    s = _make_v3(tmp_path / "old.db")
    _downgrade(s, old)
    assert version(s) == old
    s.migrate()
    assert version(s) == 4 and wcols(s) == COLS
    assert {"last_read", "operator_raw", "station_raw", "uncertain"} <= \
        {r[1] for r in s._conn.execute("PRAGMA table_info(services)")}
    assert s._conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 4
    s.close()


def test_migrate_live_v2_fixture_to_v4(tmp_path):
    db = tmp_path / "live.db"
    shutil.copy(Path(__file__).parent / "fixtures" / "live_v2.db", db)
    s = Store(str(db))
    s.migrate()
    assert version(s) == 4 and wcols(s) == COLS
    assert s._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 5
    s.close()


def test_v4_step_is_atomic(tmp_path, monkeypatch):
    """If the v4 step fails, the database stays at v3 and nothing half-applied remains."""
    import app.store as st
    s = _make_v3(tmp_path / "v3.db")
    monkeypatch.setattr(st, "_WEATHER_SCHEMA", st._WEATHER_SCHEMA + "THIS IS NOT SQL;")
    with pytest.raises(sqlite3.Error):
        s.migrate()
    assert version(s) == 3
    assert not wcols(s)
    monkeypatch.undo()
    s.migrate()
    assert version(s) == 4
    s.close()


def test_migrate_to_4_is_a_separate_step():
    """The integrator chains v5 after v4: the step must exist on its own."""
    assert callable(getattr(Store, "_migrate_to_4", None))


# -- store methods --------------------------------------------------------------

def test_add_weather_is_idempotent_on_observed_at(store):
    assert store.add_weather(obs()) is True
    again = obs(temperature_2m=99.0)
    assert store.add_weather(again) is False           # same observation, fetched twice
    n = store._conn.execute("SELECT COUNT(*) FROM weather_observations").fetchone()[0]
    assert n == 1
    assert store.latest_weather()["temperature_c"] == 10.8  # first one kept


def test_latest_weather_is_newest_observation(store):
    store.add_weather(obs("2026-10-21T03:15"))
    store.add_weather(obs("2026-10-21T03:45"))
    store.add_weather(obs("2026-10-21T03:30"))           # late arrival, older slot
    latest = store.latest_weather()
    assert latest["observed_at"] == "2026-10-21T03:45:00Z"
    assert latest["fetched_at"] == "2026-10-21T03:20:00Z"
    assert latest["kind"] == "model_current"


def test_null_vs_zero_precipitation_end_to_end(store):
    store.add_weather(obs("2026-10-21T03:00", precipitation=0.0))
    store.add_weather(obs("2026-10-21T03:15", precipitation=None))
    rows = store.weather_between("2026-10-21T00:00:00Z", "2026-10-21T23:59:59Z")
    assert [r["precipitation_mm"] for r in rows] == [0.0, None]
    raw = store._conn.execute("SELECT precipitation_mm FROM weather_observations"
                              " ORDER BY observed_at").fetchall()
    assert [r[0] for r in raw] == [0.0, None]
    assert wx.present(store.latest_weather(), NOW)["precipitation_mm"] is None


def test_weather_between_inclusive_and_accepts_datetimes(store):
    for t in ("2026-10-21T03:00", "2026-10-21T03:15", "2026-10-21T03:30", "2026-10-21T03:45"):
        store.add_weather(obs(t))
    got = store.weather_between(datetime(2026, 10, 21, 3, 15, tzinfo=UTC),
                                datetime(2026, 10, 21, 6, 30, tzinfo=wx.TZ))  # = 03:30Z
    assert [r["observed_at"] for r in got] == ["2026-10-21T03:15:00Z", "2026-10-21T03:30:00Z"]
    assert "raw_json" in got[0]


def test_history_is_kept(store):
    t = datetime(2026, 10, 1, tzinfo=UTC)
    for i in range(200):
        o = obs()
        o["observed_at"] = wx.utc_iso(t + timedelta(minutes=15 * i))
        store.add_weather(o)
    assert store._conn.execute("SELECT COUNT(*) FROM weather_observations").fetchone()[0] == 200


def test_add_weather_requires_observed_at(store):
    o = obs()
    o["observed_at"] = None
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        store.add_weather(o)
