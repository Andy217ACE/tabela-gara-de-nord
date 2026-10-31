# © 2026 Andy217Ace
"""Real-browser flow of the manual corrections in „Capturi OCR" (#ocr): login -> capture ->
„Corectează” on a row -> preview -> save -> retroactive preview -> apply -> restore ->
delete; no console/CSP errors, no horizontal scroll on a phone, the public Tabela unchanged.
Set CORR_SHOTS=<dir> to also write the screenshots. Skipped without Playwright/Chromium."""
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

import uvicorn  # noqa: E402

from app.api import create_app  # noqa: E402
from app.config import Settings  # noqa: E402
from tests.ocr_truth_images import capture  # noqa: E402
from tests.test_footer_browser import browser  # noqa: E402,F401  (shared fixture)

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "browser-test-admin-token-123"


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    capture(ROOT / "tests" / "fixtures" / "board_1.jpg")  # --capture-dir needs the photo
    d = tmp_path_factory.mktemp("corrb")
    db, cap = d / "c.db", d / "cap"
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
    subprocess.run([sys.executable, str(ROOT / "scripts" / "dev_seed.py"), str(db),
                    "--capture-dir", str(cap)], check=True, cwd=ROOT, capture_output=True,
                   env=env)
    # the real example: the board shows IR 1584, the train is 1581 (here: the departure of
    # row 5, read 1589 in the fixture, stands for the stable misread)
    c = sqlite3.connect(db)
    c.execute("UPDATE services SET train_no=1584, train_type='IR' WHERE train_no=1589")
    c.execute("UPDATE observations SET train_no=1584 WHERE train_no=1589")
    c.commit()
    c.close()
    os.environ["ADMIN_TOKEN"] = TOKEN
    os.environ["CAPTURE_DIR"] = str(cap)
    settings = Settings(db_path=str(db), source_url="http://127.0.0.1:9/none",
                        vapid_private_key="", vapid_public_key="", vapid_subject="mailto:a@b.c",
                        tesseract_cmd="tesseract", poller_enabled=False, last_image_path=None)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(create_app(settings, start_poller=False),
                                        host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", db
    srv.should_exit = True
    t.join(5)
    os.environ.pop("ADMIN_TOKEN", None)
    os.environ.pop("CAPTURE_DIR", None)


def _shot(page, name):
    out = os.environ.get("CORR_SHOTS")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(out) / f"{name}.png"), full_page=True)


def _open(browser, base, w, h, theme):
    ctx = browser.new_context(viewport={"width": w, "height": h}, service_workers="block")
    ctx.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}');")
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda dlg: dlg.accept())
    page.goto(base + "/#ocr")
    page.fill("#ocr-token", TOKEN)
    page.click(".ocr-login button[type=submit]")
    page.wait_for_selector("#ocr-rows tr")
    return ctx, page, errors


def _train(db, _unused=0):
    c = sqlite3.connect(db)
    r = c.execute("SELECT train_no FROM services WHERE train_no IN (?,?) ORDER BY id",
                  (1584, 1581)).fetchall()
    c.close()
    return [x[0] for x in r]


def _tabela_png(browser, base):
    ctx = browser.new_context(viewport={"width": 1280, "height": 800}, service_workers="block")
    ctx.add_init_script("localStorage.setItem('tabela.theme','dark');"
                        "localStorage.setItem('tabela.view','panou');")
    page = ctx.new_page()
    page.goto(base + "/")
    page.wait_for_selector(".pnl-clock")
    page.wait_for_timeout(500)
    png = page.screenshot(full_page=True, animations="disabled", mask=[
        page.locator("#hdr-clock"), page.locator("#live"), page.locator(".pnl-clock"),
        page.locator(".pnl-status"), page.locator(".pnl-clockwx")])
    ctx.close()
    return png


@pytest.mark.parametrize("w,h,theme", [(1280, 900, "dark"), (390, 844, "light")])
def test_full_flow(browser, server, w, h, theme):
    base, db = server
    ctx, page, errors = _open(browser, base, w, h, theme)
    try:
        page.click(".ocr-open")
        page.wait_for_selector("#ocr-detail .ocr-obs")
        _shot(page, f"1-captura-{w}-{theme}")
        # departures, line 5 (stored as 1584 here; the fixture image still reads 1589)
        row = page.locator("#ocr-detail table.ocr-obs").nth(1).locator("tbody tr").nth(5)
        row.get_by_role("button", name="Corectează").click()
        page.wait_for_selector("#ocr-corr-form:not([hidden]) #corr-field")
        assert page.input_value("#corr-wrong") == "1584"
        page.fill("#corr-right", "1581")
        # validation: missing note is refused by the browser/server, nothing is saved
        page.fill("#corr-note", "")
        page.click("#ocr-corr-form button[type=submit]")
        assert page.locator("#ocr-corr-form .ocr-corr-result .ocr-stats").count() == 0
        page.fill("#corr-note", "IR 1581: cifra 1 final citită 4 (cadrul văzut în captură)")
        page.click("#ocr-corr-form button[type=submit]")
        page.wait_for_selector("#ocr-corr-form .ocr-corr-result .ocr-stats")
        assert "Previzualizare" in page.inner_text("#ocr-corr-form")
        _shot(page, f"2-formular-previzualizare-{w}-{theme}")
        assert _train(db, 0).count(1584) >= 1  # the dry run changed nothing
        page.click("text=Salvează regula")
        page.wait_for_selector("#ocr-rules .ocr-rule-table tbody tr")
        assert "1584 → 1581" in page.inner_text("#ocr-rules")
        # retroactive: preview (dry run), then apply
        page.click("text=Previzualizează retroactiv")
        page.wait_for_selector("#ocr-rule-result .ocr-stats")
        assert 1584 in _train(db, 0)
        _shot(page, f"3-previzualizare-retroactiva-{w}-{theme}")
        page.click("text=/Aplică retroactiv/")
        page.wait_for_selector("text=/Restaurează lotul/")
        assert 1584 not in _train(db, 0) and 1581 in _train(db, 0)
        _shot(page, f"4-aplicat-{w}-{theme}")
        page.click("text=Jurnal de audit")
        page.wait_for_selector("#ocr-rule-result table")
        assert "aplicată retroactiv" in page.inner_text("#ocr-rule-result")
        _shot(page, f"5-jurnal-{w}-{theme}")
        # the page never scrolls sideways
        assert not page.evaluate("document.documentElement.scrollWidth >"
                                 " document.documentElement.clientWidth + 1")
        # restore puts the data back; delete is soft
        page.click("text=/Restaurează lotul/")
        page.locator("#ocr-rules button", has_text="Restaurează").wait_for(state="detached")
        assert 1584 in _train(db, 0)
        page.locator("#ocr-rules button", has_text="Șterge").first.click()
        page.wait_for_timeout(300)
        c = sqlite3.connect(db)
        assert c.execute("SELECT COUNT(*) FROM corrections").fetchone()[0] >= 1  # never hard-deleted
        c.close()
        assert errors == []
    finally:
        ctx.close()


def test_tabela_unchanged_by_corrections(browser, server):
    """The public panel is byte-identical before and after a rule exists (and was applied to
    data that is not on the board): corrections add nothing to the public pages."""
    base, db = server
    a = _tabela_png(browser, base)
    c = sqlite3.connect(db)
    c.execute("INSERT INTO corrections(board, field, wrong_value, correct_value, note,"
              " status, created_at) VALUES ('arrival','no','99991','99992','nota',"
              "'active','2026-10-27T00:00:00+00:00')")
    c.commit()
    c.close()
    b = _tabela_png(browser, base)
    assert a == b
    sw = (ROOT / "web" / "sw.js").read_text(encoding="utf-8")
    assert "ocr.js" not in sw and "corrections" not in sw  # admin code never precached
