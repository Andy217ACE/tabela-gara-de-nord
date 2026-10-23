# © 2026 Andy217Ace
import asyncio
import os

import pytest

from app import poller
from app.fetcher import FetchError
from app.ocr.reader import OcrError
from app.poller import Backoff, PhaseTracker


def test_phase_median():
    t = PhaseTracker()
    assert t.phase is None
    for ts in (60 * 5 + 13.2, 60 * 6 + 12.9, 60 * 7 + 13.4):
        t.observe_change(ts)
    assert t.phase == pytest.approx(13.2)


def test_phase_uses_last_five():
    t = PhaseTracker()
    for ts in (50, 50, 50, 20, 20, 20, 20, 20):
        t.observe_change(ts)
    assert t.phase == pytest.approx(20)


def test_phase_wraps_around_minute():
    t = PhaseTracker()
    for ts in (59.0, 60 + 0.5, 120 + 1.0, 180 + 59.5, 240 + 0.2):
        t.observe_change(ts)
    p = t.phase
    assert p is not None
    assert min(p, 60 - p) <= 1.0  # near the :00 boundary, not ~30


def test_delay_no_phase():
    assert PhaseTracker().next_poll_delay(100, None) == 10


def _t():
    t = PhaseTracker()
    t.observe_change(13.0)
    return t


def test_delay_outside_window_waits_for_next_minute():
    assert _t().next_poll_delay(40, None) == pytest.approx(32)


def test_delay_before_window_same_minute():
    assert _t().next_poll_delay(5, None) == pytest.approx(7)


def test_delay_inside_window_before_change():
    assert _t().next_poll_delay(12.5, None) <= 2.5
    assert _t().next_poll_delay(20, 13.2 - 60) == pytest.approx(2.5)


def test_delay_change_already_seen_this_minute():
    assert _t().next_poll_delay(14, 13.2) == pytest.approx(72 - 14)


def test_delay_stale_source():
    assert _t().next_poll_delay(1000, 100) == 30


def test_delay_window_wrapping_past_minute():
    t = PhaseTracker()
    t.observe_change(59.5)  # window 58.5 .. 79.5
    assert t.next_poll_delay(65, None) == pytest.approx(2.5)  # :05 still in window
    assert t.next_poll_delay(65, 59.7) == pytest.approx(118.5 - 65)
    assert t.next_poll_delay(30, None) == pytest.approx(28.5)


def test_delay_phase_below_one_second():
    t = PhaseTracker()
    t.observe_change(0.3)  # window starts at :59.3 of the previous minute
    assert t.phase == pytest.approx(0.3)
    assert t.next_poll_delay(59.5, None) == pytest.approx(2.5)
    assert t.next_poll_delay(30, None) == pytest.approx(59.3 - 30)
    # change already seen inside this window (started at 59.3) -> next window
    assert t.next_poll_delay(60.5, 60.3) == pytest.approx(119.3 - 60.5)
    assert t.next_poll_delay(59.5, 59.4) == pytest.approx(119.3 - 59.5)


def test_backoff():
    b = Backoff()
    assert [b.fail() for _ in range(8)] == [5, 10, 20, 40, 80, 160, 300, 300]
    b.ok()
    assert b.fail() == 5


# ---- run_poller -----------------------------------------------------------

class World:
    def __init__(self, change_phase=13.0, start=1000.0):
        self.now = start
        self.change_phase = change_phase
        self.requests: list[float] = []
        self.stop = asyncio.Event()
        self.rows_calls: list[float] = []
        self.end = start + 400
        self.fail_at: set[int] = set()
        self.ocr_fail_hashes: set[bytes] = set()
        self.read_calls: list[bytes] = []

    def clock(self):
        return self.now

    async def sleep(self, d):
        assert d >= 0
        self.now += d
        if self.now >= self.end:
            self.stop.set()

    def image(self):
        minute = int((self.now - self.change_phase) // 60)
        return f"img-{minute}".encode()


@pytest.fixture
def world(monkeypatch, tmp_path):
    w = World()

    async def fake_fetch(client, url):
        w.requests.append(w.now)
        if len(w.requests) in w.fail_at:
            raise FetchError("boom")
        return w.image()

    def fake_read(data):
        w.read_calls.append(data)
        if data in w.ocr_fail_hashes:
            raise OcrError("bad")
        return ["row"]

    monkeypatch.setattr(poller, "fetch_board_image", fake_fetch)
    monkeypatch.setattr(poller, "read_board", fake_read)
    w.path = str(tmp_path / "data" / "last.jpg")
    return w


class S:
    source_url = "http://x"


async def _run(w, on_rows):
    await asyncio.wait_for(
        poller.run_poller(S(), on_rows, None, w.stop, clock=w.clock, sleep=w.sleep,
                          last_image_path=w.path),
        timeout=5,
    )


async def test_run_rate_limits_and_on_rows_only_on_change(world):
    w = world
    calls = []

    async def on_rows(rows, ts):
        calls.append(ts)

    await _run(w, on_rows)
    gaps = [b - a for a, b in zip(w.requests, w.requests[1:])]
    assert min(gaps) >= 2.0
    for i, t in enumerate(w.requests):
        assert len([x for x in w.requests[: i + 1] if x > t - 60]) <= 10
    distinct = {int((t - 13.0) // 60) for t in w.requests}
    assert len(calls) == len(distinct)
    # phase-locked: far fewer requests than 1 per 2.5 s
    assert len(w.requests) < 400 / 2.5 / 2
    assert os.path.exists(w.path)


async def test_run_fetch_error_backoff(world):
    w = world
    w.fail_at = {1, 2}

    async def on_rows(rows, ts):
        pass

    await _run(w, on_rows)
    assert w.requests[1] - w.requests[0] >= 5
    assert w.requests[2] - w.requests[1] >= 10


async def test_run_survives_ocr_and_callback_errors(world):
    w = world
    w.ocr_fail_hashes = {b"img-16"}
    seen = []

    async def on_rows(rows, ts):
        seen.append(ts)
        if len(seen) == 2:
            raise RuntimeError("cb")

    await _run(w, on_rows)
    assert len(w.requests) > 3
    assert w.stop.is_set()
    assert w.read_calls.count(b"img-16") == 1  # failed-OCR hash not retried


async def test_run_passes_learned_stations_to_reader(world, monkeypatch):
    w = world
    got = []

    def fake_read(data, *, stations=()):
        got.append(set(stations))
        return ["row"]

    monkeypatch.setattr(poller, "read_board", fake_read)

    async def on_rows(rows, ts):
        pass

    await asyncio.wait_for(
        poller.run_poller(S(), on_rows, None, w.stop, clock=w.clock, sleep=w.sleep,
                          last_image_path=w.path, known_stations=lambda: {"BRASOV"}),
        timeout=5,
    )
    assert got and all(s == {"BRASOV"} for s in got)


async def test_run_survives_known_stations_failure(world, monkeypatch, caplog):
    w = world
    got = []

    def fake_read(data, *, stations=()):
        got.append(tuple(stations))
        return ["row"]

    def broken():
        raise RuntimeError("db locked")

    monkeypatch.setattr(poller, "read_board", fake_read)

    async def on_rows(rows, ts):
        pass

    await asyncio.wait_for(
        poller.run_poller(S(), on_rows, None, w.stop, clock=w.clock, sleep=w.sleep,
                          last_image_path=w.path, known_stations=broken),
        timeout=5,
    )
    assert got and all(s == () for s in got)
    # the failure is logged at most once per KNOWN_STATIONS_WARN_S, not per image
    warns = [r for r in caplog.records if "known stations unavailable" in r.getMessage()]
    assert len(got) > 1 and len(warns) == 1
