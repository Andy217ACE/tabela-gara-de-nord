# © 2026 Andy217Ace
from __future__ import annotations

import re
import unicodedata

# OCR confusions, applied only inside numeric fields.
_OCR_DIGITS = str.maketrans({
    "O": "0", "o": "0", "l": "1", "I": "1", "|": "1", "S": "5", "B": "8",
})
_DIGITLIKE = "0-9OolI|SB"

_TIME_COLON = re.compile(rf"^([{_DIGITLIKE}]{{1,2}})[:.]([{_DIGITLIKE}]{{2}})$")
_TIME_PLAIN = re.compile(rf"^([{_DIGITLIKE}]{{2}})([{_DIGITLIKE}]{{2}})$")
_DELAY = re.compile(rf"^\+?\s*([{_DIGITLIKE}]+)$")
_NUM = re.compile(rf"^[{_DIGITLIKE}]+$")

_TYPES = {"IR", "IRN", "R", "RE", "RM", "IC", "EC", "EN", "D"}
# In train types, I is often misread as l, | or 1; O as 0.
_TYPE_FIX = str.maketrans({"l": "I", "|": "I", "1": "I", "0": "O"})


def _digits(s: str) -> str:
    return s.translate(_OCR_DIGITS)


def parse_time(s: str) -> str | None:
    s = (s or "").strip()
    m = _TIME_COLON.match(s) or _TIME_PLAIN.match(s)
    if not m:
        return None
    h, mi = int(_digits(m.group(1))), int(_digits(m.group(2)))
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


MAX_DELAY = 999


def parse_delay(s: str | None) -> int | None:
    """Minutes of delay in a board cell.

    An EMPTY cell is how the CFR board shows an on-time train: that is a reading, 0.
    Anything else that is not a plausible number (letter noise such as "SOS", a lone
    "+", more than MAX_DELAY) is NOT a reading: None, so it is never shown as 0/"la timp".
    """
    s = (s or "").strip()
    if not s:
        return 0
    m = _DELAY.match(s)
    # Require at least one real digit: letter-only noise ("SOS") is not a delay.
    if not m or not any(c.isdigit() for c in m.group(1)):
        return None
    n = int(_digits(m.group(1)))
    return n if n <= MAX_DELAY else None


def parse_platform(s: str) -> int | None:
    s = (s or "").strip()
    if not _NUM.match(s):
        return None
    n = int(_digits(s))
    return n if 1 <= n <= 30 else None


def normalize_type(s: str) -> str | None:
    t = (s or "").strip().translate(_TYPE_FIX).upper()
    return t if t in _TYPES else None


def strip_flag(s: str) -> tuple[str, bool]:
    s = (s or "").strip()
    flagged = s.startswith("*") or s.endswith("*")
    return s.strip("* \t"), flagged


def clean_station(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"^[^A-Z0-9]+|[^A-Z0-9]+$", "", s)
