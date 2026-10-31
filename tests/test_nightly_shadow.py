# © 2026 Andy217Ace
"""Antrenarea zilnica in mod umbra: nu scrie in producție, nu modifică baza, raportul
spune „nu promovez". Pipeline-ul e fals (extract/label/truth), antrenarea e cea reala."""
import hashlib
import importlib.util
import json
import sqlite3
import types
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TEMPLATES = ROOT / "app" / "ocr" / "digit_templates.npz"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


shadow = _load("nightly_shadow_train", SCRIPTS / "nightly_shadow_train.py")
clf_real = _load("ocr_digit_clf", SCRIPTS / "ocr_digit_clf.py")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _make_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE captures (id INTEGER PRIMARY KEY, path TEXT)")
    con.execute("CREATE TABLE observations (id INTEGER PRIMARY KEY, capture_id INTEGER, "
                "board TEXT, row_index INTEGER, fields_json TEXT)")
    con.execute("INSERT INTO captures VALUES (1, '2026/10/31/024840-aaaa.jpg')")
    con.execute("INSERT INTO captures VALUES (2, NULL)")
    con.execute("INSERT INTO observations VALUES (1, 1, 'arrival', 0, '{\"no\": {\"raw\": \"123\"}}')")
    con.commit()
    con.close()


def _fake_clf(rng_seed=0, n=300):
    """Pipeline fals: extract nu face nimic, label scrie un dataset sintetic."""
    rng = np.random.default_rng(rng_seed)

    def extract(img_root, db_json, out_dir):
        Path(out_dir).mkdir(parents=True, exist_ok=True)

    def label(out_dir, verified=None):
        y = np.array([str(i) for i in rng.integers(0, 10, n)], dtype="U1")
        X = rng.integers(0, 256, (n, 32, 32), dtype=np.uint8)
        np.savez_compressed(
            Path(out_dir) / "dataset.npz", X=X, y=y,
            frame=np.array(["f"] * n, dtype="U200"), col=np.array(["no"] * n, dtype="U8"),
            split=np.arange(n) % 5 == 0, fused=np.zeros(n, bool),
            mchar=y.copy(), mscore=np.full(n, 0.9, np.float32),
            mmargin=np.full(n, 0.5, np.float32))
        return {"cells": 1, "by_status": {}, "glyphs_train_silver": n, "glyphs_test_silver": 0}

    def truth_glyphs(out_dir):
        y = np.array(["1", "2", "3", "4"], dtype="U1")
        X = rng.integers(0, 256, (4, 32, 32), dtype=np.uint8)
        np.savez_compressed(Path(out_dir) / "truth_glyphs.npz", X=X, y=y,
                            col=np.array(["no"] * 4, dtype="U8"),
                            mchar=y.copy(), mscore=np.full(4, 0.9, np.float32),
                            mmargin=np.full(4, 0.5, np.float32))

    return types.SimpleNamespace(
        extract=extract, label=label, truth_glyphs=truth_glyphs, TRUTH=None,
        CLASSES=clf_real.CLASSES, mlp_fit=clf_real.mlp_fit, mlp_predict=clf_real.mlp_predict,
        _acc=clf_real._acc)


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "tabela.db"
    _make_db(db)
    img_root = tmp_path / "img"
    (img_root / "captures").mkdir(parents=True)
    work = tmp_path / "shadow"
    truth = tmp_path / "truth.json"
    truth.write_text("{}", encoding="utf-8")
    return types.SimpleNamespace(db=db, img_root=img_root, work=work, truth=truth,
                                 now=datetime(2026, 10, 31, 3, 30))


def test_export_nu_modifica_baza(env):
    before = _sha(env.db)
    out = env.work
    out.mkdir()
    counts = shadow.export_db(env.db, env.img_root, out / "export.json")
    assert _sha(env.db) == before
    assert counts == {"capturi": 2, "capturi_cu_imagine": 1, "capturi_cu_fisier": 0,
                      "observatii": 1}
    data = json.loads((out / "export.json").read_text(encoding="utf-8"))
    assert data["observations"][0]["fields_json"] == '{"no": {"raw": "123"}}'


def test_run_nu_atinge_productie_si_scrie_raport(env):
    templates_before = _sha(TEMPLATES)
    db_before = _sha(env.db)
    rep = shadow.run(env.work, env.db, env.img_root, [env.truth], clf=_fake_clf(),
                     now=env.now)
    assert _sha(TEMPLATES) == templates_before, "digit_templates.npz s-a schimbat"
    assert _sha(env.db) == db_before, "baza s-a schimbat"
    assert not any(p.name == "digit_templates.npz" for p in env.work.rglob("*"))
    assert rep["stare"] == "ok"
    raport = env.work / "report-2026-10-31.json"
    assert raport.is_file()
    text = raport.read_text(encoding="utf-8")
    assert "nu promovez" in text
    data = json.loads(text)
    assert data["decizie"]["promovez"] is False
    assert data["decizie"]["decizie"] == "nu promovez"
    assert data["antrenare"]["antrenat"] is True
    assert data["antrenare"]["silver_test"]["n"] > 0
    assert data["antrenare"]["scris_de_mana"]["n"] == 4


def test_fara_set_scris_de_mana_raportul_il_spune(env):
    rep = shadow.run(env.work, env.db, env.img_root, [env.work / "lipsa.json"],
                     clf=_fake_clf(), now=env.now)
    assert rep["set_adevar"] is None
    assert rep["decizie"]["promovez"] is False
    assert "nu exista set de adevar scris de mana" in rep["decizie"]["motiv"]


def test_date_insuficiente_nu_antreneaza(env):
    rep = shadow.run(env.work, env.db, env.img_root, [env.truth],
                     clf=_fake_clf(n=20), now=env.now)
    assert rep["stare"] == "date insuficiente"
    assert rep["antrenare"]["antrenat"] is False
    assert rep["decizie"]["promovez"] is False


def test_eroare_se_raporteaza_fara_promovare(env):
    fake = _fake_clf()

    def boom(img_root, db_json, out_dir):
        raise RuntimeError("tesseract lipsa")

    fake.extract = boom
    rep = shadow.run(env.work, env.db, env.img_root, [env.truth], clf=fake, now=env.now)
    assert rep["stare"] == "eroare"
    assert rep["eroare"] == "RuntimeError: tesseract lipsa"
    data = json.loads((env.work / "report-2026-10-31.json").read_text(encoding="utf-8"))
    assert data["decizie"]["promovez"] is False


def test_imaginile_setului_se_cauta_in_workdir_si_se_raporteaza(env):
    fake, seen = _fake_clf(), {}
    real = fake.truth_glyphs

    def truth_glyphs(out_dir):
        seen["dirs"] = list(fake.TRUTH_IMG_DIRS)
        real(out_dir)
        return {"frames": 5, "frames_missing": 2, "cells": 4, "count": 0}

    fake.truth_glyphs = truth_glyphs
    rep = shadow.run(env.work, env.db, env.img_root, [env.truth], clf=fake, now=env.now)
    assert seen["dirs"] == [env.work.resolve() / "truth-img"]
    assert rep["set_adevar_cadre"]["frames_missing"] == 2
    data = json.loads((env.work / "report-2026-10-31.json").read_text(encoding="utf-8"))
    assert data["set_adevar_cadre"]["frames"] == 5


def _truth_json(path: Path, frames) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"no": 1636, "time": "20:04", "platform": None, "delay": 10}
    path.write_text(json.dumps({"frames": {f: {"arrival": [line]} for f in frames}}),
                    encoding="utf-8")
    return path


def test_cadrele_fara_imagine_se_sar_fara_eroare(tmp_path, monkeypatch):
    truth = _truth_json(tmp_path / "fix" / "ocr_truth" / "truth.json",
                        ["ocr13/a", "ocr_truth/srv/b"])
    monkeypatch.setattr(clf_real, "TRUTH", truth)
    monkeypatch.setattr(clf_real, "TRUTH_IMG_DIRS", [tmp_path / "img"])
    out = tmp_path / "out"
    skipped = clf_real.truth_glyphs(str(out))
    assert skipped["frames"] == 2 and skipped["frames_missing"] == 2
    assert not (out / "truth_glyphs.npz").exists()


def test_ordinea_cautarii_imaginilor_setului(tmp_path, monkeypatch):
    fix = tmp_path / "fix"
    truth = _truth_json(fix / "ocr_truth" / "truth.json", [])
    extra = tmp_path / "img"
    monkeypatch.setattr(clf_real, "TRUTH", truth)
    monkeypatch.setattr(clf_real, "TRUTH_IMG_DIRS", [extra])

    def put(p: Path, data: bytes):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    put(fix / "ocr13" / "a.jpg", b"repo")
    assert clf_real._truth_image("ocr13/a") == b"repo"
    put(extra / "ocr13" / "a.jpg", b"workdir")
    assert clf_real._truth_image("ocr13/a") == b"workdir"
    put(fix / "ocr_truth" / "private" / "srv" / "b.jpg", b"private")
    assert clf_real._truth_image("ocr_truth/srv/b") == b"private"
    assert clf_real._truth_image("ocr13/lipsa") is None


def test_workdir_in_repo_refuzat():
    with pytest.raises(ValueError):
        shadow.run(ROOT / "app" / "ocr" / "shadow", ROOT / "x.db", ROOT, [],
                   clf=_fake_clf(), now=datetime(2026, 10, 31))
