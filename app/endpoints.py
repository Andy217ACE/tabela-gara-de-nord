# © 2026 Andy217Ace
"""Validation of Web Push subscription endpoints (SSRF protection).

The server POSTs to whatever endpoint a browser registers, so only the real
push services are accepted (allowlist). A denylist of IP-like / local hosts is
kept as defence in depth. Used by the API and by `Store.subscribe`.

Host matching is case-insensitive (DNS is); a trailing dot is rejected.
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

MAX_ENDPOINT_LEN = 500
INVALID = "Endpoint de notificare invalid."

ALLOWED_HOSTS = frozenset({
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
    "web.push.apple.com",
})
ALLOWED_SUFFIXES = (
    ".push.services.mozilla.com",
    ".notify.windows.com",
    ".push.apple.com",
)

_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_NUMERIC_LABEL = re.compile(r"^(?:0x[0-9a-f]*|\d+)$")
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal")


def _allowed(host: str) -> bool:
    if host in ALLOWED_HOSTS:
        return True
    return any(host.endswith(s) and len(host) > len(s) for s in ALLOWED_SUFFIXES)


def check_push_endpoint(url) -> None:
    """Raise ValueError (Romanian message) unless `url` is an allowed push endpoint.

    Rules: str of at most MAX_ENDPOINT_LEN chars, no whitespace/control chars,
    scheme https, no userinfo, port absent or 443, host a DNS name (no trailing
    dot) on the push-service allowlist.
    """
    if not isinstance(url, str) or not url or len(url) > MAX_ENDPOINT_LEN:
        raise ValueError(INVALID)
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c == "\\" for c in url):
        raise ValueError(INVALID)
    try:
        u = urlsplit(url)
        port = u.port
    except ValueError:
        raise ValueError(INVALID) from None
    if u.scheme != "https" or "@" in u.netloc or u.username is not None \
            or u.password is not None:
        raise ValueError(INVALID)
    if port not in (None, 443):
        raise ValueError(INVALID)
    host = (u.hostname or "").lower()
    if not host or host.endswith("."):
        raise ValueError(INVALID)
    labels = host.split(".")
    if not all(_LABEL.match(lb) for lb in labels):
        raise ValueError(INVALID)
    # Defence in depth (redundant with the allowlist).
    if _NUMERIC_LABEL.match(labels[-1]) or host == "localhost" \
            or host.endswith(_LOCAL_SUFFIXES) or len(labels) < 2:
        raise ValueError(INVALID)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError(INVALID)
    if not _allowed(host):
        raise ValueError(INVALID)
