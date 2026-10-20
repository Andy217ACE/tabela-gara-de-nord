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


def _best(text: str, known: Iterable[str]) -> tuple[str | None, float]:
    k = _key(text)
    best, best_score = None, 0.0
    for cand in known:
        ck = _key(cand)
        if not ck:
            continue
        score = 1.0 if ck == k else difflib.SequenceMatcher(None, k, ck).ratio()
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

    `preferred` (the curated seed) is tried first, so a misread that slipped into
    the learned history ("BRASOY") still resolves to the curated name ("BRASOV").
    """
    raw = clean_station(text or "")
    if not raw:
        return "", 0.0
    known = set(known)
    if preferred:
        preferred = set(preferred)
        match, score = _best(raw, preferred)
        if match is not None and score >= threshold:
            return match, score
        known |= preferred
    match, score = _best(raw, known)
    if match is not None and score >= threshold:
        return match, score
    return raw, score
