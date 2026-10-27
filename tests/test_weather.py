# © 2026 Andy217Ace
"""app/weather.py: Open-Meteo `current` parsing, fetching, backoff, presentation."""
import asyncio
import json
import math
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import weather as wx

UTC = timezone.utc
NOW = datetime(2026, 10, 21, 3, 20, tzinfo=UTC)

# Shape of a real response (Open-Meteo, `timezone=UTC`, `forecast_days=2`, `hourly=
# temperature_2m` + the rich `current` list). Hourly values are synthetic: 48 h from 00:00 UTC.
HOURLY_TIMES = [f"2026-10-{21 + h // 24:02d}T{h % 24:02d}:00" for h in range(48)]
HOURLY_TEMPS = [round(8 + 5 * math.sin((h - 9) / 24 * 2 * math.pi), 1) for h in range(48)]
PAYLOAD = {
    "latitude": 44.424946, "longitude": 26.066908, "generationtime_ms": 0.108,
    "utc_offset_seconds": 0, "timezone": "UTC", "timezone_abbreviation": "UTC",
    "elevation": 85.0,
    "current_units": {"time": "iso8601", "interval": "seconds", "temperature_2m": "°C",
                      "relative_humidity_2m": "%", "apparent_temperature": "°C",
                      "is_day": "", "precipitation": "mm", "rain": "mm", "showers": "mm",
                      "snowfall": "cm", "weather_code": "wmo code",
                      "surface_pressure": "hPa", "wind_speed_10m": "km/h",
                      "wind_direction_10m": "°", "wind_gusts_10m": "km/h"},
    "current": {"time": "2026-10-21T03:15", "interval": 900, "temperature_2m": 10.8,
                "relative_humidity_2m": 93, "apparent_temperature": 10.2, "is_day": 0,
                "precipitation": 0.00, "rain": 0.0, "showers": 0.0, "snowfall": 0.0,
                "weather_code": 45, "surface_pressure": 1008.4, "wind_speed_10m": 5.4,
                "wind_direction_10m": 48, "wind_gusts_10m": 11.2},
    "hourly_units": {"time": "iso8601", "temperature_2m": "°C"},
    "hourly": {"time": HOURLY_TIMES, "temperature_2m": HOURLY_TEMPS},
}
# the stored raw_json keeps everything except `hourly` (kept compactly in hourly_json)
RAW_PAYLOAD = {k: v for k, v in PAYLOAD.items() if k != "hourly"}


def cfg(**kw):
    base = dict(url=wx.DEFAULT_URL, latitude=44.4323, longitude=26.1063, interval_s=900)
    base.update(kw)
    return wx.WeatherConfig(**base)


def payload(**current):
    p = json.loads(json.dumps(PAYLOAD))
    p["current"].update(current)
    return p


# -- parsing ------------------------------------------------------------------

def test_parse_full_payload():
    o = wx.parse_observation(PAYLOAD, NOW)
    assert o["observed_at"] == "2026-10-21T03:15:00Z"
    assert o["fetched_at"] == "2026-10-21T03:20:00Z"
    assert o["source"] == "open-meteo" and o["kind"] == "model_current"
    assert o["temperature_c"] == 10.8 and o["apparent_temperature_c"] == 10.2
    assert o["precipitation_mm"] == 0.0 and o["precipitation_mm"] is not None
    assert o["weather_code"] == 45 and isinstance(o["weather_code"], int)
    assert o["wind_speed_kmh"] == 5.4 and o["wind_direction_deg"] == 48
    assert (o["latitude"], o["longitude"]) == (44.424946, 26.066908)
    assert json.loads(o["units_json"])["wind_speed_10m"] == "km/h"
    assert json.loads(o["raw_json"]) == RAW_PAYLOAD
    # the rich `current` fields (schema v8)
    assert o["relative_humidity_pct"] == 93 and o["is_day"] == 0
    assert o["rain_mm"] == 0.0 and o["showers_mm"] == 0.0 and o["snowfall_cm"] == 0.0
    assert o["rain_mm"] is not None and o["snowfall_cm"] is not None   # real zeros
    assert o["surface_pressure_hpa"] == 1008.4 and o["wind_gusts_kmh"] == 11.2


NEW_KEYS = ("relative_humidity_pct", "is_day", "rain_mm", "showers_mm", "snowfall_cm",
            "surface_pressure_hpa", "wind_gusts_kmh")
NEW_SRC = ("relative_humidity_2m", "is_day", "rain", "showers", "snowfall",
           "surface_pressure", "wind_gusts_10m")


def test_parse_missing_new_fields_are_none_not_zero():
    p = payload()
    for k in NEW_SRC:
        del p["current"][k]
    o = wx.parse_observation(p, NOW)
    for k in NEW_KEYS:
        assert o[k] is None, k
    assert o["temperature_c"] == 10.8   # the old fields are unaffected


@pytest.mark.parametrize("src", NEW_SRC)
def test_parse_null_new_field_is_none(src):
    o = wx.parse_observation(payload(**{src: None}), NOW)
    assert o[NEW_KEYS[NEW_SRC.index(src)]] is None


def test_parse_real_zero_precip_split_is_kept_as_zero():
    o = wx.parse_observation(payload(precipitation=0.0, rain=0.0, showers=0.0, snowfall=0.0), NOW)
    assert (o["precipitation_mm"], o["rain_mm"], o["showers_mm"], o["snowfall_cm"]) == (0.0,) * 4
    assert all(v is not None for v in (o["rain_mm"], o["showers_mm"], o["snowfall_cm"]))


def test_parse_precip_split_values():
    o = wx.parse_observation(payload(precipitation=1.5, rain=1.0, showers=0.5, snowfall=0.7), NOW)
    assert (o["precipitation_mm"], o["rain_mm"], o["showers_mm"], o["snowfall_cm"]) == \
        (1.5, 1.0, 0.5, 0.7)


@pytest.mark.parametrize("val,want", [(0, 0), (1, 1), (True, None), (2, None), (-1, None),
                                      (0.5, None), ("1", None), (None, None)])
def test_parse_is_day_only_0_or_1(val, want):
    assert wx.parse_observation(payload(is_day=val), NOW)["is_day"] == want


def test_parse_humidity_out_of_range_is_none():
    assert wx.parse_observation(payload(relative_humidity_2m=140), NOW)["relative_humidity_pct"] is None
    assert wx.parse_observation(payload(relative_humidity_2m=-3), NOW)["relative_humidity_pct"] is None
    assert wx.parse_observation(payload(relative_humidity_2m=0), NOW)["relative_humidity_pct"] == 0


def test_parse_new_units_converted_or_dropped():
    p = payload(snowfall=1.0, wind_gusts_10m=10.0, rain=1.0, showers=2.0)
    p["current_units"].update({"snowfall": "inch", "wind_gusts_10m": "m/s", "rain": "inch",
                               "showers": "furlong"})
    o = wx.parse_observation(p, NOW)
    assert o["snowfall_cm"] == pytest.approx(2.54)
    assert o["wind_gusts_kmh"] == pytest.approx(36.0)
    assert o["rain_mm"] == pytest.approx(25.4)
    assert o["showers_mm"] is None                    # unknown unit: never guess


# -- hourly series ----------------------------------------------------------------------

def test_hourly_is_25_points_from_the_observed_hour():
    o = wx.parse_observation(PAYLOAD, NOW)               # observed 03:15 -> hour 03:00
    h = json.loads(o["hourly_json"])
    assert h["start"] == "2026-10-21T03:00:00Z" and h["step_s"] == 3600
    assert h["t"] == HOURLY_TEMPS[3:28] and len(h["t"]) == 25
    assert len(o["hourly_json"]) < 400                   # compact: only what the UI needs


def test_hourly_shorter_series_is_kept_as_is():
    p = payload()
    p["hourly"] = {"time": HOURLY_TIMES[:10], "temperature_2m": HOURLY_TEMPS[:10]}
    h = json.loads(wx.parse_observation(p, NOW)["hourly_json"])
    assert h["t"] == HOURLY_TEMPS[3:10]


@pytest.mark.parametrize("hourly", [None, {}, [], "x", {"time": []}, {"time": ["x"]},
                                    {"time": HOURLY_TIMES, "temperature_2m": "abc"},
                                    {"time": HOURLY_TIMES, "temperature_2m": []},
                                    {"time": HOURLY_TIMES[:2], "temperature_2m": [1, 2]}])
def test_hourly_unusable_is_none_and_never_fails_the_observation(hourly):
    p = payload()
    p["hourly"] = hourly
    o = wx.parse_observation(p, NOW)
    assert o["hourly_json"] is None and o["temperature_c"] == 10.8


def test_hourly_absent_block_is_none():
    p = payload()
    del p["hourly"]
    assert wx.parse_observation(p, NOW)["hourly_json"] is None


def test_hourly_null_and_bad_entries_stay_null_not_zero():
    p = payload()
    temps = list(HOURLY_TEMPS)
    temps[5] = None
    temps[6] = "abc"
    temps[7] = float("nan")
    p["hourly"] = {"time": HOURLY_TIMES, "temperature_2m": temps}
    t = json.loads(wx.parse_observation(p, NOW)["hourly_json"])["t"]
    assert t[2:5] == [None, None, None] and t[0] == HOURLY_TEMPS[3] and t[5] == HOURLY_TEMPS[8]


def test_hourly_gap_in_times_is_aligned_by_time():
    p = payload()
    times, temps = HOURLY_TIMES[:], HOURLY_TEMPS[:]
    del times[5], temps[5]                           # the 05:00 hour is missing
    p["hourly"] = {"time": times, "temperature_2m": temps}
    t = json.loads(wx.parse_observation(p, NOW)["hourly_json"])["t"]
    assert t[2] is None and t[1] == HOURLY_TEMPS[4] and t[3] == HOURLY_TEMPS[6]


def test_hourly_follows_utc_offset_seconds():
    p = payload(time="2026-10-21T06:15")
    p["utc_offset_seconds"] = 10800                  # configured with timezone=Europe/Bucharest
    h = json.loads(wx.parse_observation(p, NOW)["hourly_json"])   # hourly times are local clock
    assert h["start"] == "2026-10-21T03:00:00Z" and h["t"][0] == HOURLY_TEMPS[6]


def test_hourly_fahrenheit_is_converted_unknown_unit_dropped():
    p = payload()
    p["hourly"] = {"time": HOURLY_TIMES, "temperature_2m": [50.0] * 48}
    p["hourly_units"]["temperature_2m"] = "°F"
    assert json.loads(wx.parse_observation(p, NOW)["hourly_json"])["t"][0] == 10.0
    p["hourly_units"]["temperature_2m"] = "K"
    assert wx.parse_observation(p, NOW)["hourly_json"] is None


def test_hourly_not_in_raw_json():
    assert "hourly" not in json.loads(wx.parse_observation(PAYLOAD, NOW)["raw_json"])


def test_parse_null_precipitation_stays_null_not_zero():
    o = wx.parse_observation(payload(precipitation=None), NOW)
    assert o["precipitation_mm"] is None
    assert o["temperature_c"] == 10.8


def test_parse_missing_fields_are_none():
    p = payload()
    for k in ("temperature_2m", "apparent_temperature", "weather_code", "wind_speed_10m",
              "wind_direction_10m", "precipitation") + NEW_SRC:
        del p["current"][k]
    del p["current_units"]
    del p["hourly"]
    o = wx.parse_observation(p, NOW)
    for k in ("temperature_c", "apparent_temperature_c", "precipitation_mm", "weather_code",
              "wind_speed_kmh", "wind_direction_deg", "hourly_json") + NEW_KEYS:
        assert o[k] is None, k
    assert o["units_json"] is None


@pytest.mark.parametrize("bad", ["abc", True, float("nan"), float("inf"), [], {}])
def test_parse_non_numeric_values_are_none(bad):
    o = wx.parse_observation(payload(temperature_2m=bad, weather_code=bad), NOW)
    assert o["temperature_c"] is None and o["weather_code"] is None


def test_parse_non_integer_weather_code_is_none():
    assert wx.parse_observation(payload(weather_code=3.5), NOW)["weather_code"] is None
    assert wx.parse_observation(payload(weather_code=3.0), NOW)["weather_code"] == 3


@pytest.mark.parametrize("p", [None, [], {}, {"current": None}, {"current": {}},
                               {"current": {"time": "yesterday"}},
                               {"current": {"time": 12}}])
def test_parse_rejects_payload_without_valid_time(p):
    with pytest.raises(wx.WeatherError):
        wx.parse_observation(p, NOW)


def test_time_without_offset_is_utc():
    o = wx.parse_observation(payload(time="2026-07-01T12:00"), NOW)
    assert o["observed_at"] == "2026-07-01T12:00:00Z"   # not shifted by Bucharest's +3


def test_time_with_utc_offset_seconds_is_converted_to_utc():
    p = payload(time="2026-10-21T06:15")
    p["utc_offset_seconds"] = 10800  # would happen with timezone=Europe/Bucharest
    assert wx.parse_observation(p, NOW)["observed_at"] == "2026-10-21T03:15:00Z"


def test_explicit_offset_in_time_is_honoured():
    o = wx.parse_observation(payload(time="2026-10-21T06:15+03:00"), NOW)
    assert o["observed_at"] == "2026-10-21T03:15:00Z"


def test_units_are_converted_or_dropped():
    p = payload(wind_speed_10m=10.0, temperature_2m=50.0, precipitation=1.0)
    p["current_units"].update({"wind_speed_10m": "m/s", "temperature_2m": "°F",
                               "precipitation": "inch"})
    o = wx.parse_observation(p, NOW)
    assert o["wind_speed_kmh"] == pytest.approx(36.0)
    assert o["temperature_c"] == pytest.approx(10.0)
    assert o["precipitation_mm"] == pytest.approx(25.4)
    p["current_units"]["wind_speed_10m"] = "furlongs/fortnight"
    assert wx.parse_observation(p, NOW)["wind_speed_kmh"] is None  # never guess


def test_utc_iso():
    assert wx.utc_iso(datetime(2026, 1, 2, 3, 4, 5, 999, tzinfo=UTC)) == "2026-01-02T03:04:05Z"
    buc = datetime(2026, 10, 21, 6, 15, tzinfo=wx.TZ)
    assert wx.utc_iso(buc) == "2026-10-21T03:15:00Z"
    assert wx.utc_iso(datetime(2026, 10, 21, 3, 15)) == "2026-10-21T03:15:00Z"  # naive = UTC


# -- config ---------------------------------------------------------------------

def test_config_from_env_defaults(monkeypatch):
    for k in ("WEATHER_ENABLED", "WEATHER_LAT", "WEATHER_LON", "WEATHER_URL",
              "WEATHER_INTERVAL_S"):
        monkeypatch.delenv(k, raising=False)
    c = wx.config_from_env()
    assert c == wx.WeatherConfig(url="https://api.open-meteo.com/v1/forecast",
                                 latitude=44.4323, longitude=26.1063, interval_s=900)


@pytest.mark.parametrize("val", ["0", "false", "off", "no"])
def test_config_from_env_disabled(monkeypatch, val):
    monkeypatch.setenv("WEATHER_ENABLED", val)
    assert wx.config_from_env() is None


def test_config_interval_has_minimum_and_bad_values_fall_back(monkeypatch):
    monkeypatch.setenv("WEATHER_ENABLED", "1")
    monkeypatch.setenv("WEATHER_INTERVAL_S", "60")
    assert wx.config_from_env().interval_s == 300
    monkeypatch.setenv("WEATHER_INTERVAL_S", "abc")
    assert wx.config_from_env().interval_s == 900
    monkeypatch.setenv("WEATHER_LAT", "999")
    monkeypatch.setenv("WEATHER_LON", "x")
    c = wx.config_from_env()
    assert (c.latitude, c.longitude) == (44.4323, 26.1063)


def test_settings_carry_weather_config(monkeypatch):
    from app.config import Settings, get_settings
    monkeypatch.delenv("WEATHER_ENABLED", raising=False)
    assert get_settings().weather is not None            # on by default in production
    monkeypatch.setenv("WEATHER_ENABLED", "0")
    assert get_settings().weather is None
    s = Settings(db_path=":memory:", source_url="x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="", tesseract_cmd="t")
    assert s.weather is None                              # tests never hit the network


# -- fetching -------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_fetch_sends_exact_parameters_and_user_agent():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = req.url
        seen["ua"] = req.headers.get("user-agent")
        return httpx.Response(200, json=PAYLOAD)

    async def go():
        async with mock_client(handler) as c:
            return await wx.fetch_observation(c, cfg(), now=NOW)
    o = run(go())
    assert o["temperature_c"] == 10.8
    q = dict(seen["url"].params)
    # the request the user specified (rich `current` list + `hourly`), UTC, two forecast days
    assert q == {"latitude": "44.4323", "longitude": "26.1063",
                 "hourly": "temperature_2m",
                 "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,"
                            "precipitation,rain,showers,snowfall,weather_code,surface_pressure,"
                            "wind_speed_10m,wind_direction_10m,wind_gusts_10m",
                 "timezone": "UTC", "forecast_days": "2"}
    assert str(seen["url"]).startswith("https://api.open-meteo.com/v1/forecast?")
    assert seen["ua"].isascii() and "tabela-gara-de-nord" in seen["ua"]
    assert o["hourly_json"] is not None and o["relative_humidity_pct"] == 93


@pytest.mark.parametrize("resp", [
    httpx.Response(500, text="oops"),
    httpx.Response(429, json={"error": True, "reason": "limit"}),
    httpx.Response(200, text="not json {"),
    httpx.Response(200, json={"error": True, "reason": "bad"}),
    httpx.Response(200, content=b"x" * (wx.MAX_BYTES + 1)),
])
def test_fetch_errors_raise_weather_error(resp):
    async def go():
        async with mock_client(lambda req: resp) as c:
            await wx.fetch_observation(c, cfg(), now=NOW)
    with pytest.raises(wx.WeatherError):
        run(go())


def test_fetch_timeout_raises_weather_error():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    async def go():
        async with mock_client(handler) as c:
            await wx.fetch_observation(c, cfg(), now=NOW)
    with pytest.raises(wx.WeatherError):
        run(go())


def test_fetch_uses_10s_timeout():
    assert wx.TIMEOUT_S == 10.0


# -- loop + backoff -------------------------------------------------------------

def test_next_delay_backoff_is_exponential_capped_and_never_below_5_min():
    assert wx.next_delay(0, 900) == 900
    assert wx.next_delay(0, 10) == 300            # never more than 1 request / 5 min
    assert [wx.next_delay(n, 900) for n in (1, 2, 3, 4, 5, 9)] == \
        [300, 600, 1200, 1800, 1800, 1800]


def _loop(handler, n_waits, interval=900, on_obs=None, initial_delay=0.0):
    """Run run_weather until it has asked to wait n_waits times; return (delays, obs)."""
    delays, got = [], []

    async def go():
        stop = asyncio.Event()

        async def wait(d):
            delays.append(d)
            if len(delays) >= n_waits:
                stop.set()
            return stop.is_set()

        async def default_on_obs(o):
            got.append(o)
        async with mock_client(handler) as c:
            await wx.run_weather(cfg(interval_s=interval), c, on_obs or default_on_obs, stop,
                                 wait=wait, initial_delay=initial_delay)
    run(go())
    return delays, got


def test_run_weather_success_waits_interval():
    delays, got = _loop(lambda r: httpx.Response(200, json=PAYLOAD), 3)
    assert delays == [900, 900, 900] and len(got) == 3


def test_run_weather_errors_back_off_then_recover():
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) <= 3:
            raise httpx.ConnectTimeout("down", request=req)
        return httpx.Response(200, json=PAYLOAD)
    delays, got = _loop(handler, 5)
    assert delays == [300, 600, 1200, 900, 900]
    assert len(got) == 2


def test_run_weather_on_obs_failure_counts_as_failure():
    async def broken(o):
        raise RuntimeError("db locked")
    delays, _ = _loop(lambda r: httpx.Response(200, json=PAYLOAD), 2, on_obs=broken)
    assert delays == [300, 600]


def test_run_weather_initial_delay_waits_first():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, json=PAYLOAD)
    delays, _ = _loop(handler, 1, initial_delay=120)
    assert delays == [120] and calls == []   # stopped during the initial wait


def test_run_weather_stops_promptly_on_stop_event():
    async def go():
        stop = asyncio.Event()
        async with mock_client(lambda r: httpx.Response(200, json=PAYLOAD)) as c:
            t = asyncio.create_task(wx.run_weather(cfg(), c, _noop, stop))
            await asyncio.sleep(0.05)
            stop.set()
            await asyncio.wait_for(t, 1)
    run(go())


async def _noop(o):
    return None


def test_supervisor_restarts_crashed_loop(monkeypatch):
    calls = []

    async def flaky(c, client, on_obs, stop, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("bug")
        stop.set()

    monkeypatch.setattr(wx, "run_weather", flaky)

    async def go():
        stop = asyncio.Event()
        await asyncio.wait_for(wx.supervise_weather(cfg(), None, _noop, stop,
                                                    restart_backoff=0.01), 2)
    run(go())
    assert len(calls) == 2


# -- presentation -----------------------------------------------------------------

WMO_CODES = [0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77,
             80, 81, 82, 85, 86, 95, 96, 99]


def test_wmo_table_is_complete_and_romanian():
    assert sorted(wx.WMO_RO) == WMO_CODES
    for code in WMO_CODES:
        label = wx.condition_ro(code)
        assert label and label != "Condiții necunoscute"
    assert wx.condition_ro(0) == "Senin"
    assert wx.condition_ro(3) == "Înnorat"
    assert wx.condition_ro(45) == "Ceață"
    assert wx.condition_ro(95).startswith("Furtună")


@pytest.mark.parametrize("code", [None, 4, 50, 100, -1])
def test_unknown_wmo_code(code):
    assert wx.condition_ro(code) == "Condiții necunoscute"
    assert wx.icon_for(code, True) == "unknown"


def test_icons_by_code():
    want = {0: "sun", 1: "sun", 2: "partly", 3: "cloud", 45: "fog", 48: "fog",
            51: "drizzle", 55: "drizzle", 56: "freezing", 57: "freezing", 61: "rain",
            65: "rain", 66: "freezing", 67: "freezing", 71: "snow", 77: "snow",
            80: "showers", 82: "showers", 85: "snow", 86: "snow", 95: "thunder", 99: "thunder"}
    for code, icon in want.items():
        assert wx.icon_for(code, True) == icon, code
    assert wx.icon_for(0, False) == "moon" and wx.icon_for(2, False) == "partly-night"
    assert wx.icon_for(61, False) == "rain"


@pytest.mark.parametrize("deg,want", [
    (0, "N"), (360, "N"), (359.9, "N"), (22.4, "N"), (22.5, "NE"), (45, "NE"),
    (67.4, "NE"), (67.5, "E"), (90, "E"), (135, "SE"), (180, "S"), (225, "SV"),
    (270, "V"), (315, "NV"), (337.4, "NV"), (337.5, "N"), (720, "N"), (-90, "V"),
    (None, None), (float("nan"), None)])
def test_wind_direction_ro(deg, want):
    assert wx.wind_direction_ro(deg) == want


def test_is_daytime_bucharest():
    assert wx.is_daytime(44.43, 26.1, datetime(2026, 6, 21, 10, 0, tzinfo=UTC)) is True
    assert wx.is_daytime(44.43, 26.1, datetime(2026, 6, 21, 0, 0, tzinfo=UTC)) is False
    assert wx.is_daytime(44.43, 26.1, datetime(2026, 12, 21, 16, 0, tzinfo=UTC)) is False
    assert wx.is_daytime(44.43, 26.1, datetime(2026, 12, 21, 10, 0, tzinfo=UTC)) is True


def row(**kw):
    o = wx.parse_observation(PAYLOAD, NOW)
    o.update(kw)
    return o


def test_present_shape():
    p = wx.present(row(), NOW)
    assert p["available"] is True
    assert p["observed_at"] == "2026-10-21T03:15:00Z"
    assert p["observed_local"] == "06:15"          # Europe/Bucharest (UTC+3 in October)
    assert p["age_s"] == 300 and p["stale"] is False
    assert p["kind"] == "model_current"
    assert p["label_ro"] == "Condiții curente (model Open-Meteo)"
    assert p["temperature_c"] == 10.8 and p["apparent_temperature_c"] == 10.2
    assert p["precipitation_mm"] == 0.0
    assert p["weather_code"] == 45 and p["condition_ro"] == "Ceață" and p["icon"] == "fog"
    assert p["wind_speed_kmh"] == 5.4 and p["wind_direction_deg"] == 48
    assert p["wind_direction_ro"] == "NE"
    assert p["attribution"] == {"source": "Open-Meteo.com", "url": "https://open-meteo.com/",
                                "license": "CC BY 4.0"}
    assert "raw_json" not in p and "units_json" not in p


def test_present_has_rich_fields_and_hourly():
    p = wx.present(row(), NOW)
    assert p["relative_humidity_pct"] == 93 and p["surface_pressure_hpa"] == 1008.4
    assert p["wind_gusts_kmh"] == 11.2
    assert (p["rain_mm"], p["showers_mm"], p["snowfall_cm"]) == (0.0, 0.0, 0.0)
    h = p["hourly"]
    assert h["start_utc"] == "2026-10-21T03:00:00Z" and h["step_s"] == 3600
    assert h["temperature_c"] == HOURLY_TEMPS[3:28]
    assert h["min_c"] == min(HOURLY_TEMPS[3:28]) and h["max_c"] == max(HOURLY_TEMPS[3:28])
    assert "hourly_json" not in p and "raw_json" not in p


def test_present_old_row_without_new_columns_gives_nulls():
    old = {k: v for k, v in row().items() if k not in NEW_KEYS and k != "hourly_json"}
    p = wx.present(old, NOW)
    assert p["available"] is True and p["temperature_c"] == 10.8
    for k in ("relative_humidity_pct", "surface_pressure_hpa", "wind_gusts_kmh", "rain_mm",
              "showers_mm", "snowfall_cm", "hourly"):
        assert p[k] is None, k
    assert isinstance(p["is_day"], bool)              # computed from the sun, as before


def test_present_uses_stored_is_day_and_falls_back_to_the_sun():
    noon = dict(observed_at="2026-06-21T10:00:00Z", weather_code=0)
    assert wx.present(row(is_day=0, **noon), datetime(2026, 6, 21, 10, 5, tzinfo=UTC)) \
        ["icon"] == "moon"                              # the model says night: believe it
    midnight = dict(observed_at="2026-06-21T00:00:00Z", weather_code=0)
    p = wx.present(row(is_day=1, **midnight), datetime(2026, 6, 21, 0, 5, tzinfo=UTC))
    assert p["is_day"] is True and p["icon"] == "sun"
    p = wx.present(row(is_day=None, **midnight), datetime(2026, 6, 21, 0, 5, tzinfo=UTC))
    assert p["is_day"] is False and p["icon"] == "moon"  # NULL: computed


def test_present_hourly_edge_cases():
    assert wx.present(row(hourly_json=None), NOW)["hourly"] is None
    assert wx.present(row(hourly_json="{not json"), NOW)["hourly"] is None
    assert wx.present(row(hourly_json='{"start":"x","step_s":3600,"t":[1]}'), NOW)["hourly"] is None
    h = wx.present(row(hourly_json=json.dumps(
        {"start": "2026-10-21T03:00:00Z", "step_s": 3600, "t": [None, 4.0, None, -2.5]})),
        NOW)["hourly"]
    assert h["temperature_c"] == [None, 4.0, None, -2.5]
    assert h["min_c"] == -2.5 and h["max_c"] == 4.0
    # nothing to draw -> no chart at all (never a flat line at 0)
    assert wx.present(row(hourly_json=json.dumps(
        {"start": "2026-10-21T03:00:00Z", "step_s": 3600, "t": [None, None]})), NOW)["hourly"] is None


def test_present_null_precipitation_is_null():
    assert wx.present(row(precipitation_mm=None), NOW)["precipitation_mm"] is None


def test_present_stale_after_45_min():
    obs = datetime(2026, 10, 21, 3, 15, tzinfo=UTC)
    assert wx.present(row(), obs + timedelta(minutes=45))["stale"] is False
    p = wx.present(row(), obs + timedelta(minutes=45, seconds=1))
    assert p["stale"] is True and p["age_s"] == 2701
    assert wx.STALE_AFTER_S == 2700


def test_present_none_is_unavailable():
    p = wx.present(None, NOW)
    assert p["available"] is False and p["stale"] is True
    assert p["observed_at"] is None and p["age_s"] is None
    assert p["attribution"]["license"] == "CC BY 4.0"


def test_present_night_icon():
    night = row(observed_at="2026-10-21T21:00:00Z", weather_code=0)
    p = wx.present(night, datetime(2026, 10, 21, 21, 5, tzinfo=UTC))
    assert p["icon"] == "moon" and p["is_day"] is False


def test_no_nan_leaks_into_json():
    p = wx.present(row(), NOW)
    for v in p.values():
        if isinstance(v, float):
            assert math.isfinite(v)
