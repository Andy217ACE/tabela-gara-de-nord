# © 2026 Andy217Ace
import base64
from pathlib import Path

import httpx
import pytest

from app.fetcher import FetchError, extract_image, fetch_board_image, image_hash

FIX = Path(__file__).parent / "fixtures"


def _page() -> str:
    return (FIX / "page_1.html").read_text(encoding="utf-8")


def test_extract_image_jpeg():
    data = extract_image(_page())
    assert data.startswith(b"\xff\xd8")
    assert len(data) > 10_000


def test_extract_image_missing():
    with pytest.raises(ValueError):
        extract_image("<html><body>nimic</body></html>")


def test_extract_image_not_an_image():
    payload = base64.b64encode(b"hello world, not an image").decode()
    with pytest.raises(ValueError):
        extract_image(f'<img src="data:image/jpeg;base64,{payload}">')


def test_extract_image_png():
    raw = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    payload = base64.b64encode(raw).decode()
    assert extract_image(f'<img src="data:image/png;base64,{payload}">') == raw


def test_image_hash():
    assert image_hash(b"abc") == "a9993e364706816aba3e25717850c26c9cd0d89d"


async def test_fetch_ok_and_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, text=_page())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        data = await fetch_board_image(c, "http://x/")
    assert data.startswith(b"\xff\xd8")
    assert seen["ua"] == (
        "tabela-gara-de-nord/1.0 (+https://github.com/Andy217Ace/tabela-gara-de-nord; "
        "© 2026 Andy217Ace; date CFR)"
    )


async def test_fetch_status_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(500))
    async with httpx.AsyncClient(transport=transport) as c:
        with pytest.raises(FetchError):
            await fetch_board_image(c, "http://x/")


async def test_fetch_transport_error():
    def handler(request):
        raise httpx.RemoteProtocolError("closed without response")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(FetchError):
            await fetch_board_image(c, "http://x/")


async def test_fetch_page_without_image():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text="<html></html>"))
    async with httpx.AsyncClient(transport=transport) as c:
        with pytest.raises(FetchError):
            await fetch_board_image(c, "http://x/")
