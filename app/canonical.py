# © 2026 Andy217Ace
"""Canonical operator / station names for noisy OCR text (difflib fuzzy match).

A reading is mapped to the closest known name when the similarity ratio reaches
the threshold; below it the cleaned raw text is returned together with its best
score so the caller can mark the value as uncertain. Nothing is invented: the
known lists hold only names actually seen on the board (``data/*.txt``) plus the
stations learned from the stored history.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from app.normalize import clean_station

DEFAULT_THRESHOLD = 0.82
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def _key(s: str) -> str:
    """Comparison key: ASCII, lower case, letters/digits/single spaces only."""
    s = re.sub(r"[^a-z0-9 ]+", "", _fold(s).lower())
    return re.sub(r"\s+", " ", s).strip()


def clean_operator(s: str | None) -> str:
    s = re.sub(r"\s+", " ", _fold(s or ""))
    return s.strip(" .,;:|_-")


def _load(name: str) -> tuple[str, ...]:
    try:
        lines = (DATA_DIR / name).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    return tuple(ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#"))


@lru_cache(maxsize=1)
def known_operators() -> tuple[str, ...]:
    return _load("operators.txt")


@lru_cache(maxsize=1)
def seed_stations() -> frozenset[str]:
    return frozenset(clean_station(s) for s in _load("stations_seed.txt"))


def _lev(a: str, b: str) -> int:
    """Levenshtein distance (short strings only)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def near_name(a: str, b: str) -> bool:
    """Are station names `a` and `b` (clean_station form) one OCR slip apart? Same
    letters with spaces moved ("AD JUD"/"ADJUD"), a stray one-character token
    ("RUSE I"/"RUSE"), or within 1 edit (names up to 6
    letters) / 2 edits (longer names). Used to keep misreads out of the learned list."""
    ka, kb = _key(a), _key(b)
    if ka.replace(" ", "") == kb.replace(" ", ""):
        return True
    wa, wb = re.split(r"[\s-]+", (a or "").upper()), re.split(r"[\s-]+", (b or "").upper())
    if sorted(w for w in wa if w) == sorted(w for w in wb if w):  # "KIEV - CHISINAU"
        return True
    for x, y in ((ka, kb), (kb, ka)):  # a stray one-character token: "RUSE I" / RUSE
        w = x.split()
        if len(w) >= 2 and len(w[-1]) == 1 and " ".join(w[:-1]) == y:
            return True
    return _lev(ka, kb) <= (1 if min(len(ka), len(kb)) <= 6 else 2)


SPACING_SCORE = 0.95  # same letters, spaces misplaced: "AD JUD", "PLOIESTISUD", "CHISINAU -KIEV"
TAIL_SCORE = 0.9  # a stray one-character token after an exact name: "ARAD E", "RUSE I"


def _same_words(k: str, ck: str) -> bool:
    """Could `k` be an OCR misread of `ck`? OCR noise substitutes characters inside the
    words; it does not add or drop whole words or change a word into another one.
    So: same number of words, and each word differs by at most one edit per 5 letters
    with the same length (one extra/missing letter only in words of 6+ letters).
    Rejects VATRA DORNEI/VATRA DORNEI BAI, CLUJ NAPOCA EST/CLUJ NAPOCA,
    PITESTI SUD/PLOIESTI SUD and CRAIOVITA/CRAIOVA; keeps BRASOY->BRASOV."""
    a, b = k.split(), ck.split()
    if len(a) != len(b):
        return False
    for wa, wb in zip(a, b):
        if wa == wb:
            continue
        diff = abs(len(wa) - len(wb))
        if diff > 1 or (diff == 1 and min(len(wa), len(wb)) < 6):
            return False
        if _lev(wa, wb) > max(1, min(len(wa), len(wb)) // 5):
            return False
    return True


def _best(text: str, known: Iterable[str], words: bool = False) -> tuple[str | None, float]:
    k = _key(text)
    best, best_score = None, 0.0
    for cand in known:
        ck = _key(cand)
        if not ck:
            continue
        if ck == k:
            score = 1.0
        elif words and k.replace(" ", "") == ck.replace(" ", ""):
            score = SPACING_SCORE
        elif words and len(k.split()) >= 2 and len(k.split()[-1]) == 1                 and " ".join(k.split()[:-1]) == ck:
            score = TAIL_SCORE
        elif words and not _same_words(k, ck):
            continue  # a genuinely different name, not a misread of this one
        else:
            score = difflib.SequenceMatcher(None, k, ck).ratio()
        if score > best_score or (score == best_score and best is not None and cand < best):
            best, best_score = cand, score
    return best, best_score


def canonical_operator(text: str | None, known: Iterable[str] | None = None,
                       threshold: float = DEFAULT_THRESHOLD) -> tuple[str, float]:
    """(canonical name, score); below `threshold`: (cleaned raw text, best score)."""
    raw = clean_operator(text)
    if not _key(raw):
        return "", 0.0
    match, score = _best(raw, known_operators() if known is None else known)
    if match is not None and score >= threshold:
        return match, score
    return raw, score


def canonical_station(text: str | None, known: Iterable[str], *,
                      preferred: Iterable[str] | None = None,
                      threshold: float = DEFAULT_THRESHOLD) -> tuple[str, float]:
    """(known station, score); below `threshold`: (cleaned raw text, best score).

    Fuzzy matches are limited to in-word OCR noise (`_same_words`); any score below
    1.0 means the name was corrected and the caller must mark the row uncertain.

    `preferred` (the curated seed) is tried first, so a misread that slipped into
    the learned history ("BRASOY") still resolves to the curated name ("BRASOV").
    """
    raw = clean_station(text or "")
    if not raw:
        return "", 0.0
    known = set(known)
    if preferred:
        preferred = set(preferred)
        match, score = _best(raw, preferred, words=True)
        if match is not None and score >= threshold:
            return match, score
        known |= preferred
    match, score = _best(raw, known, words=True)
    if match is not None and score >= threshold:
        return match, score
    return raw, min(score, 0.999)  # kept as read: never "exact"
