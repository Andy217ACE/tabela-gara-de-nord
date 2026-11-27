# © 2026 Andy217Ace
"""Suita de regresie OCR: cititorul de productie pe doua seturi etichetate de mana, cu
baseline versionat (``tests/fixtures/ocr_truth/regression-baseline.json``).

  truth    tests/fixtures/ocr_truth/truth.json            setul de dezvoltare (reglare)
  holdout  tests/fixtures/ocr_truth/holdout/holdout.json  validare independenta: etichetat orb,
                                                          niciodata folosit la reglare

Partea care ruleaza in CI (fara imagini): baseline-ul corespunde etichetelor (amprenta
sha256), seturile sunt disjuncte intre ele (hash-ul capturii si >= 60 min) si antrenarea in
umbra nu foloseste niciun cadru de evaluare. Partea cu imagini (capturile reale nu sunt in
git, vezi tests/ocr_truth_images.py) ruleaza cititorul pe fiecare cadru si cere, pe fiecare
camp: greseli <= baseline (fara toleranta), ok >= baseline - TOL, necitite <= baseline + TOL.

Baseline-ul se rescrie DOAR intentionat (dupa o imbunatatire masurata sau etichete noi):
    OCR_RECORD_REGRESSION=1 pytest tests/test_ocr_regression.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from app.observations import PROCESSING_VERSION
from app.ocr import truth
from app.ocr.reader import read_board_debug
from tests.ocr_truth_images import FIX, frame_path, read_frame

ROOT = Path(__file__).resolve().parents[1]
SETS = {"truth": FIX / "ocr_truth" / "truth.json",
        "holdout": FIX / "ocr_truth" / "holdout" / "holdout.json"}
BASELINE = FIX / "ocr_truth" / "regression-baseline.json"
TOL = 3  # linii lasate pentru alt build Tesseract/OpenCV (ca in test_ocr14); greseli: 0
MIN_GAP_S = 3600  # holdout/README.md: fiecare cadru holdout e la >= 60 min de setul truth
RECORD = os.environ.get("OCR_RECORD_REGRESSION") == "1"
# Cadre holdout copiate apoi in truth.json si folosite la reglare (5d8e0af, Beta 1.39): nu mai
# sunt nevazute, deci validarea le exclude. Lista e inchisa: o scurgere noua pica testul.
LEAKED = {"ocr_truth/holdout/2026_10_24_160005-57702940"}

_spec = importlib.util.spec_from_file_location(
    "nightly_shadow_train", ROOT / "scripts" / "nightly_shadow_train.py")
shadow = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shadow)


def _file(name: str) -> dict:
    return truth.load(SETS[name])["frames"]


def _labels(name: str) -> dict:
    """Cadrele notate: holdout fara cele scurse in setul de dezvoltare."""
    frames = _file(name)
    return frames if name == "truth" else {f: v for f, v in frames.items() if f not in LEAKED}


def labels_sha256(frames: dict) -> str:
    blob = json.dumps(frames, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _when(frame: str) -> datetime | None:
    m = shadow.FRAME_RE.search(frame)
    return datetime.strptime("".join(m.group(1, 2, 3, 4)), "%Y%m%d%H%M%S") if m else None


_results: dict[str, dict] = {}


def measure(name: str) -> dict:
    """Scorul cititorului (buget 60 s, ca test_ocr14) pe tot setul; sare daca lipseste o imagine."""
    if name not in _results:
        frames = _labels(name)
        missing = [f for f in frames if not frame_path(f).is_file()]
        if missing:
            pytest.skip(f"{len(missing)} capturi reale lipsa in setul {name} (OCR_TRUTH_DIR)")
        preds = {f: truth.lines_of(read_board_debug(read_frame(f), budget_s=60.0)[1])
                 for f in frames}
        _results[name] = truth.score({"frames": frames}, preds)
    return _results[name]


def _counts(result: dict) -> dict:
    return {f: {k: result["counts"][f][k] for k in ("ok", "unread", "wrong")}
            for f in truth.FIELDS}


def record_baseline() -> None:
    doc = {"processing_version": PROCESSING_VERSION,
           "recorded": datetime.now().strftime("%Y-%m-%d"),
           "rerecord": "OCR_RECORD_REGRESSION=1 pytest tests/test_ocr_regression.py",
           "sets": {}}
    for name in SETS:
        frames = _labels(name)
        doc["sets"][name] = {"frames": len(frames),
                             "lines": sum(len(ls) for b in frames.values() for ls in b.values()),
                             "labels_sha256": labels_sha256(frames),
                             "fields": _counts(measure(name))}
    BASELINE.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


# --- CI: fara imagini --------------------------------------------------------------------

def test_record_baseline_only_on_purpose():
    if not RECORD:
        pytest.skip("OCR_RECORD_REGRESSION=1 rescrie baseline-ul")
    record_baseline()


@pytest.mark.parametrize("name", list(SETS))
def test_baseline_matches_the_labels(name):
    """O eticheta schimbata/adaugata cere re-inregistrarea baseline-ului (cu imaginile)."""
    frames = _labels(name)
    got = _baseline()["sets"][name]
    assert got["labels_sha256"] == labels_sha256(frames), "re-inregistrati baseline-ul"
    assert got["frames"] == len(frames)
    assert set(got["fields"]) == set(truth.FIELDS)
    for f in truth.FIELDS:
        c = got["fields"][f]
        assert c["ok"] + c["unread"] + c["wrong"] <= got["lines"]


def test_holdout_is_disjoint_from_the_truth_set():
    tr, ho = _labels("truth"), _labels("holdout")
    assert set(_file("holdout")) & set(tr) == LEAKED  # nicio scurgere noua
    assert not set(tr) & set(ho)
    assert not {shadow.frame_key(f) for f in tr} & {shadow.frame_key(f) for f in ho}
    t_times = [t for t in map(_when, tr) if t]
    for f in ho:
        h = _when(f)
        assert h, f"cadru holdout fara ora in nume: {f}"
        near = min(abs((h - t).total_seconds()) for t in t_times)
        assert near >= MIN_GAP_S, (f, near)


def test_shadow_training_never_sees_an_evaluation_frame(tmp_path):
    keys = shadow.eval_frame_keys(SETS.values())
    assert keys == {shadow.frame_key(f) for f in _file("truth") | _file("holdout")}
    srv = sorted(f for f in _labels("holdout") | _labels("truth") if _when(f))[:3]
    # numele capturii pe server: YYYY/MM/DD/HHMMSS-<hash8> (app/observations.capture_path)
    as_server = ["{}/{}/{}/{}-{}".format(*shadow.FRAME_RE.search(f).groups()) for f in srv]
    other = "2026/11/20/101010-0123abcd"
    assert shadow.training_frames(as_server + [other], keys) == [other]


# --- cu imagini: acuratetea pe camp nu scade sub baseline ----------------------------------

@pytest.mark.parametrize("field", truth.FIELDS)
@pytest.mark.parametrize("name", list(SETS))
def test_field_accuracy_does_not_regress(name, field):
    r = measure(name)
    c, base = r["counts"][field], _baseline()["sets"][name]["fields"][field]
    misses = r["misses"][field]
    assert c["wrong"] <= base["wrong"], misses
    assert c["ok"] >= base["ok"] - TOL, misses
    assert c["unread"] <= base["unread"] + TOL, misses
