# © 2026 Andy217Ace
"""Alternativa OCR (app/ocr/alt_reader.py): citirea celulelor, declansarea, completarea liniilor.

Fara Tesseract si fara capturi reale: celulele se construiesc din sabloanele de cifre ale
tablei, modelul de test e liniar peste aceleasi sabloane (un MLP cu greutati sablon)."""
from __future__ import annotations

import dataclasses

import cv2
import numpy as np
import pytest

from app.models import Row
from app.ocr import alt_reader as alt
from app.ocr import digits, order

_D = np.load(digits.TEMPLATES_PATH)
_LABELS = str(_D["labels"])
_T = _D["templates"].astype(np.float32)


def make_model(scale: float = 60.0) -> alt.AltModel:
    k = len(alt.CLASSES)
    w1 = np.zeros((1024, k), np.float32)
    for i, c in enumerate(alt.CLASSES):
        t = _T[_LABELS.find(c)].reshape(-1)
        t = t - t.mean()
        w1[:, i] = t / np.linalg.norm(t)
    return alt.AltModel(w1, np.zeros(k, np.float32), np.eye(k, dtype=np.float32) * scale,
                        np.zeros(k, np.float32))


def make_cell(text: str, h: int = 60, gap: int = 14) -> np.ndarray:
    """Celula (0 = cerneala, 255 = fond) cu `text` in fontul tablei."""
    parts = []
    for c in text:
        g = (_T[_LABELS.find(c)] > 0.5).astype(np.uint8)
        parts += [cv2.resize(g, (h, h), interpolation=cv2.INTER_NEAREST),
                  np.zeros((h, gap), np.uint8)]
    ink = np.pad(np.hstack(parts), ((6, 6), (8, 8)))
    return np.where(ink > 0, 0, 255).astype(np.uint8)


MODEL = make_model()
BLANK = np.full((60, 80), 255, np.uint8)


# --- read_cell ---------------------------------------------------------------------------
@pytest.mark.parametrize("text,col,want", [
    ("05:28", "time", "05:28"), ("14:07", "time", "14:07"), ("9:45", "time", "09:45"),
    ("3021", "no", "3021"), ("7", "no", "7"), ("11631", "no", "11631"),
])
def test_read_cell_reads_values(text, col, want):
    r = alt.read_cell(MODEL, make_cell(text), col)
    assert r is not None and r[0] == want and r[1] >= alt.MIN_PROB


def test_read_cell_empty_cell_is_none():
    assert alt.read_cell(MODEL, BLANK, "no") is None
    assert alt.read_cell(MODEL, BLANK, "time") is None


def test_read_cell_invalid_time_is_none():
    assert alt.read_cell(MODEL, make_cell("99:99"), "time") is None
    assert alt.read_cell(MODEL, make_cell("25:00"), "time") is None


def test_read_cell_zero_or_too_long_number_is_none():
    assert alt.read_cell(MODEL, make_cell("0"), "no") is None
    assert alt.read_cell(MODEL, make_cell("123456"), "no") is None


def test_read_cell_low_confidence_is_none():
    flat = make_model(scale=0.5)  # softmax aproape plat: nicio glifa nu atinge pragul
    assert alt.read_cell(flat, make_cell("3021"), "no") is None
    assert alt.read_cell(MODEL, make_cell("3021"), "no", min_prob=1.01) is None


def test_read_cell_fused_glyphs_are_not_guessed():
    cell = make_cell("31", gap=0)  # doua cifre lipite
    spans = digits.segment_spans(cell)
    r = alt.read_cell(MODEL, cell, "no")
    if any(fused for _, _, fused in spans):
        assert r is None  # segmentarea nu stie cate cifre sunt: nu se ghiceste
    else:
        assert r is None or r[0] == "31"


def test_proba_masks_disallowed_characters():
    p = MODEL.proba([np.zeros((32, 32), np.float32)], alt.ALLOWED["no"])
    assert p[0][alt.CLASSES.index(":")] == 0 and p[0][alt.CLASSES.index("+")] == 0
    assert p.sum() == pytest.approx(1.0)


# --- model -------------------------------------------------------------------------------
def test_model_roundtrip_and_shape_check(tmp_path):
    f = tmp_path / "model-2026-11-17.npz"
    np.savez(f, W1=MODEL.W1, b1=MODEL.b1, W2=MODEL.W2, b2=MODEL.b2)
    m = alt.AltModel.load(f)
    assert alt.read_cell(m, make_cell("3021"), "no")[0] == "3021"
    with pytest.raises(ValueError):
        alt.AltModel(np.zeros((10, 4)), np.zeros(4), np.zeros((4, 12)), np.zeros(12))


def test_stale_engine_fingerprint_disables_the_model(tmp_path):
    f = tmp_path / "m.npz"
    np.savez(f, W1=MODEL.W1, b1=MODEL.b1, W2=MODEL.W2, b2=MODEL.b2, engine_fp="deadbeef")
    with pytest.raises(ValueError, match="amprenta"):
        alt.AltModel.load(f)
    np.savez(f, W1=MODEL.W1, b1=MODEL.b1, W2=MODEL.W2, b2=MODEL.b2,
             engine_fp=alt.engine_fingerprint())
    assert alt.AltModel.load(f) is not None


def test_get_model_without_or_with_broken_file(tmp_path, monkeypatch):
    monkeypatch.delenv("OCR_ALT_MODEL", raising=False)
    assert alt.get_model() is None
    monkeypatch.setenv("OCR_ALT_MODEL", str(tmp_path / "lipsa.npz"))
    assert alt.get_model() is None  # fisier lipsa: alternativa oprita, nu exceptie
    bad = tmp_path / "bad.npz"
    bad.write_bytes(b"not an npz")
    monkeypatch.setenv("OCR_ALT_MODEL", str(bad))
    assert alt.get_model() is None


# --- intrari de debug false pentru declansare / completare -------------------------------------
def field(norm=None, raw=""):
    return {"raw": raw, "norm": norm, "conf": None, "bbox": [0, 0, 1, 1]}


def entry(board, j, no=None, time=None, typ="R", state=None):
    """Linie de debug; cu tip, numar si ora are rand, altfel e necitita (sau `state`)."""
    f = {"type": field(typ, typ or ""), "no": field(no, str(no or "")),
         "station": field("BRASOV", "BRASOV"), "operator": field("CFR CALATORI", "CFR"),
         "time": field(time, time or ""), "delay": field(0, ""), "platform": field(3, "3")}
    row = None
    if typ and no and time:
        row = Row(board=board, train_type=typ, train_no=no, station="BRASOV",
                  operator="CFR CALATORI", sched_time=time, platform=3, confidence=0.9)
    return {"board": board, "row_index": j, "row": row, "conf": 0.8, "raw_text": "x",
            "fields": f, "state": state or ("ok" if row else "unread")}


def read_entries():
    """Panou 'arrival' de 6 linii citite (ore crescatoare), a 3-a necitita."""
    times = ["10:00", "10:10", "10:20", "10:30", "10:40", "10:50"]
    es = [entry("arrival", j, 1000 + j, t) for j, t in enumerate(times)]
    es[2] = entry("arrival", 2, None, None, state="unread")
    return es


class FakePanel:
    def __init__(self, cells):
        self._cells = cells

    def __len__(self):
        return 12

    def cells(self, j):
        return self._cells[j]


@pytest.fixture
def fake_panels(monkeypatch):
    def install(cells_by_board):
        monkeypatch.setattr(alt, "_panels", lambda image: {
            b: FakePanel(c) for b, c in cells_by_board.items()})
    return install


def test_eligible_needs_type_and_a_missing_numeric_column():
    es = read_entries()
    assert alt.eligible(es) == [2]
    es[2]["fields"]["type"]["norm"] = None  # fara tip: MLP-ul nu citeste litere
    assert alt.eligible(es) == []


def test_eligible_skips_empty_lines():
    es = read_entries()
    es.append(entry("arrival", 7, None, None, typ=None, state="empty"))
    assert alt.eligible(es) == [2]


def test_eligible_skips_broken_panels():
    es = [entry("arrival", j, None, None, state="unread") for j in range(alt.MAX_UNREAD + 1)]
    assert alt.eligible(es) == []  # peste prag: cadru stricat la sursa, nu se inventeaza
    assert alt.eligible(es[:alt.MAX_UNREAD]) != []
    assert alt.eligible(es[:2], lo=3) == []  # pragul de declansare reglabil


def test_recover_fills_missing_number_and_marks_the_line(fake_panels):
    es = read_entries()
    es[2] = entry("arrival", 2, None, "10:20", state="unread")  # ora citita, numarul nu
    fake_panels({"arrival": {2: {"no": make_cell("7942"), "time": make_cell("23:59")}}})
    info = alt.recover(b"img", es, MODEL)
    e = es[2]
    assert info["recovered"] == 1 and info["lines"] == [2]
    assert e["row"].train_no == 7942 and e["row"].sched_time == "10:20"  # ora cititorului
    assert e["state"] == "ok" and e["alt"]["cols"] == ["no"]
    assert e["fields"]["no"]["check"] == "alt" and e["fields"]["time"].get("check") is None
    assert e["row"].uncertain and e["row"].confidence <= order.REPAIRED_CONFIDENCE
    assert e["row"].station == "BRASOV"


def test_recover_fills_both_columns_in_chronological_order(fake_panels):
    es = read_entries()
    fake_panels({"arrival": {2: {"no": make_cell("7942"), "time": make_cell("10:20")}}})
    assert alt.recover(b"img", es, MODEL)["recovered"] == 1
    assert (es[2]["row"].train_no, es[2]["row"].sched_time) == (7942, "10:20")
    assert es[2]["alt"]["cols"] == ["no", "time"]


def test_recover_rejects_a_time_out_of_the_panel_order(fake_panels):
    es = read_entries()
    fake_panels({"arrival": {2: {"no": make_cell("7942"), "time": make_cell("19:20")}}})
    info = alt.recover(b"img", es, MODEL)
    assert info["recovered"] == 0 and es[2]["row"] is None and es[2]["state"] == "unread"


def test_recover_rejects_the_number_of_another_line(fake_panels):
    es = read_entries()
    fake_panels({"arrival": {2: {"no": make_cell("1001"), "time": make_cell("10:20")}}})
    assert alt.recover(b"img", es, MODEL)["recovered"] == 0  # 1001 e linia 1


def test_recover_leaves_the_line_unread_when_a_cell_is_unsure(fake_panels):
    es = read_entries()
    fake_panels({"arrival": {2: {"no": make_cell("7942"), "time": BLANK}}})
    assert alt.recover(b"img", es, MODEL)["recovered"] == 0
    assert es[2]["row"] is None and "alt" not in es[2]


def test_recover_without_unread_lines_does_nothing_and_decodes_nothing(monkeypatch):
    es = [entry("arrival", j, 1000 + j, f"10:{j:02d}") for j in range(6)]
    before = [dataclasses.replace(e["row"]) for e in es]
    monkeypatch.setattr(alt, "_panels", lambda image: pytest.fail("nu se decodeaza imaginea"))
    info = alt.recover(b"img", es, MODEL)
    assert info["reason"] == "no_eligible_lines" and info["recovered"] == 0
    assert [e["row"] for e in es] == before and all("alt" not in e for e in es)


def test_recover_respects_its_own_budget(fake_panels):
    es = read_entries()
    fake_panels({"arrival": {2: {"no": make_cell("7942"), "time": make_cell("10:20")}}})
    info = alt.recover(b"img", es, MODEL, budget=-1.0)
    assert info["reason"] == "budget" and info["recovered"] == 0


# --- apply: punctul de intrare, oprit implicit -----------------------------------------------
def test_apply_is_off_by_default(monkeypatch, fake_panels):
    monkeypatch.delenv("OCR_ALT", raising=False)
    es = read_entries()
    fake_panels({"arrival": {2: {"no": make_cell("7942"), "time": make_cell("10:20")}}})
    assert alt.apply(b"img", es, MODEL)["reason"] == "disabled"
    assert es[2]["row"] is None


def test_apply_on_with_model_recovers_and_without_model_is_noop(monkeypatch, fake_panels):
    monkeypatch.setenv("OCR_ALT", "1")
    es = read_entries()
    fake_panels({"arrival": {2: {"no": make_cell("7942"), "time": make_cell("10:20")}}})
    monkeypatch.delenv("OCR_ALT_MODEL", raising=False)
    assert alt.apply(b"img", es)["reason"] == "no_model" and es[2]["row"] is None
    assert alt.apply(b"img", es, MODEL)["recovered"] == 1


def test_apply_swallows_internal_errors(monkeypatch):
    monkeypatch.setenv("OCR_ALT", "1")
    es = read_entries()

    def boom(image):
        raise RuntimeError("x")
    monkeypatch.setattr(alt, "_panels", boom)
    assert alt.apply(b"img", es, MODEL)["reason"] == "error"
    assert es[2]["row"] is None  # cadrul ramane cum l-a lasat cititorul


def test_alt_mark_does_not_break_the_version_parser():
    from app.observations import parse_line_version
    assert parse_line_version("ocr-tess-grid-5+ocr:alt") == {"state": "ok", "retry": None}
    assert parse_line_version("v+retry:lvl+:2+ocr:alt")["retry"] == {"variant": "lvl+",
                                                                      "attempts": 2}


def test_apply_shadow_mode_logs_but_changes_nothing(monkeypatch, fake_panels, caplog):
    monkeypatch.setenv("OCR_ALT", "1")
    monkeypatch.setenv("OCR_ALT_SHADOW", "1")
    es = read_entries()
    fake_panels({"arrival": {2: {"no": make_cell("7942"), "time": make_cell("10:20")}}})
    with caplog.at_level("INFO", logger="app.ocr.alt_shadow"):
        info = alt.apply(b"img", es, MODEL)
    assert info["recovered"] == 1 and info["shadow"] is True
    assert es[2]["row"] is None and "alt" not in es[2]  # nimic publicat
    assert "7942" in caplog.text


def test_apply_error_leaves_entries_untouched(monkeypatch, fake_panels):
    monkeypatch.setenv("OCR_ALT", "1")
    monkeypatch.delenv("OCR_ALT_SHADOW", raising=False)
    es = read_entries()
    fake_panels({"arrival": {2: {"no": make_cell("7942"), "time": make_cell("10:20")}}})
    monkeypatch.setattr(alt, "_build_row", lambda *a: (_ for _ in ()).throw(ValueError("x")))
    assert alt.apply(b"img", es, MODEL)["reason"] == "error"
    assert es == read_entries()
