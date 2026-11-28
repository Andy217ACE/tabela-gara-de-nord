# © 2026 Andy217Ace
"""?lang=en: the static head is served in English (link previews, crawlers without JS)."""
import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings

RO_DESC = "Sosirile și plecările din Gara de Nord București, actualizate în timp real"


@pytest.fixture
def client():
    s = Settings(db_path=":memory:", source_url="https://example.com/x",
                 vapid_private_key="", vapid_public_key="", vapid_subject="mailto:a@b.c",
                 tesseract_cmd="tesseract")
    with TestClient(create_app(s, start_poller=False)) as c:
        yield c


def _assert_ro(html):
    assert '<html lang="ro">' in html
    assert RO_DESC in html
    assert 'content="ro_RO"' in html
    assert "sosiri și plecări live" in html


@pytest.mark.parametrize("path", ["/?lang=en", "/index.html?lang=en"])
def test_en_head(client, path):
    r = client.get(path)
    assert r.status_code == 200
    h = r.text
    assert '<html lang="en">' in h
    assert '<html lang="ro">' not in h
    assert RO_DESC not in h
    assert 'property="og:locale" content="en_GB"' in h
    assert "arrivals and departures" in h.lower()
    for marker in ('name="description"', 'property="og:title"', 'property="og:description"',
                   'name="twitter:title"', 'name="twitter:description"', "<title>"):
        assert marker in h
    assert "sosiri și plecări live" not in h
    assert "text/html" in r.headers["content-type"]


@pytest.mark.parametrize("path", ["/", "/?lang=ro", "/?lang=fr", "/?lang=", "/index.html"])
def test_ro_head(client, path):
    r = client.get(path)
    assert r.status_code == 200
    _assert_ro(r.text)


def _no_ssr(h):
    """Body without the server-rendered content block (it is localized: app/seo.py)."""
    h = h[h.index("</head>"):]
    return h[:h.index('<section class="ssr"')] + h[h.index("</section>", h.index('<section class="ssr"')):]


def test_body_identical(client):
    ro = client.get("/").text
    en = client.get("/?lang=en").text
    assert _no_ssr(ro) == _no_ssr(en)
