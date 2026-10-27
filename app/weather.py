# © 2026 Andy217Ace
"""Weather next to the clock: Open-Meteo `current` values + next-24 h temperatures for Bucharest.

The server (never the browser: CSP connect-src stays 'self') asks Open-Meteo for the
`current` block (temperature, feels-like, humidity, is_day, precipitation split rain/showers/
snow, weather code, surface pressure, wind speed/direction/gusts) and the `hourly`
temperature series (UTC, `forecast_days=2`) every WEATHER_INTERVAL_S seconds (default 900 = Open-Meteo's 15-minute
resolution, minimum 300). Errors back off exponentially (5, 10, 20, 30 min cap); there is
never more than one request per 5 minutes, also across restarts (the first request waits
until 5 minutes after the last stored fetch).

Honest labelling: `current` is the latest *model* value for the grid cell around the
coordinates, not a measuring station. Every stored row has kind="model_current" and the UI
says "Condiții curente (model Open-Meteo)". Missing values stay None (NULL) — never 0;
precipitation 0.0 is a real value. Times are stored in UTC ("YYYY-MM-DDTHH:MM:SSZ").
The hourly series is kept compactly (25 points from the observed hour, `hourly_json`) only on
the newest observation: it is a forecast the UI needs now, not history.

Data: Open-Meteo.com, CC BY 4.0 (attribution shown wherever the values are shown).

The loop runs as its own supervised asyncio task (see `start`), independent of the CFR
poller: a weather failure is logged and retried, it never touches the board or health.ok.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

UTC = timezone.utc
TZ = ZoneInfo("Europe/Bucharest")

DEFAULT_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_LAT = 44.4323
DEFAULT_LON = 26.1063
CURRENT_VARS = ("temperature_2m,relative_humidity_2m,apparent_temperature,is_day,"
                "precipitation,rain,showers,snowfall,weather_code,surface_pressure,"
                "wind_speed_10m,wind_direction_10m,wind_gusts_10m")
HOURLY_VARS = "temperature_2m"
FORECAST_DAYS = 2             # `hourly` then covers the next 24-48 h from any hour of today
HOURLY_POINTS = 25            # stored: the observed hour + the next 24 hours
SOURCE = "open-meteo"
KIND = "model_current"
LABEL_RO = "Condiții curente (model Open-Meteo)"
ATTRIBUTION = {"source": "Open-Meteo.com", "url": "https://open-meteo.com/",
               "license": "CC BY 4.0"}

DEFAULT_INTERVAL_S = 900
MIN_INTERVAL_S = 300          # never more than one request per 5 minutes
MAX_BACKOFF_S = 1800          # errors: 5, 10, 20, 30, 30 ... minutes
TIMEOUT_S = 10.0
MAX_BYTES = 64 * 1024         # `current` + 48 hourly values is ~2 KB
STALE_AFTER_S = 2700          # an observation older than 45 min is shown as "date vechi"
UI_REFRESH_S = 300            # web/weather.js polls /api/weather this often
RESTART_BACKOFF_S = 5.0       # supervisor: first delay before restarting a crashed loop
STOP_TIMEOUT_S = 10.0
USER_AGENT = ("tabela-gara-de-nord/1.0 (+https://github.com/Andy217Ace/tabela-gara-de-nord; "
              "(c) 2026 Andy217Ace; meteo Open-Meteo)")


class WeatherError(Exception):
    pass


@dataclass(frozen=True)
class WeatherConfig:
    url: str = DEFAULT_URL
    latitude: float = DEFAULT_LAT
    longitude: float = DEFAULT_LON
    interval_s: int = DEFAULT_INTERVAL_S


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        v = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return v if math.isfinite(v) and lo <= v <= hi else default


def config_from_env() -> WeatherConfig | None:
    """WEATHER_* env vars; None when WEATHER_ENABLED is 0/false/no/off (default: on)."""
    if os.environ.get("WEATHER_ENABLED", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    raw = os.environ.get("WEATHER_INTERVAL_S", "").strip()
    interval = int(raw) if raw.isascii() and raw.isdigit() else DEFAULT_INTERVAL_S
    return WeatherConfig(
        url=os.environ.get("WEATHER_URL", "").strip() or DEFAULT_URL,
        latitude=_env_float("WEATHER_LAT", DEFAULT_LAT, -90, 90),
        longitude=_env_float("WEATHER_LON", DEFAULT_LON, -180, 180),
        interval_s=max(MIN_INTERVAL_S, interval),
    )


def ui_config(enabled: bool) -> dict:
    """The `weather` block of GET /api/config."""
    return {"enabled": bool(enabled), "stale_after_s": STALE_AFTER_S, "refresh_s": UI_REFRESH_S}


# -- parsing ----------------------------------------------------------------------

def utc_iso(dt: datetime) -> str:
    """UTC ISO-8601 with a Z, seconds precision (naive input is taken as UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s: str) -> datetime:
    """Inverse of utc_iso (accepts any ISO form; naive = UTC)."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


# unit as reported in `current_units` -> factor/function to our unit; None = unknown unit
_TEMP = {"°C": lambda x: x, "°F": lambda x: (x - 32) * 5 / 9}
_SPEED = {"km/h": lambda x: x, "m/s": lambda x: x * 3.6, "mph": lambda x: x * 1.609344,
          "kn": lambda x: x * 1.852}
_PRECIP = {"mm": lambda x: x, "inch": lambda x: x * 25.4}
_DEG = {"°": lambda x: x}
_PCT = {"%": lambda x: x}
_HPA = {"hPa": lambda x: x}
_SNOW = {"cm": lambda x: x, "inch": lambda x: x * 2.54}
_DEFAULT_UNITS = {"temperature_2m": "°C", "apparent_temperature": "°C",
                  "wind_speed_10m": "km/h", "wind_gusts_10m": "km/h", "precipitation": "mm",
                  "rain": "mm", "showers": "mm", "snowfall": "cm", "wind_direction_10m": "°",
                  "relative_humidity_2m": "%", "surface_pressure": "hPa"}


def _value(current: dict, units: dict, key: str, table: dict) -> float | None:
    x = _num(current.get(key))
    if x is None:
        return None
    unit = units.get(key, _DEFAULT_UNITS[key])
    conv = table.get(unit)
    if conv is None:
        log.warning("weather: unknown unit %r for %s; value dropped", unit, key)
        return None
    y = conv(x)
    return y if conv is table.get(_DEFAULT_UNITS[key]) else round(y, 2)


def _observed_at(payload: dict, current: dict) -> str:
    t = current.get("time")
    if not isinstance(t, str):
        raise WeatherError("current.time missing")
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise WeatherError(f"current.time invalid: {t[:40]!r}") from None
    if dt.tzinfo is None:
        # Without a `timezone` parameter Open-Meteo answers in GMT (offset 0); honour
        # utc_offset_seconds in case the URL was configured with a timezone.
        off = payload.get("utc_offset_seconds")
        off = off if isinstance(off, int) and not isinstance(off, bool) else 0
        dt = dt.replace(tzinfo=UTC) - timedelta(seconds=off)
    return utc_iso(dt)


def _is_day(v) -> int | None:
    """Open-Meteo's is_day flag: 0 or 1 only (anything else is unknown, never a guess)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v) if v in (0, 1) else None


def _hourly_series(payload: dict, observed: str) -> str | None:
    """The next-24 h temperature series as compact JSON, or None when unusable:
    {"start": "<observed hour, UTC>", "step_s": 3600, "t": [<=25 values, None = missing]}.
    Aligned by time (a missing hour is a null, never a shifted value); trailing nulls are cut.
    A bad `hourly` block never fails the observation."""
    h = payload.get("hourly")
    if not isinstance(h, dict):
        return None
    times, temps = h.get("time"), h.get("temperature_2m")
    if not isinstance(times, list) or not isinstance(temps, list):
        return None
    units = payload.get("hourly_units")
    unit = units.get("temperature_2m", "°C") if isinstance(units, dict) else "°C"
    conv = _TEMP.get(unit)
    if conv is None:
        log.warning("weather: unknown hourly unit %r; series dropped", unit)
        return None
    off = payload.get("utc_offset_seconds")
    off = off if isinstance(off, int) and not isinstance(off, bool) else 0
    by_time: dict[datetime, float] = {}
    for ts, raw in zip(times, temps):
        x = _num(raw)
        if x is None or not isinstance(ts, str):
            continue
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC) - timedelta(seconds=off)
        by_time[dt.astimezone(UTC)] = x if conv is _TEMP["°C"] else round(conv(x), 2)
    start = parse_utc(observed).replace(minute=0, second=0, microsecond=0)
    series = [by_time.get(start + timedelta(hours=i)) for i in range(HOURLY_POINTS)]
    while series and series[-1] is None:
        series.pop()
    if not any(v is not None for v in series):
        return None
    return json.dumps({"start": utc_iso(start), "step_s": 3600, "t": series},
                      separators=(",", ":"))


def parse_observation(payload, fetched_at: datetime) -> dict:
    """Open-Meteo forecast JSON -> one row for `weather_observations`."""
    if not isinstance(payload, dict) or not isinstance(payload.get("current"), dict):
        raise WeatherError("no `current` block in the answer")
    current = payload["current"]
    observed = _observed_at(payload, current)
    units = payload.get("current_units")
    units_ok = isinstance(units, dict)
    units = units if units_ok else {}
    code = _num(current.get("weather_code"))
    humidity = _value(current, units, "relative_humidity_2m", _PCT)
    try:
        hourly_json = _hourly_series(payload, observed)
    except Exception:  # defensive: the hourly block is optional
        log.exception("weather: hourly series dropped")
        hourly_json = None
    raw = {k: v for k, v in payload.items() if k != "hourly"}
    return {
        "observed_at": observed,
        "fetched_at": utc_iso(fetched_at),
        "source": SOURCE,
        "kind": KIND,
        "latitude": _num(payload.get("latitude")),
        "longitude": _num(payload.get("longitude")),
        "temperature_c": _value(current, units, "temperature_2m", _TEMP),
        "apparent_temperature_c": _value(current, units, "apparent_temperature", _TEMP),
        "precipitation_mm": _value(current, units, "precipitation", _PRECIP),
        "weather_code": int(code) if code is not None and code.is_integer() else None,
        "wind_speed_kmh": _value(current, units, "wind_speed_10m", _SPEED),
        "wind_direction_deg": _value(current, units, "wind_direction_10m", _DEG),
        # schema v8
        "relative_humidity_pct": humidity if humidity is not None and 0 <= humidity <= 100 else None,
        "is_day": _is_day(current.get("is_day")),
        "rain_mm": _value(current, units, "rain", _PRECIP),
        "showers_mm": _value(current, units, "showers", _PRECIP),
        "snowfall_cm": _value(current, units, "snowfall", _SNOW),
        "surface_pressure_hpa": _value(current, units, "surface_pressure", _HPA),
        "wind_gusts_kmh": _value(current, units, "wind_gusts_10m", _SPEED),
        "hourly_json": hourly_json,
        "units_json": json.dumps(units, ensure_ascii=False) if units_ok else None,
        "raw_json": json.dumps(raw, ensure_ascii=False, separators=(",", ":")),
    }


# -- fetching -----------------------------------------------------------------------

def request_params(cfg: WeatherConfig) -> dict:
    return {"latitude": f"{cfg.latitude:.4f}", "longitude": f"{cfg.longitude:.4f}",
            "hourly": HOURLY_VARS, "current": CURRENT_VARS,
            "timezone": "UTC", "forecast_days": str(FORECAST_DAYS)}


async def fetch_observation(client: httpx.AsyncClient, cfg: WeatherConfig,
                            now: datetime | None = None) -> dict:
    try:
        async with client.stream("GET", cfg.url, params=request_params(cfg),
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                                 timeout=TIMEOUT_S) as resp:
            if resp.status_code != 200:
                raise WeatherError(f"HTTP {resp.status_code}")
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_BYTES:
                    raise WeatherError("response too large")
    except httpx.HTTPError as e:  # transport errors, timeouts, protocol errors
        raise WeatherError(f"transport error: {e!r}") from e
    try:
        data = json.loads(bytes(buf).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise WeatherError("invalid JSON") from None
    if isinstance(data, dict) and data.get("error"):
        raise WeatherError(f"API error: {str(data.get('reason'))[:200]}")
    return parse_observation(data, now or datetime.now(UTC))


# -- loop ---------------------------------------------------------------------------

def next_delay(failures: int, interval_s: float) -> float:
    """Seconds until the next request: the interval after a success, exponential backoff
    (from 5 min, capped at 30 min) after `failures` consecutive errors; never < 5 min."""
    if failures <= 0:
        return max(MIN_INTERVAL_S, interval_s)
    return min(MAX_BACKOFF_S, MIN_INTERVAL_S * 2 ** min(failures - 1, 10))


async def _wait_stop(stop: asyncio.Event, delay: float) -> bool:
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay)
    except asyncio.TimeoutError:
        pass
    return stop.is_set()


async def run_weather(cfg: WeatherConfig, client: httpx.AsyncClient, on_obs,
                      stop: asyncio.Event, *, initial_delay: float = 0.0, wait=None) -> None:
    """Fetch, hand the row to `await on_obs(row)`, sleep; until `stop` is set.

    `wait(delay) -> bool` (stopped?) is injectable for tests.
    """
    wait = wait or (lambda d: _wait_stop(stop, d))
    if initial_delay > 0 and await wait(initial_delay):
        return
    failures = 0
    while not stop.is_set():
        try:
            obs = await fetch_observation(client, cfg)
            await on_obs(obs)
            failures = 0
        except asyncio.CancelledError:
            raise
        except WeatherError as e:
            failures += 1
            log.warning("weather fetch failed (%d in a row): %s", failures, e)
        except Exception:
            failures += 1
            log.exception("weather update failed (%d in a row)", failures)
        if await wait(next_delay(failures, cfg.interval_s)):
            return


async def supervise_weather(cfg: WeatherConfig, client, on_obs, stop: asyncio.Event, *,
                            initial_delay: float = 0.0,
                            restart_backoff: float | None = None) -> None:
    """Run the loop; on a crash log it and restart with backoff (never raises)."""
    first = RESTART_BACKOFF_S if restart_backoff is None else restart_backoff
    delay = first
    while not stop.is_set():
        try:
            await run_weather(cfg, client, on_obs, stop, initial_delay=initial_delay)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("weather loop crashed; restarting in %.2fs", delay)
        else:
            if stop.is_set():
                break
            log.error("weather loop exited unexpectedly; restarting in %.2fs", delay)
        initial_delay = 0.0
        if await _wait_stop(stop, delay):
            break
        delay = min(max(delay * 2, first), MAX_BACKOFF_S)


class WeatherService:
    """The running background task (created by `start`, stopped in the app lifespan)."""

    def __init__(self, task: asyncio.Task, stop: asyncio.Event, client: httpx.AsyncClient):
        self.task, self._stop, self._client = task, stop, client

    async def stop(self) -> None:
        self._stop.set()
        try:
            await asyncio.wait_for(self.task, STOP_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.warning("weather task did not stop in %.0fs; cancelled", STOP_TIMEOUT_S)
        except Exception:
            log.exception("weather task failed during shutdown")
        finally:
            await self._client.aclose()


def start(store, cfg: WeatherConfig) -> WeatherService:
    """Start the supervised weather task (call from a running event loop)."""
    initial = 0.0
    try:
        latest = store.latest_weather()
        if latest and latest.get("fetched_at"):
            age = (datetime.now(UTC) - parse_utc(latest["fetched_at"])).total_seconds()
            initial = min(MIN_INTERVAL_S, max(0.0, MIN_INTERVAL_S - age))
    except Exception:
        log.exception("weather: could not read the last fetch time")

    async def on_obs(obs: dict) -> None:
        await asyncio.to_thread(store.add_weather, obs)

    client = httpx.AsyncClient()
    stop = asyncio.Event()
    task = asyncio.create_task(supervise_weather(cfg, client, on_obs, stop,
                                                 initial_delay=initial))
    return WeatherService(task, stop, client)


# -- presentation -------------------------------------------------------------------

# WMO weather interpretation codes (Open-Meteo docs), in Romanian.
WMO_RO = {
    0: "Senin",
    1: "Predominant senin",
    2: "Parțial noros",
    3: "Înnorat",
    45: "Ceață",
    48: "Ceață cu depunere de chiciură",
    51: "Burniță slabă",
    53: "Burniță moderată",
    55: "Burniță densă",
    56: "Burniță înghețată slabă",
    57: "Burniță înghețată densă",
    61: "Ploaie slabă",
    63: "Ploaie moderată",
    65: "Ploaie puternică",
    66: "Ploaie înghețată slabă",
    67: "Ploaie înghețată puternică",
    71: "Ninsoare slabă",
    73: "Ninsoare moderată",
    75: "Ninsoare puternică",
    77: "Grăunțe de zăpadă",
    80: "Averse slabe de ploaie",
    81: "Averse moderate de ploaie",
    82: "Averse violente de ploaie",
    85: "Averse slabe de ninsoare",
    86: "Averse puternice de ninsoare",
    95: "Furtună cu descărcări electrice",
    96: "Furtună cu grindină slabă",
    99: "Furtună cu grindină puternică",
}
UNKNOWN_RO = "Condiții necunoscute"

_ICONS = {0: "sun", 1: "sun", 2: "partly", 3: "cloud", 45: "fog", 48: "fog",
          51: "drizzle", 53: "drizzle", 55: "drizzle", 56: "freezing", 57: "freezing",
          61: "rain", 63: "rain", 65: "rain", 66: "freezing", 67: "freezing",
          71: "snow", 73: "snow", 75: "snow", 77: "snow", 80: "showers", 81: "showers",
          82: "showers", 85: "snow", 86: "snow", 95: "thunder", 96: "thunder", 99: "thunder"}
_NIGHT = {"sun": "moon", "partly": "partly-night"}

WIND_RO = ("N", "NE", "E", "SE", "S", "SV", "V", "NV")


def condition_ro(code) -> str:
    return WMO_RO.get(code, UNKNOWN_RO) if isinstance(code, int) else UNKNOWN_RO


def icon_for(code, is_day: bool | None) -> str:
    icon = _ICONS.get(code, "unknown") if isinstance(code, int) else "unknown"
    return _NIGHT.get(icon, icon) if is_day is False else icon


def wind_direction_ro(deg) -> str | None:
    """Direction the wind blows FROM, 8 sectors of 45°: [337.5, 22.5) = N, [22.5, 67.5) = NE…"""
    d = _num(deg)
    if d is None:
        return None
    return WIND_RO[int(((d % 360) + 22.5) // 45) % 8]


def is_daytime(lat: float, lon: float, when: datetime) -> bool:
    """Sun above the horizon (elevation > -0.833°), NOAA approximation; computed, not read."""
    t = when.astimezone(UTC)
    hour = t.hour + t.minute / 60 + t.second / 3600
    g = 2 * math.pi / 365 * (t.timetuple().tm_yday - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    ha = math.radians((hour * 60 + eqtime + 4 * lon) / 4 - 180)
    phi = math.radians(lat)
    cos_zen = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(ha)
    elevation = 90 - math.degrees(math.acos(max(-1.0, min(1.0, cos_zen))))
    return elevation > -0.833


def age_s(row: dict | None, now: datetime) -> float | None:
    """Seconds since the observation time of `row` (None without data)."""
    if not row or not row.get("observed_at"):
        return None
    return round(max(0.0, (now - parse_utc(row["observed_at"])).total_seconds()), 1)


def present_hourly(row: dict) -> dict | None:
    """The stored next-24 h series for the UI (None without a drawable series)."""
    raw = row.get("hourly_json")
    if not raw:
        return None
    try:
        h = json.loads(raw)
        start = utc_iso(parse_utc(h["start"]))
        step = h["step_s"]
        vals = [_num(v) for v in h["t"]]
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    real = [v for v in vals if v is not None]
    if step != 3600 or not real:
        return None
    return {"start_utc": start, "step_s": step, "temperature_c": vals,
            "min_c": min(real), "max_c": max(real)}


def present(row: dict | None, now: datetime) -> dict:
    """Body of GET /api/weather."""
    if not row:
        return {"available": False, "kind": KIND, "label_ro": LABEL_RO, "observed_at": None,
                "age_s": None, "stale": True, "attribution": ATTRIBUTION}
    observed = parse_utc(row["observed_at"])
    age = age_s(row, now)
    lat = row.get("latitude")
    lon = row.get("longitude")
    stored = _is_day(row.get("is_day"))   # the model's own flag; NULL (old rows): the sun
    is_day = bool(stored) if stored is not None else is_daytime(
        lat if lat is not None else DEFAULT_LAT, lon if lon is not None else DEFAULT_LON, observed)
    code = row.get("weather_code")
    return {
        "available": True,
        "observed_at": utc_iso(observed),
        "observed_local": observed.astimezone(TZ).strftime("%H:%M"),
        "fetched_at": row.get("fetched_at"),
        "age_s": age,
        "stale": age > STALE_AFTER_S,
        "kind": row.get("kind") or KIND,
        "label_ro": LABEL_RO,
        "temperature_c": row.get("temperature_c"),
        "apparent_temperature_c": row.get("apparent_temperature_c"),
        "precipitation_mm": row.get("precipitation_mm"),
        "weather_code": code,
        "condition_ro": condition_ro(code),
        "icon": icon_for(code, is_day),
        "is_day": is_day,
        "wind_speed_kmh": row.get("wind_speed_kmh"),
        "wind_direction_deg": row.get("wind_direction_deg"),
        "wind_direction_ro": wind_direction_ro(row.get("wind_direction_deg")),
        "wind_gusts_kmh": row.get("wind_gusts_kmh"),
        "relative_humidity_pct": row.get("relative_humidity_pct"),
        "surface_pressure_hpa": row.get("surface_pressure_hpa"),
        "rain_mm": row.get("rain_mm"),
        "showers_mm": row.get("showers_mm"),
        "snowfall_cm": row.get("snowfall_cm"),
        "hourly": present_hourly(row),
        "attribution": ATTRIBUTION,
    }
