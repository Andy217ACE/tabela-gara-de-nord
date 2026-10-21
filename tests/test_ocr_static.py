# © 2026 Andy217Ace
"""Static checks for the „Capturi OCR" view, SW pass-through and nginx admin limits."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


@pytest.fixture
def client():
    s = Settings(db_path=":memory:", source_url="https://example.com/x", vapid_private_key="",
                 vapid_public_key="", vapid_subject="mailto:a@b.c", tesseract_cmd="tesseract")
    with TestClient(create_app(s, start_poller=False)) as c:
        yield c


def test_ocr_js_served_and_safe(client):
    r = client.get("/ocr.js")
    assert r.status_code == 200
    js = r.text
    assert js.startswith("// © 2026 Andy217Ace")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(",
                "new Function", ".style.", "setAttribute(\"style\"", "cssText"):
        assert bad not in js, bad
    assert "/api/admin/" in js and "credentials" in js
    assert "TabelaApp.views.ocr" in js
    assert "Capturi OCR" in js


def test_ocr_css_served_and_themed(client):
    r = client.get("/ocr.css")
    assert r.status_code == 200
    css = r.text
    assert css.startswith("/* © 2026 Andy217Ace */")
    assert "var(--surface)" in css and "var(--bad)" in css  # theme tokens, no fixed palette
    assert "@import" not in css and "url(" not in css


def test_ocr_view_not_in_public_nav_and_lazy():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "ocr.js" not in html and "ocr.css" not in html and "#ocr" not in html
    app = (WEB / "app.js").read_text(encoding="utf-8")
    assert '"#ocr": "ocr"' in app and 's.src = "ocr.js"' in app and 'css.href = "ocr.css"' in app


def test_sw_never_caches_admin():
    sw = (WEB / "sw.js").read_text(encoding="utf-8")
    assert 'if (url.pathname.indexOf("/api/") === 0) return; // never cached' in sw
    shell = sw[sw.index("var SHELL"):sw.index("];", sw.index("var SHELL"))]
    assert "ocr" not in shell


def test_nginx_admin_login_rate_limited_and_certbot_untouched():
    conf = (ROOT / "deploy" / "nginx-tabela.conf").read_text(encoding="utf-8")
    limits = (ROOT / "deploy" / "tabela-limits.conf").read_text(encoding="utf-8")
    assert re.search(r"limit_req_zone \$binary_remote_addr zone=tabela_admin_login:\S+ rate=5r/m;",
                     limits)
    block = conf[conf.index("location = /api/admin/login"):]
    block = block[:block.index("}")]
    assert "limit_req zone=tabela_admin_login burst=5 nodelay;" in block
    assert conf.count("# managed by Certbot") == 8  # unchanged
    assert conf.index("location = /api/admin/login") < conf.index("location /api/ {")


def test_admin_responses_not_cached_header(client, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    r = client.get("/api/admin/captures")
    assert r.status_code == 503 and "no-store" in r.headers["cache-control"]
