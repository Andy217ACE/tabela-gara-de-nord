# © 2026 Andy217Ace
"""Poller -> on_capture hook: every new image recorded; failures never stop polling."""
import asyncio

import pytest

from app import captures, poller
from app.ocr.reader import OcrError
from app.store import Store


class S:
    source_url = "http://x"


class W:
    def __init__(self):
        self.now = 1000.0
        self.stop = asyncio.Event()

    def clock(self):
        return self.now

    async def sleep(self, d):
        self.now += d
        if self.now >= 1300:
            self.stop.set()


@pytest.fixture
def w(monkeypatch):
    w = W()

    async def fetch(client, url):
        return f"img-{int((w.now - 13) // 60)}".encode()

    def read_debug(data, *, stations=(), votes=None):
        if data == b"img-17":
            raise OcrError("bad")
        return ["row"], [{"dbg": 1}]

    monkeypatch.setattr(poller, "fetch_board_image", fetch)
    monkeypatch.setattr(poller, "read_board_debug", read_debug)
    monkeypatch.setattr(poller, "read_board", None)  # must not be used with on_capture
    return w


async def _run(w, on_rows, on_capture, tmp_path):
    await asyncio.wait_for(poller.run_poller(
        S(), on_rows, None, w.stop, clock=w.clock, sleep=w.sleep,
        last_image_path=str(tmp_path / "last.jpg"), on_capture=on_capture), timeout=5)


async def test_on_capture_after_on_rows_and_on_ocr_failure(w, tmp_path):
    order, caps = [], []

    async def on_rows(rows, ts):
        order.append(("rows", ts))

    async def on_capture(image, rows, debug, ts, dur, error):
        order.append(("cap", ts))
        caps.append((image, rows, debug, error, dur))

    await _run(w, on_rows, on_capture, tmp_path)
    assert caps, "no capture recorded"
    ok = [c for c in caps if c[3] is None]
    assert ok and all(c[1] == ["row"] and c[2] == [{"dbg": 1}] for c in ok)
    assert all(isinstance(c[4], int) and c[4] >= 0 for c in caps)
    failed = [c for c in caps if c[3] is not None]
    assert [c[0] for c in failed] == [b"img-17"] and "OcrError" in failed[0][3]
    assert failed[0][1] is None and failed[0][2] is None
    # for ok images the capture comes right after the ingest of the same reading
    for i, (kind, ts) in enumerate(order):
        if kind == "cap" and i and order[i - 1][0] == "rows":
            assert order[i - 1][1] == ts


async def test_capture_failure_never_breaks_polling(w, tmp_path):
    seen = []

    async def on_rows(rows, ts):
        seen.append(ts)

    async def on_capture(*a):
        raise RuntimeError("disk full")

    await _run(w, on_rows, on_capture, tmp_path)
    assert len(seen) >= 3 and w.stop.is_set()


async def test_record_failure_inside_hook_is_swallowed(tmp_path, monkeypatch, caplog):
    store = Store(":memory:")
    store.migrate()
    hook = captures.make_on_capture(store, captures.CaptureSettings(True, str(tmp_path), 7))
    from app import observations

    def boom(*a, **k):
        raise RuntimeError("db locked")

    monkeypatch.setattr(observations, "record_capture", boom)
    await hook(b"img", [], None, 1000.0, 5, None)  # no exception
    assert any("capture recording failed" in r.getMessage() for r in caplog.records)
    store.close()


async def test_disabled_hook_records_nothing(tmp_path):
    store = Store(":memory:")
    store.migrate()
    hook = captures.make_on_capture(store, captures.CaptureSettings(False, str(tmp_path), 7))
    await hook(b"img", [], None, 1000.0, 5, None)
    assert store._conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 0
    store.close()
