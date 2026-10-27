# © 2026 Andy217Ace
"""Cells hit by glare / the board's own arrow glyph: what can be completed, and what not.

Live audit 27.10 (Beta 1.25): a white blob (the clock reflected in the glass, or the arrow
the board draws over a delay cell when the train gets its platform) covers

- the "+" and the first digit of the delay of the first arrival line ("+15" shows as
  "[blob]5"; 399 of 407 glare-rejected delay cells of the history are on line 0), and
- the colon of a scheduled time ("7:37" shows as "7[blob]37"), which left the whole line
  unread: no train, and the train missing from the board.

The pixels under a blob are gone, so nothing here reads them back. What can be said safely:

``time_candidates``  the times a glyph sequence leaves possible: every trusted glyph is
                     kept, a glyph the templates do not trust is a wildcard (the colon
                     slot may hold any glyph: the blob), at most one wildcard digit.
``pick_time``        the candidate that the neighbouring lines' times (the panel is in
                     chronological order, see ``order.py``) and the train's earlier
                     readings leave: exactly one, otherwise None (never a guess).
``delay_tail``       the units digit of a delay cell that both readers agree on, used by
                     ``DelayVotes`` to confirm that a glared cell still shows the delay the
                     train had in the frames before (the tens digit under the blob is not
                     read: "+15" gave 45 / 75 / 465 / 85).
"""
from __future__ import annotations

from collections.abc import Sequence

from app.normalize import parse_time
from app.ocr import digits

DAY = 1440
FILLED = "glare_filled"  # fields.time.check of a time completed from its surroundings
MAX_WILDCARDS = 1   # untrusted digit glyphs a candidate may stand on
MIN_TRUSTED = 2     # trusted digit glyphs a candidate needs
# a glyph cut out of a blob fused with its neighbours is trusted only on a clear match
# (glare: "+45" gave "1" at 0.78 / margin 0.041)
FUSED_MIN_SCORE = 0.80
FUSED_MIN_MARGIN = 0.10

# a glyph the template matcher saw: (character, trusted)
Glyph = tuple[str, bool]


def glyph_flags(raw: Sequence[tuple]) -> list[Glyph]:
    """(character, trusted) of each ``DigitMatcher.glyphs`` item: a glyph cut out of a fused
    blob needs the stricter score (reader.FUSED_MIN_*), like for the delay."""
    out = []
    for ch, score, margin, _g, fused in raw:
        ok = digits.glyph_trusted(score, margin) and (
            not fused or (score >= FUSED_MIN_SCORE and margin >= FUSED_MIN_MARGIN))
        out.append((ch, ok))
    return out


def _fill(slots: Sequence[Glyph], fmt: str) -> dict[str, int]:
    """{"HH:MM": wildcard digits used} for the digit slots: every trusted glyph is kept, an
    untrusted one (at most MAX_WILDCARDS) takes each digit in turn; `fmt` places the digits
    ("{}:{}{}" for H:MM, "{}{}:{}{}" for HH:MM)."""
    fixed: list[str | None] = []
    for ch, ok in slots:
        if ok and not ch.isdigit():
            return {}
        fixed.append(ch if ok else None)
    holes = [k for k, c in enumerate(fixed) if c is None]
    if len(holes) > MAX_WILDCARDS or len(slots) - len(holes) < MIN_TRUSTED:
        return {}
    out: dict[str, int] = {}
    for d in ("0123456789" if holes else [""]):
        digs = list(fixed)
        if holes:
            digs[holes[0]] = d
        t = parse_time(fmt.format(*digs))
        if t is not None:
            out[t] = len(holes)
    return out


def time_candidates(glyphs: Sequence[Glyph]) -> dict[str, int]:
    """{"HH:MM": wildcard digits used} of the times the glyphs allow.

    The board prints "H:MM" or "HH:MM". Layouts tried: the colon is a glyph (its slot may
    hold anything the templates do not trust: the blob that hides it, or a real colon) or
    it was dropped by the segmentation. A trusted digit in the colon slot rules that layout
    out."""
    n = len(glyphs)
    g = list(glyphs)

    def colon_ok(k: int) -> bool:
        return not g[k][1] or g[k][0] == ":"

    runs: list[tuple[list[Glyph], str]] = []
    if n == 4:
        if colon_ok(1):
            runs.append(([g[0], g[2], g[3]], "{}:{}{}"))   # H:MM, colon is a glyph
        runs.append((g, "{}{}:{}{}"))                      # HHMM, colon dropped
    elif n == 5 and colon_ok(2):
        runs.append(([g[0], g[1], g[3], g[4]], "{}{}:{}{}"))  # HH:MM
    elif n == 3:
        runs.append((g, "{}:{}{}"))                        # H:MM, colon dropped
    found: dict[str, int] = {}
    for slots, fmt in runs:
        for t, w in _fill(slots, fmt).items():
            found[t] = min(w, found.get(t, w))
    return found


def minutes(t: str) -> int:
    return int(t[:2]) * 60 + int(t[3:])


def fits(t: str, lo: str | None, hi: str | None) -> bool:
    """`t` lies between the times of the nearest lines above (`lo`) and below (`hi`) it on
    the panel (the order is chronological, wrapping once at midnight; the same arithmetic
    as ``order._repair``)."""
    m = minutes(t)
    if lo is not None and (m - minutes(lo)) % DAY > DAY // 2:
        return False
    if hi is not None and (minutes(hi) - m) % DAY > DAY // 2:
        return False
    if lo is not None and hi is not None and (m - minutes(lo)) % DAY > (
            minutes(hi) - minutes(lo)) % DAY:
        return False
    return True


def pick_time(cands: dict[str, int], lo: str | None, hi: str | None,
              hint: str | None = None) -> str | None:
    """The one time the evidence leaves, or None.

    - `hint`: the time the train showed unanimously in the last frames. If the glyphs allow
      it and the neighbours do not contradict it, it is the answer; a different unique
      candidate is a contradiction, so no answer.
    - without a hint the candidate must be unique after the neighbour bounds, and stand on
      no wildcard digit unless BOTH neighbours bound it (only a hidden colon is free).
    """
    adm = [t for t in cands if fits(t, lo, hi)]
    if hint is not None:
        if hint in adm and len(adm) == 1:
            return hint
        return hint if hint in adm and all(
            cands[t] > 0 for t in adm if t != hint) else None
    if len(adm) != 1:
        return None
    t = adm[0]
    if cands[t] > 0 and (lo is None or hi is None):
        return None
    return t


def delay_tail(raw: Sequence[tuple], t_text: str) -> str | None:
    """Units digit ("0" or "5": the board counts delays in 5-minute steps) of a delay cell
    when the last glyph is a trusted digit (a clear match if it was cut out of a fused
    blob) and Tesseract's last character is the same. None otherwise."""
    flags = glyph_flags(raw)
    if len(flags) < 2:
        return None
    ch, ok = flags[-1]
    t = (t_text or "").replace(" ", "")
    if ok and ch in "05" and t and t[-1] == ch:
        return ch
    return None
