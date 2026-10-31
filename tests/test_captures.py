# © 2026 Andy217Ace
"""Capture retention (files only, safely under CAPTURE_DIR), stats, overlay."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np
import pytest

from app import captures as cap
from app import observations as obs
from app.store import Store
from tests.ocr_truth_images import capture

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.migrate()
    yield s
    s.close()


def rec(store, root, days_ago, data):
    return obs.record_capture(store, data, [], None, NOW - timedelta(days=days_ago),
                              capture_dir=root)


def paths(store):
    return {r[0]: r[1] for r in store._conn.execute("SELECT id, path FROM captures")}


def test_settings_defaults_and_env(monkeypatch):
    for k in ("CAPTURE_ENABLED", "CAPTURE_DIR", "CAPTURE_RETENTION_DAYS"):
        monkeypatch.delenv(k, raising=False)
    s = cap.capture_settings()
    assert s.enabled and s.retention_days == 7 and s.dir.replace("\\", "/").endswith("captures")
    monkeypatch.setenv("CAPTURE_ENABLED", "0")
    monkeypatch.setenv("CAPTURE_DIR", "/x/y")
    monkeypatch.setenv("CAPTURE_RETENTION_DAYS", "bad")
    s = cap.capture_settings()
    assert (s.enabled, s.dir, s.retention_days) == (False, "/x/y", 7)


@pytest.mark.parametrize("rel", ["../evil.jpg", "/etc/passwd", "a/../../b.jpg", "C:/x.jpg",
                                 "a\\..\\b.jpg", "", None, "."])
def test_safe_path_rejects(tmp_path, rel):
    assert cap.safe_path(tmp_path, rel) is None


def test_safe_path_accepts_relative(tmp_path):
    assert cap.safe_path(tmp_path, "2026/10/21/x.jpg") == (tmp_path / "2026/10/21/x.jpg").resolve()


def test_retention_removes_old_files_keeps_rows(store, tmp_path):
    root = tmp_path / "captures"
    old = rec(store, root, 10, b"old-image")
    new = rec(store, root, 1, b"new-image")
    old_file = root / paths(store)[old]
    assert old_file.exists()
    dry = cap.run_retention(store, root, 7, now=NOW, dry_run=True)
    assert dry["candidates"] == 1 and old_file.exists()
    res = cap.run_retention(store, root, 7, now=NOW)
    assert res["removed"] == 1 and res["bytes"] == len(b"old-image")
    assert not old_file.exists()
    p = paths(store)
    assert p[old] is None and p[new] is not None and (root / p[new]).exists()
    assert store._conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0] == 2
    exp = store._conn.execute("SELECT expires_at FROM captures WHERE id=?", (old,)).fetchone()
    assert exp[0] is not None  # kept
    assert not old_file.parent.exists()  # empty day dir pruned, root kept
    assert root.exists()
    again = cap.run_retention(store, root, 7, now=NOW)  # idempotent
    assert again["candidates"] == 0


def test_retention_missing_file_is_fine(store, tmp_path):
    cid = rec(store, tmp_path, 10, b"gone")
    (tmp_path / paths(store)[cid]).unlink()
    res = cap.run_retention(store, tmp_path, 7, now=NOW)
    assert res["missing"] == 1 and paths(store)[cid] is None


def test_retention_never_touches_outside_root(store, tmp_path):
    root = tmp_path / "captures"
    root.mkdir()
    outside = tmp_path / "precious.jpg"
    outside.write_bytes(b"keep me")
    cid = rec(store, root, 10, b"x1")
    for evil in ("../precious.jpg", str(outside), "..\\precious.jpg"):
        store._conn.execute("UPDATE captures SET path=? WHERE id=?", (evil, cid))
        res = cap.run_retention(store, root, 7, now=NOW)
        assert res["skipped"] == 1 and res["removed"] == 0
        assert outside.read_bytes() == b"keep me"
    assert paths(store)[cid] is None


def test_retention_loop_runs_and_stops(store, tmp_path):
    rec(store, tmp_path, 10, b"loop")
    settings = cap.CaptureSettings(True, str(tmp_path), 7)

    async def main():
        stop = asyncio.Event()
        t = asyncio.create_task(cap.retention_loop(store, settings, stop, first_delay=0.01,
                                                   interval=0.01))
        await asyncio.sleep(0.2)
        stop.set()
        await asyncio.wait_for(t, 2)

    asyncio.run(main())
    assert all(p is None for p in paths(store).values())


def test_capture_stats(store, tmp_path):
    rec(store, tmp_path, 3, b"aaaa")
    rec(store, tmp_path, 1, b"bb")
    s = cap.capture_stats(store)
    assert s["count"] == 2 and s["bytes"] == 6 and s["captures_total"] == 2
    assert s["oldest"].startswith("2026-10-18")


def test_overlay_png_same_size_and_coloured(store, tmp_path):
    from app.ocr.reader import read_board_debug
    data = capture(FIX / "board_1.jpg").read_bytes()
    rows, debug = read_board_debug(data)
    cid = obs.record_capture(store, data, rows, debug, NOW, capture_dir=tmp_path)
    det = cap.capture_detail(store, cid)
    assert len(det["observations"]) == len(debug)
    png = cap.overlay_png(data, det["observations"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    a = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    b = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert a.shape == b.shape
    assert (a != b).any()
    assert cap.overlay_png(b"junk", []) is None


def test_conf_colour():
    assert cap.conf_colour(95) == cap.GREEN
    assert cap.conf_colour(60) == cap.AMBER
    assert cap.conf_colour(10) == cap.RED and cap.conf_colour(None) == cap.RED


def test_list_captures_pagination(store, tmp_path):
    ids = [rec(store, tmp_path, d, f"img{d}".encode()) for d in (5, 4, 3, 2, 1)]
    first = cap.list_captures(store, limit=2)
    assert [c["id"] for c in first] == ids[::-1][:2]
    nxt = cap.list_captures(store, limit=2, before=first[-1]["id"])
    assert [c["id"] for c in nxt] == ids[::-1][2:4]
    assert set(first[0]) >= {"captured_at", "ok", "n_rows", "duration_ms", "bytes", "hash8",
                             "processing_version", "error"}
    assert "path" not in first[0]  # server paths never leave the API


def test_image_path_only_under_root(store, tmp_path):
    cid = rec(store, tmp_path, 1, b"img")
    assert cap.image_path(store, tmp_path, cid).read_bytes() == b"img"
    store._conn.execute("UPDATE captures SET path='../x' WHERE id=?", (cid,))
    assert cap.image_path(store, tmp_path, cid) is None
    assert cap.image_path(store, tmp_path, 999) is None


def test_system_stats_shape(store, tmp_path):
    obs.record_capture(store, b"a", [], None, NOW, capture_dir=tmp_path, duration_ms=100)
    obs.record_capture(store, b"b", [], None, NOW, capture_dir=tmp_path, duration_ms=300,
                       error="boom")
    s = cap.capture_system_stats(store, ":memory:", now=NOW + timedelta(minutes=1))
    assert s["errors_24h"] == 1
    assert s["duration_ms"] == {"n": 2, "avg": 200.0, "p95": 300.0}
    assert s["last_capture_ok"] and s["last_capture_attempt"]
    assert s["images"]["count"] == 2
