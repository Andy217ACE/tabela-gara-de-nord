# © 2026 Andy217Ace
from __future__ import annotations

import asyncio
import logging
import math
import os
import statistics
import time
from collections import deque
from typing import Awaitable, Callable, Iterable

import httpx

from app.fetcher import FetchError, fetch_board_image, image_hash
from app.models import Row
from app.ocr.reader import OcrError, read_board, read_board_debug
from app.rejected import save_rejected

log = logging.getLogger(__name__)

MIN_GAP = 2.0          # hard limit: never < 2 s between requests
MAX_PER_MIN = 10       # hard limit: at most 10 requests in any 60 s window
WINDOW_BEFORE = 1.0
WINDOW_AFTER = 20.0
IN_WINDOW_DELAY = 2.5
NO_PHASE_DELAY = 10.0
STALE_AFTER = 300.0
STALE_DELAY = 30.0
HISTORY = 5
KNOWN_STATIONS_WARN_S = 600  # log a known_stations() failure at most every 10 min


class PhaseTracker:
    """Tracks the second-within-the-minute at which the source image changes.

    The phase is the circular median of the last observations (circular so
    that values around :59/:00 do not average to :30).
    """

    def __init__(self) -> None:
        self._obs: deque[float] = deque(maxlen=HISTORY)

    def observe_change(self, ts: float) -> None:
        self._obs.append(ts % 60.0)

    @property
    def phase(self) -> float | None:
        if not self._obs:
            return None
        angles = [v / 60.0 * 2 * math.pi for v in self._obs]
        ref = math.atan2(sum(math.sin(a) for a in angles), sum(math.cos(a) for a in angles))
        ref = (ref / (2 * math.pi) * 60.0) % 60.0
        deltas = [((v - ref + 30.0) % 60.0) - 30.0 for v in self._obs]
        return (ref + statistics.median(deltas)) % 60.0

    def next_poll_delay(self, now: float, last_change: float | None) -> float:
        phase = self.phase
        if phase is None:
            return NO_PHASE_DELAY
        if last_change is not None and now - last_change > STALE_AFTER:
            return STALE_DELAY
        minute0 = now - (now % 60.0)
        # Window instances: [minute0 + 60k + phase - 1, ... + 21]. k=-1 covers
        # windows wrapping past :00; k=1 covers phase < 1 s, where the window
        # starts at :59.x of the current minute's end.
        for k in (-1, 0, 1):
            start = minute0 + 60.0 * k + phase - WINDOW_BEFORE
            if start <= now <= start + WINDOW_BEFORE + WINDOW_AFTER:
                if last_change is not None and last_change >= start:
                    return start + 60.0 - now  # change already seen in this window
                return IN_WINDOW_DELAY
        for k in (0, 1):
            start = minute0 + 60.0 * k + phase - WINDOW_BEFORE
            if start > now:
                return start - now
        return NO_PHASE_DELAY  # defensive; cannot happen (k=1 start > now)


class Backoff:
    def __init__(self) -> None:
        self._n = 0

    def fail(self) -> float:
        delay = min(5.0 * (2 ** self._n), 300.0)
        self._n += 1
        return delay

    def ok(self) -> None:
        self._n = 0


def _rate_wait(requests: deque[float], now: float) -> float:
    wait = 0.0
    if requests:
        wait = max(wait, requests[-1] + MIN_GAP - now)
    if len(requests) >= MAX_PER_MIN:
        wait = max(wait, requests[-MAX_PER_MIN] + 60.0 - now)
    return wait


def _save_image(path: str | None, data: bytes) -> None:
    if not path:
        return
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        log.warning("could not save last image", exc_info=True)


async def run_poller(
    settings,
    on_rows: Callable[[list[Row], float], Awaitable[None]],
    client: httpx.AsyncClient,
    stop: asyncio.Event,
    *,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    last_image_path: str | None = "data/last.jpg",
    known_stations: Callable[[], Iterable[str]] | None = None,
    on_capture: Callable[..., Awaitable[None]] | None = None,
    rejected_dir: str | None = None,
) -> None:
    """Poll the board image and hand new readings to `on_rows`.

    `known_stations` (e.g. ``Store.known_stations``) supplies the station names
    learned from the history for OCR canonicalisation. `on_capture(image, rows,
    debug, ts, duration_ms, error)` (optional) records every new image after
    `on_rows`, also when OCR failed; its failures are logged and ignored.
    `on_rows` may return {panel: reason} for the panels it rejected; such frames
    (and frames OCR failed on) are saved to `rejected_dir` (None: not saved).
    """
    reader = read_board if on_capture is None else read_board_debug

    async def capture(data: bytes, rows, debug, ts: float, dur_ms: int, error) -> None:
        if on_capture is None:
            return
        try:
            await on_capture(data, rows, debug, ts, dur_ms, error)
        except Exception:
            log.exception("on_capture callback failed")
    tracker = PhaseTracker()
    backoff = Backoff()
    requests: deque[float] = deque(maxlen=MAX_PER_MIN)
    last_hash: str | None = None
    ks_warned: float | None = None  # monotonic time of the last known_stations warning
    last_change: float | None = None

    async def pause(delay: float) -> None:
        if delay <= 0:
            return
        if sleep is asyncio.sleep:  # wake up promptly on shutdown
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
        else:
            await sleep(delay)

    while not stop.is_set():
        # Hard limits, regardless of what the tracker asks for.
        await pause(_rate_wait(requests, clock()))
        if stop.is_set():
            break
        requests.append(clock())
        try:
            data = await fetch_board_image(client, settings.source_url)
        except FetchError as e:
            delay = backoff.fail()
            log.warning("fetch failed (%s); retry in %.0fs", e, delay)
            await pause(delay)
            continue
        except Exception:
            log.exception("unexpected fetch error")
            await pause(backoff.fail())
            continue
        backoff.ok()
        ts = clock()
        h = image_hash(data)
        if h != last_hash:
            first = last_hash is None
            last_hash = h  # remembered even if OCR fails: no retry every 2 s
            await asyncio.to_thread(_save_image, last_image_path, data)
            if not first:
                tracker.observe_change(ts)
                last_change = ts
            t0, debug = time.perf_counter(), None
            try:
                if known_stations is None:
                    rows = await asyncio.to_thread(reader, data)
                else:
                    try:
                        stations = await asyncio.to_thread(known_stations)
                    except Exception:  # canonicalisation then uses the seed only
                        now_m = time.monotonic()
                        if ks_warned is None or now_m - ks_warned >= KNOWN_STATIONS_WARN_S:
                            ks_warned = now_m
                            log.warning("known stations unavailable (repeats silenced for"
                                        " %d min)", KNOWN_STATIONS_WARN_S // 60, exc_info=True)
                        stations = ()
                    rows = await asyncio.to_thread(reader, data, stations=stations)
                if on_capture is not None:
                    rows, debug = rows
            except (OcrError, ValueError) as e:
                log.exception("OCR failed for new image")
                if rejected_dir:
                    await asyncio.to_thread(save_rejected, rejected_dir, data, ts,
                                            {"frame": f"OCR failed: {type(e).__name__}"})
                await capture(data, None, None, ts, int((time.perf_counter() - t0) * 1000),
                              f"{type(e).__name__}: {e}")
            else:
                dur_ms = int((time.perf_counter() - t0) * 1000)
                rejected = None
                try:
                    rejected = await on_rows(rows, ts)
                except Exception:
                    log.exception("on_rows callback failed")
                if rejected and rejected_dir:
                    await asyncio.to_thread(save_rejected, rejected_dir, data, ts,
                                            dict(rejected))
                await capture(data, rows, debug, ts, dur_ms, None)
        await pause(tracker.next_poll_delay(clock(), last_change))
