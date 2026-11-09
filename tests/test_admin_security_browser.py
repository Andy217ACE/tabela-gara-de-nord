# © 2026 Andy217Ace
"""Cardul „Securitate" din #admin într-un browser real: login -> rezumat, tabele (banați acum,
istoric, top IP-uri), ore în ora României, „—" pentru valori lipsă, sortare, fereastra 24 h /
7 zile, căile ostile afișate ca text (fără HTML executat), fără scroll orizontal la 390 px,
temă luminoasă/întunecată, fără erori de consolă/CSP. Set SEC_SHOTS=<dir> pentru capturi.
Skipped without Playwright/Chromium."""
import json
import os
import socket
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
from tests.test_admin_security import snapshot  # noqa: E402
from tests.test_footer_browser import browser  # noqa: E402,F401  (shared fixture)

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "browser-test-admin-token-sec"
XSS = '/<img src=x onerror="window.__xss=1">.php'


def _data(now):
    s = snapshot(now, generated_ts=now - 120)
    s["banned"].append({"ip": "203.0.113.9", "jail": "sshd", "banned_at": "2026-11-09T10:00:00+00:00",
                        "expires_at": None, "permanent": True, "bancount": None})
    s["ips"]["195.178.110.159"]["24h"]["paths"] = [{"path": XSS, "count": 2},
                                                   {"path": "/.env", "count": 1}]
    s["ips"]["6.6.6.6"] = {
        "24h": {"requests": 9, "probes": 9, "first_seen": "2026-11-09T11:00:00+00:00",
                "last_seen": "2026-11-09T11:05:00+00:00", "paths": [{"path": "/wp-login.php", "count": 9}]},
        "7d": {"requests": 40, "probes": 30, "first_seen": "2026-11-04T11:00:00+00:00",
               "last_seen": "2026-11-09T11:05:00+00:00", "paths": [{"path": "/wp-login.php", "count": 30}]}}
    s["top"].append({"ip": "6.6.6.6", "probes_24h": 9, "probes_7d": 30, "requests_7d": 40,
                     "last_seen": "2026-11-09T11:05:00+00:00", "banned": False})
    s["top"].append({"ip": "80.94.95.211", "probes_24h": 0, "probes_7d": 2, "requests_7d": 7,
                     "last_seen": "2026-11-05T21:40:52+00:00", "banned": False})
    s["history"].append({"at": "2026-11-09T09:00:00+00:00", "event": "unban", "jail": "sshd",
                         "ip": "10.1.1.1"})
    s["totals"]["bans_7d"] = None
    return s


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    d = tmp_path_factory.mktemp("secb")
    db = d / "s.db"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "dev_seed.py"), str(db)],
                   check=True, cwd=ROOT, capture_output=True)
    (d / "security").mkdir()
    (d / "security" / "snapshot.json").write_text(json.dumps(_data(time.time())), encoding="utf-8")
    os.environ["ADMIN_TOKEN"] = TOKEN
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
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    t.join(5)
    os.environ.pop("ADMIN_TOKEN", None)


def _open(browser, base, w, h, theme, route=None):
    ctx = browser.new_context(viewport={"width": w, "height": h}, service_workers="block")
    ctx.add_init_script(f"localStorage.setItem('tabela.theme', '{theme}');")
    if route:
        ctx.route("**/api/admin/security", route)
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(base + "/#admin")
    page.fill("#admin-token", TOKEN)
    page.click(".admin-login button[type=submit]")
    page.wait_for_selector("#admin-security")
    return ctx, page, errors


def _shot(page, name):
    out = os.environ.get("SEC_SHOTS")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        page.locator("#admin-security").screenshot(path=str(Path(out) / f"{name}.png"))


def _rows(page, box):
    return page.eval_on_selector_all(
        f"#{box} tbody tr", "rs => rs.map(r => Array.from(r.cells).map(c => c.textContent))")


@pytest.mark.parametrize("w,h,theme", [(1280, 900, "dark"), (390, 844, "light")])
def test_security_card(browser, server, w, h, theme):
    ctx, page, errors = _open(browser, server, w, h, theme)
    page.wait_for_selector("#admin-sec-banned tbody tr")
    _shot(page, f"securitate-{w}-{theme}")

    meta = page.text_content("#admin-sec-meta")
    assert "Actualizat acum 2 min" in meta and "ora României" in meta
    summary = page.text_content("#admin-sec-summary")
    assert "Banați acum" in summary and "Cereri-probă 24 h" in summary and "554" in summary
    # bans_7d lipsește în snapshot -> „—", nu 0
    stat7 = page.eval_on_selector_all(
        "#admin-sec-summary .admin-stat",
        "els => els.filter(e => e.querySelector('dt').textContent === 'Ban-uri 7 zile')"
        ".map(e => e.querySelector('dd').textContent)")
    assert stat7 == ["—"]

    banned = _rows(page, "admin-sec-banned")
    assert len(banned) == 2
    first = next(r for r in banned if r[0] == "195.178.110.159")
    assert "19:10:14" in first[2]                     # 17:10:14 UTC = 19:10:14 ora României
    assert first[4] == "1" and first[5] == "4" and first[6] == "3"
    assert XSS in first[7]                            # calea ostilă, ca text
    other = next(r for r in banned if r[0] == "203.0.113.9")
    assert other[3] == "permanent" and other[4] == "—" and other[5] == "—" and other[6] == "—"
    assert "ora României" in page.text_content("#admin-sec-banned thead")
    assert "(N = 2)" in page.text_content("#admin-security")

    assert page.evaluate("window.__xss") is None
    assert page.locator("#admin-security img").count() == 0

    hist = _rows(page, "admin-sec-history")
    assert [r[1] for r in hist] == ["Ban", "Unban"]

    # fereastra 7 zile schimbă numerele din tabele
    page.select_option("#admin-sec-window", "7d")
    first7 = next(r for r in _rows(page, "admin-sec-banned") if r[0] == "195.178.110.159")
    assert first7[5] == "5" and first7[6] == "4"

    # sortare: top după cereri-probă (implicit descrescător), apoi crescător la click
    top = [r[0] for r in _rows(page, "admin-sec-top")]
    assert top == ["6.6.6.6", "195.178.110.159", "80.94.95.211"]
    page.select_option("#admin-sec-window", "24h")   # fără probe în 24 h -> nu e în top-ul 24 h
    assert [r[0] for r in _rows(page, "admin-sec-top")] == ["6.6.6.6", "195.178.110.159"]
    assert "(N = 2)" in page.text_content("#admin-sec-top-h")
    page.select_option("#admin-sec-window", "7d")
    page.click("#admin-sec-top th:nth-child(2) button")
    top = [r[0] for r in _rows(page, "admin-sec-top")]
    th = page.get_attribute("#admin-sec-top th:nth-child(2)", "aria-sort")
    assert th in ("ascending", "descending")
    assert top == (["80.94.95.211", "195.178.110.159", "6.6.6.6"] if th == "ascending"
                   else ["6.6.6.6", "195.178.110.159", "80.94.95.211"])
    page.click("#admin-sec-top th:nth-child(2) button")
    assert page.get_attribute("#admin-sec-top th:nth-child(2)", "aria-sort") != th

    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
    assert not errors, errors
    ctx.close()


@pytest.mark.parametrize("payload,text", [
    ({"available": False, "reason": "missing"}, "nu a scris încă"),
    ({"available": False, "reason": "stale", "stale": True, "age_s": 3720,
      "generated_at": "2026-11-09T10:00:00+00:00"}, "acum 62 min"),
    ({"available": False, "reason": "invalid"}, "invalid"),
])
def test_security_card_unavailable(browser, server, payload, text):
    def route(r):
        r.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
    ctx, page, errors = _open(browser, server, 390, 844, "dark", route)
    page.wait_for_function("document.querySelector('#admin-sec-meta').textContent.length > 0")
    meta = page.text_content("#admin-sec-meta")
    assert text in meta, meta
    assert page.locator("#admin-sec-banned tbody tr").count() == 0
    assert not errors, errors
    ctx.close()


def test_security_card_fail2ban_missing(browser, server):
    data = snapshot(time.time(), generated_ts=time.time() - 30)
    data.update({"available": True, "stale": False, "age_s": 30, "banned": [], "history": [],
                 "fail2ban": {"available": False, "log_available": False, "jails": []}})
    data["totals"].update({"banned_now": None, "bans_24h": None, "bans_7d": None})

    def route(r):
        r.fulfill(status=200, content_type="application/json", body=json.dumps(data))
    ctx, page, errors = _open(browser, server, 1280, 900, "light", route)
    page.wait_for_selector("#admin-sec-summary .admin-stat")
    assert "fail2ban indisponibil" in page.text_content("#admin-security")
    assert "Actualizat acum 30 s" in page.text_content("#admin-sec-meta")
    assert not errors, errors
    ctx.close()
