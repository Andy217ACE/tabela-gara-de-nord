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
MAX_BYTES = 10 * 1024 * 1024  # the CFR page embeds the image as base64; refuse anything larger

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
        async with client.stream("GET", url, headers={"User-Agent": USER_AGENT},
                                 timeout=TIMEOUT) as resp:
            if resp.status_code >= 300:  # errors and (unfollowed) redirects
                raise FetchError(f"HTTP {resp.status_code}")
            declared = resp.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > MAX_BYTES:
                raise FetchError("response too large")
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise FetchError("response too large")
                chunks.append(chunk)
            html = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
    except httpx.TransportError as e:
        raise FetchError(f"transport error: {e!r}") from e
    try:
        return extract_image(html)
    except ValueError as e:
        raise FetchError(str(e)) from e
