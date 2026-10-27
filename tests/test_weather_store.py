# © 2026 Andy217Ace
"""Schema v4: weather_observations table + Store weather methods."""
import json
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
        "wind_speed_kmh", "wind_direction_deg", "units_json", "raw_json",
        # schema v8 (additive)
        "relative_humidity_pct", "is_day", "rain_mm", "showers_mm", "snowfall_cm",
        "surface_pressure_hpa", "wind_gusts_kmh", "hourly_json"}
V4_COLS = COLS - {"relative_humidity_pct", "is_day", "rain_mm", "showers_mm", "snowfall_cm",
                  "surface_pressure_hpa", "wind_gusts_kmh", "hourly_json"}


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


def test_schema_version_is_at_least_4():
    assert SCHEMA_VERSION >= 8   # v8 = rich weather columns


def test_fresh_db_has_weather_table(store):
    assert version(store) == SCHEMA_VERSION
    assert wcols(store) == COLS
    store.migrate()  # idempotent
    assert version(store) == SCHEMA_VERSION


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
    for t in ("observations", "captures", "trains"):  # v5 tables (stage B) do not exist at v3
        s._conn.execute(f"DROP TABLE IF EXISTS {t}")
    s._conn.execute("PRAGMA user_version = 3")
    return s


def test_migrate_v3_with_data_to_v4_keeps_all_rows(tmp_path):
    s = _make_v3(tmp_path / "v3.db")
    before = {t: s._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("runs", "services", "events")}
    assert before["services"] == 4
    s.migrate()
    s.migrate()  # idempotent
    assert version(s) == SCHEMA_VERSION and wcols(s) == COLS
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
    assert version(s) == SCHEMA_VERSION and wcols(s) == COLS
    assert {"last_read", "operator_raw", "station_raw", "uncertain"} <= \
        {r[1] for r in s._conn.execute("PRAGMA table_info(services)")}
    assert s._conn.execute("SELECT COUNT(*) FROM services").fetchone()[0] == 4
    s.close()


def test_migrate_live_v2_fixture_to_v4(tmp_path):
    db = tmp_path / "live.db"
    shutil.copy(Path(__file__).parent / "fixtures" / "live_v2.db", db)
    s = Store(str(db))
    s.migrate()
    assert version(s) == SCHEMA_VERSION and wcols(s) == COLS
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
    assert version(s) == SCHEMA_VERSION
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


# -- schema v8: rich weather columns (additive ALTER TABLE) -----------------------------------

def _make_v7(path):
    """A database as the deployed Beta 1.24 code leaves it: v7, with the OLD v4 weather table
    (no rich columns) holding real rows."""
    s = Store(str(path))
    s.migrate()
    s.ingest(base_rows(), T0)
    c = s._conn
    c.execute("DROP TABLE weather_observations")
    from app.store import _WEATHER_SCHEMA
    c.executescript(_WEATHER_SCHEMA)
    c.execute("INSERT INTO weather_observations(observed_at, fetched_at, temperature_c,"
              " apparent_temperature_c, precipitation_mm, weather_code, wind_speed_kmh,"
              " wind_direction_deg, raw_json) VALUES"
              " ('2026-10-20T03:15:00Z','2026-10-20T03:20:00Z', 9.5, 8.1, 0.0, 3, 12.0, 200, '{}'),"
              " ('2026-10-20T03:30:00Z','2026-10-20T03:35:00Z', 9.7, NULL, NULL, NULL, NULL, NULL, NULL)")
    c.execute("PRAGMA user_version = 7")
    return s


def test_migrate_v7_to_v8_adds_columns_keeps_rows_and_nulls(tmp_path):
    s = _make_v7(tmp_path / "v7.db")
    assert wcols(s) == V4_COLS
    s.migrate()
    s.migrate()  # idempotent
    assert version(s) == SCHEMA_VERSION == 8 and wcols(s) == COLS
    rows = s.weather_between("2026-10-20T00:00:00Z", "2026-10-20T23:59:59Z")
    assert [r["temperature_c"] for r in rows] == [9.5, 9.7]
    assert rows[0]["precipitation_mm"] == 0.0 and rows[1]["precipitation_mm"] is None
    assert rows[0]["wind_speed_kmh"] == 12.0 and rows[0]["weather_code"] == 3
    new = ("relative_humidity_pct", "is_day", "rain_mm", "showers_mm", "snowfall_cm",
           "surface_pressure_hpa", "wind_gusts_kmh", "hourly_json")
    for r in rows:
        assert all(r[k] is None for k in new)       # old rows: NULL, never 0
    p = wx.present(rows[0] | {"latitude": None}, datetime(2026, 10, 20, 3, 20, tzinfo=UTC))
    assert p["available"] is True and p["relative_humidity_pct"] is None and p["hourly"] is None
    s.close()


def test_v8_step_is_atomic(tmp_path, monkeypatch):
    import app.store as st
    s = _make_v7(tmp_path / "v7.db")
    monkeypatch.setattr(st, "_WEATHER_V8_COLUMNS",
                        st._WEATHER_V8_COLUMNS + (("broken", "NOT A TYPE ((("),))
    with pytest.raises(sqlite3.Error):
        s.migrate()
    assert version(s) == 7
    assert wcols(s) == V4_COLS                        # nothing half-applied
    monkeypatch.undo()
    s.migrate()
    assert version(s) == SCHEMA_VERSION and wcols(s) == COLS
    s.close()


def test_migrate_to_8_is_a_separate_step():
    assert callable(getattr(Store, "_migrate_to_8", None))


def test_stats_overview_works_across_v7_rows_and_v8_rows(tmp_path):
    """stats_overview selects only the four classic weather columns: rows written before the
    v8 migration and rows written after it feed the same per-panel weather groups."""
    from datetime import date
    from app import stats, stats_overview as so
    from tests.test_stats_overview import add
    s = _make_v7(tmp_path / "mix.db")
    s._conn.execute("DELETE FROM weather_observations")
    for day in range(10, 15):                                  # old schema, v7 rows
        s._conn.execute(
            "INSERT INTO weather_observations(observed_at, fetched_at, temperature_c,"
            " precipitation_mm, wind_speed_kmh) VALUES (?,?,?,?,5.0)",
            (f"2026-10-{day}T09:00:00Z", f"2026-10-{day}T09:05:00Z", 8.0, 0.0))
    s.migrate()                                                # -> v8
    for day in range(15, 20):                                  # new schema, v8 rows
        wet = day % 2 == 1
        s.add_weather(obs(f"2026-10-{day}T09:00", precipitation=1.2 if wet else 0.0,
                          rain=1.2 if wet else 0.0, temperature_2m=18.0))
    for day in range(10, 20):
        add(s._conn, "arrival", 100 + day, day, "12:00", 20 if day % 2 else 1)
    so.clear_cache()
    w = so.overview(s, stats.Params(on_time=5, min_sample=5), {}, today=date(2026, 10, 20))["weather"]
    s.close()
    assert w["status"] == "ok" and w["matched"] == 10 and w["observations"] == 10
    assert w["boards"]["arrival"]["status"] == "ok"


# -- hourly series lives only on the newest observation --------------------------------------

def test_add_weather_stores_new_fields_and_hourly(store):
    store.add_weather(obs("2026-10-21T03:15", relative_humidity_2m=0, snowfall=0.0, rain=0.0))
    r = store.latest_weather()
    assert r["relative_humidity_pct"] == 0 and r["snowfall_cm"] == 0.0 and r["rain_mm"] == 0.0
    assert r["surface_pressure_hpa"] == 1008.4 and r["wind_gusts_kmh"] == 11.2 and r["is_day"] == 0
    assert json.loads(r["hourly_json"])["step_s"] == 3600


def test_null_new_fields_are_stored_as_null_not_zero(store):
    store.add_weather(obs("2026-10-21T03:15", relative_humidity_2m=None, rain=None,
                          surface_pressure=None, wind_gusts_10m=None, is_day=None))
    r = store.latest_weather()
    for k in ("relative_humidity_pct", "rain_mm", "surface_pressure_hpa", "wind_gusts_kmh",
              "is_day"):
        assert r[k] is None, k


def test_hourly_kept_only_on_the_newest_observation(store):
    store.add_weather(obs("2026-10-21T03:15"))
    store.add_weather(obs("2026-10-21T03:30"))
    store.add_weather(obs("2026-10-21T03:45"))
    got = {r["observed_at"]: r["hourly_json"]
           for r in store.weather_between("2026-10-21T00:00:00Z", "2026-10-21T23:59:59Z")}
    assert got["2026-10-21T03:15:00Z"] is None and got["2026-10-21T03:30:00Z"] is None
    assert got["2026-10-21T03:45:00Z"] is not None
    # temperatures / the other values of the old rows are untouched
    assert store.weather_between("2026-10-21T03:15:00Z",
                                 "2026-10-21T03:15:00Z")[0]["temperature_c"] == 10.8


def test_late_older_observation_does_not_take_over_hourly(store):
    store.add_weather(obs("2026-10-21T03:45"))
    store.add_weather(obs("2026-10-21T03:30"))           # arrives late
    rows = {r["observed_at"]: r["hourly_json"]
            for r in store.weather_between("2026-10-21T00:00:00Z", "2026-10-21T23:59:59Z")}
    assert rows["2026-10-21T03:45:00Z"] is not None and rows["2026-10-21T03:30:00Z"] is None


def test_duplicate_observation_keeps_hourly_of_the_first(store):
    store.add_weather(obs("2026-10-21T03:15"))
    assert store.add_weather(obs("2026-10-21T03:15")) is False
    assert store.latest_weather()["hourly_json"] is not None


def test_observation_without_hourly_does_not_erase_the_previous_series(store):
    """A newest answer without a usable hourly block never wipes the series stored before."""
    store.add_weather(obs("2026-10-21T03:15"))
    o = obs("2026-10-21T03:30")
    o["hourly_json"] = None
    store.add_weather(o)
    rows = {r["observed_at"]: r["hourly_json"]
            for r in store.weather_between("2026-10-21T00:00:00Z", "2026-10-21T23:59:59Z")}
    assert rows["2026-10-21T03:15:00Z"] is not None and rows["2026-10-21T03:30:00Z"] is None
