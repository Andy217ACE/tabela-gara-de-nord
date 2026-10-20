# © 2026 Andy217Ace
from __future__ import annotations

import base64
import binascii
import hashlib
import re

import httpx

USER_AGENT = (
    "tabela-gara-de-nord/1.0 (+https://github.com/Andy217Ace/tabela-gara-de-nord; "
    "(c) 2026 Andy217Ace; date CFR)"
)
TIMEOUT = 15.0

_DATA_URI = re.compile(r"data:image/(?:jpeg|jpg|png);base64,([A-Za-z0-9+/=\s]+)", re.I)


class FetchError(Exception):
    pass


def extract_image(html: str) -> bytes:
    m = _DATA_URI.search(html)
    if not m:
        raise ValueError("no base64 image found in page")
    try:
        data = base64.b64decode(re.sub(r"\s+", "", m.group(1)), validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError("invalid base64 image") from e
    if not (data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG")):
        raise ValueError("image is not a JPEG/PNG")
    return data


def image_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


async def fetch_board_image(client: httpx.AsyncClient, url: str) -> bytes:
    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except httpx.TransportError as e:
        raise FetchError(f"transport error: {e!r}") from e
    if resp.status_code >= 400:
        raise FetchError(f"HTTP {resp.status_code}")
    try:
        return extract_image(resp.text)
    except ValueError as e:
        raise FetchError(str(e)) from e
