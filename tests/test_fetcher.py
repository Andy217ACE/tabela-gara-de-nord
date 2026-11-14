# © 2026 Andy217Ace
import base64
import re
from pathlib import Path

import httpx
import pytest

from app.fetcher import MAX_BYTES, FetchError, extract_image, fetch_board_image, image_hash

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


def _truncated_page(keep: int) -> str:
    from app.fetcher import _DATA_URI
    html = _page()
    m = _DATA_URI.search(html)
    full = base64.b64decode(re.sub(r"\s+", "", m.group(1)))
    cut = base64.b64encode(full[:keep]).decode()
    return html.replace(m.group(1), cut)


def test_extract_image_rejects_truncated_jpeg():
    with pytest.raises(ValueError, match="truncated"):
        extract_image(_truncated_page(8192))


async def test_fetch_truncated_jpeg_is_fetch_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=_truncated_page(16384)))
    async with httpx.AsyncClient(transport=transport) as c:
        with pytest.raises(FetchError):
            await fetch_board_image(c, "http://x/")


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
        "(c) 2026 Andy217Ace; date CFR)"
    )
    assert seen["ua"].isascii()


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


async def test_fetch_rejects_oversized_response():
    big = b"x" * (MAX_BYTES + 1)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=big))
    async with httpx.AsyncClient(transport=transport) as c:
        with pytest.raises(FetchError, match="too large"):
            await fetch_board_image(c, "http://x/")


async def test_fetch_rejects_oversized_chunked_response():
    async def gen():
        for _ in range(MAX_BYTES // 65536 + 2):
            yield b"x" * 65536

    transport = httpx.MockTransport(lambda r: httpx.Response(200, content=gen()))
    async with httpx.AsyncClient(transport=transport) as c:
        with pytest.raises(FetchError, match="too large"):
            await fetch_board_image(c, "http://x/")


async def test_fetch_invalid_base64_is_fetch_error():
    html = '<img src="data:image/jpeg;base64,/9j/4AAQ=A=A">'
    transport = httpx.MockTransport(lambda r: httpx.Response(200, text=html))
    async with httpx.AsyncClient(transport=transport) as c:
        with pytest.raises(FetchError, match="base64"):
            await fetch_board_image(c, "http://x/")


async def test_fetch_redirect_response_is_fetch_error():
    transport = httpx.MockTransport(
        lambda r: httpx.Response(302, headers={"location": "http://y/"}, text=_page()))
    async with httpx.AsyncClient(transport=transport) as c:
        with pytest.raises(FetchError, match="HTTP 302"):
            await fetch_board_image(c, "http://x/")
