# © 2026 Andy217Ace
"""TOTP (RFC 6238, HMAC-SHA1, 30 s, 6 digits) for the optional admin 2FA. Stdlib only."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import struct

STEP_S = 30
DIGITS = 6
MIN_SECRET_BYTES = 10  # 80 bits; scripts/admin_totp_setup.py generates 20 (160 bits)


def decode_secret(b32: str) -> bytes | None:
    """Base32 secret as authenticator apps show it (spaces, lower case and missing '=' allowed)."""
    s = "".join(b32.split()).upper().rstrip("=")
    try:
        key = base64.b32decode(s + "=" * (-len(s) % 8))
    except (binascii.Error, ValueError):
        return None
    return key if len(key) >= MIN_SECRET_BYTES else None


def code_at(key: bytes, counter: int, digits: int = DIGITS) -> str:
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    n = struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF
    return str(n % 10 ** digits).zfill(digits)


def match(key: bytes, code: str, now: float, after: int = -1) -> int | None:
    """Counter of the step (now ±1 step) whose code equals `code`, only if it is newer than
    `after` (the last accepted counter: replay protection). None otherwise."""
    if not (isinstance(code, str) and len(code) == DIGITS and code.isascii() and code.isdigit()):
        return None
    t = int(now) // STEP_S
    found = None
    for c in (t - 1, t, t + 1):  # no early exit: same work whatever matches
        if hmac.compare_digest(code_at(key, c), code) and c > after and found is None:
            found = c
    return found
