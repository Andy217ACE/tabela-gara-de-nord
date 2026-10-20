# © 2026 Andy217Ace
import difflib
import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.models import Row
from app.ocr import preprocess
from app.ocr.reader import COLUMNS, read_board

FIX = Path(__file__).parent / "fixtures"
NUMERIC = ("train_no", "sched_time", "delay_min", "platform")


def _bytes() -> bytes:
    return (FIX / "board_1.jpg").read_bytes()


def _golden() -> dict:
    return json.loads((FIX / "board_1.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rows() -> list[Row]:
    return read_board(_bytes())


def _split(rows):
    return ([r for r in rows if r.board == "arrival"],
            [r for r in rows if r.board == "departure"])


def _pairs(rows):
    arr, dep = _split(rows)
    g = _golden()
    return list(zip(arr, g["arrival"])) + list(zip(dep, g["departure"]))


def _accuracy(pairs, field):
    return sum(getattr(r, field) == e[field] for r, e in pairs) / 24


def test_row_count(rows):
    arr, dep = _split(rows)
    assert len(arr) == 12
    assert len(dep) == 12


def test_numeric_fields_exact(rows):
    pairs = _pairs(rows)
    assert len(pairs) == 24
    for field in NUMERIC:
        assert _accuracy(pairs, field) >= 0.95, field
    assert all(r.sched_time == e["sched_time"] for r, e in pairs)


def test_train_type_and_flag(rows):
    pairs = _pairs(rows)
    assert _accuracy(pairs, "train_type") >= 0.95
    assert _accuracy(pairs, "flagged") >= 0.95


def test_text_fields_close(rows):
    pairs = _pairs(rows)
    ok = sum(
        difflib.SequenceMatcher(None, r.station, e["station"]).ratio() >= 0.85
        for r, e in pairs
    )
    assert ok / 24 >= 0.90


def test_confidence_range(rows):
    assert rows
    assert all(0.0 <= r.confidence <= 1.0 for r in rows)
    assert sum(r.confidence for r in rows) / len(rows) > 0.5


def test_columns_are_fractions():
    assert set(COLUMNS) == {
        "type", "no", "station", "operator", "time", "delay", "platform"}
    for x0, x1 in COLUMNS.values():
        assert 0.0 <= x0 < x1 <= 1.0


def test_watermark_ignored():
    img = np.zeros((200, 600, 3), np.uint8)
    img[:] = (170, 40, 10)  # BGR blue panel
    cv2.line(img, (0, 200), (600, 0), (30, 30, 220), 25)  # red diagonal watermark
    cv2.putText(img, "www.cfr.ro", (150, 120), cv2.FONT_HERSHEY_SIMPLEX, 2,
                (40, 40, 230), 6)
    mask = preprocess.text_mask(img)
    assert mask.shape[:2] == (600, 1800)  # upscaled x3
    assert (mask == 0).sum() == 0  # no black (text) pixels at all


def test_text_mask_keeps_white_and_yellow():
    img = np.zeros((60, 200, 3), np.uint8)
    img[:] = (170, 40, 10)
    img[10:30, 10:40] = (255, 255, 255)   # white
    img[10:30, 100:130] = (0, 230, 255)   # yellow
    mask = preprocess.text_mask(img)
    assert mask[60, 75] == 0 and mask[60, 345] == 0
    assert mask[150, 300] == 255  # blue background -> white


def test_split_boards_halves():
    img = cv2.imdecode(np.frombuffer(_bytes(), np.uint8), cv2.IMREAD_COLOR)
    arr, dep = preprocess.split_boards(img)
    h, w = img.shape[:2]
    assert arr.shape[0] == h and dep.shape[0] == h
    assert 0.4 * w < arr.shape[1] < 0.5 * w
    assert 0.4 * w < dep.shape[1] < 0.5 * w


def test_row_bands_on_fixture():
    img = cv2.imdecode(np.frombuffer(_bytes(), np.uint8), cv2.IMREAD_COLOR)
    for half in preprocess.split_boards(img):
        bands = preprocess.row_bands(preprocess.board_mask(half))
        assert len(bands) == 12
        assert all(y0 < y1 for y0, y1 in bands)


def test_digit_templates_generalise_to_held_out_board():
    """Templates are built from the arrivals panel only; departures are unseen."""
    from app.ocr.digits import DigitMatcher
    from app.ocr.reader import cell_grid

    matcher = DigitMatcher.load()
    assert "arrival" in matcher.boards
    assert "departure" not in matcher.boards  # otherwise this test is circular
    img = cv2.imdecode(np.frombuffer(_bytes(), np.uint8), cv2.IMREAD_COLOR)
    dep = preprocess.split_boards(img)[1]
    ok = 0
    for cells, e in zip(cell_grid(dep), _golden()["departure"]):
        ok += matcher.read(cells["no"], "0123456789")[0] == str(e["train_no"])
        ok += matcher.read(cells["time"], "0123456789:")[0] == e["sched_time"]
        plat = matcher.read(cells["platform"], "0123456789")[0]
        ok += plat == ("" if e["platform"] is None else str(e["platform"]))
    assert ok >= 35  # of 36


def test_digit_templates_file_shipped_next_to_module():
    from app.ocr import digits

    assert digits.TEMPLATES_PATH.parent == Path(digits.__file__).parent
    assert digits.TEMPLATES_PATH.is_file()


def test_digit_templates_reproducible_from_fixture():
    from app.ocr.digits import DEFAULT_BOARDS, DigitMatcher, build_from_fixture

    assert DEFAULT_BOARDS == ("arrival",)
    labels, templates = build_from_fixture(
        FIX / "board_1.jpg", FIX / "board_1.json", DEFAULT_BOARDS)
    committed = DigitMatcher.load()
    assert labels == committed.labels
    assert templates.shape == committed.templates.shape
    assert np.abs(templates - committed.templates).max() < 1e-3


def test_cli_defaults_to_arrival_only(tmp_path, monkeypatch):
    from app.ocr import digits

    out = tmp_path / "t.npz"
    monkeypatch.setattr(digits, "TEMPLATES_PATH", out)
    assert digits.main([str(FIX / "board_1.jpg"), str(FIX / "board_1.json")]) == 0
    assert digits.DigitMatcher.load(out).boards == ("arrival",)


def test_missing_templates_logs_warning(monkeypatch, caplog, tmp_path):
    from app.ocr import digits, reader

    monkeypatch.setattr(digits, "TEMPLATES_PATH", tmp_path / "missing.npz")
    monkeypatch.setattr(reader, "_matcher", None)
    monkeypatch.setattr(reader, "_matcher_loaded", False)
    with caplog.at_level("WARNING", logger="app.ocr.reader"):
        assert reader._get_matcher() is None
    assert any("template" in r.getMessage().lower() for r in caplog.records)


def test_too_small_image_rejected():
    tiny = np.zeros((40, 150, 3), np.uint8)
    tiny[:] = (170, 40, 10)
    ok, buf = cv2.imencode(".png", tiny)
    with pytest.raises(ValueError, match="prea mică"):
        read_board(buf.tobytes())


@pytest.mark.parametrize("kind", ["timeout", "tesseract_error"])
def test_tesseract_failure_raises_ocr_error(monkeypatch, kind):
    import pytesseract

    from app.ocr import reader

    exc = (RuntimeError("Tesseract process timeout") if kind == "timeout"
           else pytesseract.TesseractError(1, "boom"))
    seen = {}

    def boom(*args, **kwargs):
        seen.update(kwargs)
        raise exc

    monkeypatch.setattr(reader.pytesseract, "image_to_data", boom)
    with pytest.raises(reader.OcrError):
        read_board(_bytes())
    assert seen.get("timeout") == reader.TESSERACT_TIMEOUT == 10


def test_segment_splits_touching_digits():
    from app.ocr.digits import segment

    cell = np.full((40, 120), 255, np.uint8)
    cv2.putText(cell, "88", (5, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.3, 0, 5)
    cell[8:34, 30:45] = 0  # glue the two glyphs together
    assert len(segment(cell)) == 2
    assert segment(np.full((40, 120), 255, np.uint8)) == []


def test_garbage_image():
    with pytest.raises(ValueError):
        read_board(b"not an image")
    blue = np.zeros((350, 1100, 3), np.uint8)
    blue[:] = (170, 40, 10)
    ok, buf = cv2.imencode(".png", blue)
    assert read_board(buf.tobytes()) == []


def test_upscaled_rendition_still_reads():
    img = cv2.imdecode(np.frombuffer(_bytes(), np.uint8), cv2.IMREAD_COLOR)
    big = cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".jpg", big, [cv2.IMWRITE_JPEG_QUALITY, 92])
    pairs = _pairs(read_board(buf.tobytes()))
    assert _accuracy(pairs, "sched_time") >= 0.90


def test_read_board_speed():
    data = _bytes()
    read_board(data)  # warm-up
    t0 = time.perf_counter()
    read_board(data)
    assert time.perf_counter() - t0 < 4.0  # target ~2 s; generous for CI noise
