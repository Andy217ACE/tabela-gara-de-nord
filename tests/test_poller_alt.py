# © 2026 Andy217Ace
"""Integrarea alternativei OCR in poller: oprita = ieșire identică; OCR_ALT=1 recuperează o linie
necitită cu marcajul +ocr:alt; OCR_ALT_SHADOW=1 nu schimbă rândurile. Fără Tesseract."""
import asyncio

import pytest

from app import observations, poller
from app.ocr import alt_reader as alt
from app.ocr import stats as ocr_stats
from tests.test_ocr_alt_reader import FakePanel, MODEL, make_cell, read_entries


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
        if self.now >= 1100:
            self.stop.set()


def _entries():
    es = read_entries()
    es[2] = {**es[2]}  # linia 2: necitită
    return es


@pytest.fixture
def run(monkeypatch, tmp_path):
    for k in ("OCR_ALT", "OCR_ALT_SHADOW", "OCR_ALT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    ocr_stats.reset()
    monkeypatch.setattr(alt, "get_model", lambda: MODEL)
    monkeypatch.setattr(alt, "_panels", lambda image: {"arrival": FakePanel(
        {2: {"no": make_cell("7942"), "time": make_cell("10:20")}})})

    async def fetch(client, url):
        return b"img"

    def read_debug(data, *, stations=(), votes=None):
        es = _entries()
        return [e["row"] for e in es if e["row"] is not None], es

    monkeypatch.setattr(poller, "fetch_board_image", fetch)
    monkeypatch.setattr(poller, "read_board_debug", read_debug)

    async def go():
        w, got, caps = W(), [], []

        async def on_rows(rows, ts):
            got.append(list(rows))

        async def on_capture(image, rows, debug, ts, dur, error):
            caps.append((rows, debug))

        await asyncio.wait_for(poller.run_poller(
            S(), on_rows, None, w.stop, clock=w.clock, sleep=w.sleep,
            last_image_path=str(tmp_path / "last.jpg"), on_capture=on_capture), timeout=10)
        return got, caps
    return go


async def test_alt_off_output_is_unchanged(run, monkeypatch):
    monkeypatch.setattr(alt, "apply", lambda *a, **k: pytest.fail("alt must not run"))
    got, caps = await run()
    assert got and all(len(r) == 5 for r in got)
    assert all(e["row"] is None for _, d in caps for e in d if e["row_index"] == 2)
    assert all("alt" not in e for _, d in caps for e in d)
    assert ocr_stats.snapshot()["alt"] == {"frames": 0, "tried": 0, "recovered": 0}


async def test_alt_on_recovers_the_unread_line_and_marks_it(run, monkeypatch):
    monkeypatch.setenv("OCR_ALT", "1")
    got, caps = await run()
    assert got and all(len(r) == 6 for r in got)
    assert any(r.train_no == 7942 and r.sched_time == "10:20" for r in got[0])
    rows, debug = caps[0]
    e = debug[2]
    assert e["alt"] and e["row"].uncertain and len(rows) == 6
    assert observations.line_version("v", e).endswith("+ocr:alt")
    assert "+ocr:alt" not in observations.line_version("v", debug[1])
    assert ocr_stats.snapshot()["alt"]["recovered"] >= 1


async def test_alt_shadow_does_not_change_rows(run, monkeypatch, caplog):
    monkeypatch.setenv("OCR_ALT", "1")
    monkeypatch.setenv("OCR_ALT_SHADOW", "1")
    with caplog.at_level("INFO", logger="app.ocr.alt_shadow"):
        got, caps = await run()
    assert got and all(len(r) == 5 for r in got)
    assert all(e["row"] is None and "alt" not in e for _, d in caps for e in d
               if e["row_index"] == 2)
    assert any("alt-shadow" in r.getMessage() for r in caplog.records)
