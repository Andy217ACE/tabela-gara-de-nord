# © 2026 Andy217Ace
"""Canonical operator / station names for noisy OCR text (difflib fuzzy match).

A reading is mapped to the closest known name when the similarity ratio reaches
the threshold (operators: or a softer score with a clear margin, see `operator_match`);
otherwise the cleaned raw text is returned together with its best
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
# Measured on 823,912 live readings vs each train number's stable operator: >=0.82 is 99.9999%
# right; 0.65-0.82 with a margin >=0.10 over the runner-up operator is 100% of 1,626 (99.3%
# without the margin; <=93% below 0.65).
OPERATOR_SOFT_THRESHOLD = 0.65
OPERATOR_MARGIN = 0.10
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
def _operator_table() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """(official name, aliases) per line of ``Official | alias | alias``."""
    out = []
    for ln in _load("operators.txt"):
        official, *aliases = (p.strip() for p in ln.split("|"))
        out.append((official, tuple(a for a in aliases if a)))
    return tuple(out)


def known_operators() -> tuple[str, ...]:
    """The official operator names."""
    return tuple(o for o, _ in _operator_table())


@lru_cache(maxsize=1)
def operator_keys() -> tuple[tuple[str, str], ...]:
    """(match key text, official name): the official name and every board alias."""
    return tuple((k, o) for o, al in _operator_table() for k in (o, *al))


@lru_cache(maxsize=1)
def seed_stations() -> frozenset[str]:
    return frozenset(clean_station(s) for s in _load("stations_seed.txt"))


@lru_cache(maxsize=1)
def station_names() -> dict[str, str]:
    """Stored key (board form, ASCII upper case) -> display name, ``data/stations.txt``.

    Display only: keys stay what is stored and used in URLs, stats and exports.
    """
    out = {}
    for ln in _load("stations.txt"):
        key, _, name = (p.strip() for p in ln.partition("|"))
        if clean_station(key) and name:
            out[clean_station(key)] = name
    return out


@lru_cache(maxsize=1)
def _display_keys() -> dict[str, str]:
    return {_loose(clean_station(n)): k for k, n in station_names().items()}


def _loose(s: str) -> str:
    """Hyphens count as spaces, so "Cluj-Napoca" finds the CFR form "Cluj Napoca"."""
    return " ".join(s.replace("-", " ").split())


def station_key(text: str | None) -> str:
    """The stored key for a key or a display name ("Brașov", "Cluj-Napoca" -> "CLUJ NAPOCA")."""
    raw = clean_station(text or "")
    return _display_keys().get(_loose(raw), raw)


def stations_matching(text: str | None) -> list[str]:
    """Keys whose display name contains `text`, diacritics/case ignored ("henri" -> airport)."""
    q = _loose(clean_station(text or ""))
    return sorted(k for d, k in _display_keys().items() if q in d) if q else []


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
    PITESTI SUD/PLOIESTI SUD and CRAIOVITA/CRAIOVA; keeps BRASOY->BRASOV and the last
    word cut by one final letter (VATRA DORNEI BA -> VATRA DORNEI BAI)."""
    a, b = k.split(), ck.split()
    if len(a) != len(b):
        return False
    for pos, (wa, wb) in enumerate(zip(a, b)):
        if wa == wb:
            continue
        if (pos == len(a) - 1 and len(a) >= 2 and len(wa) >= 2 and len(wb) == len(wa) + 1
                and wb.startswith(wa)):
            continue  # the last letter of the last word cut off at the cell edge:
            # VATRA DORNEI BA -> VATRA DORNEI BAI (a one-word name is never completed)
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


def operator_match(text: str | None, known: Iterable[str] | None = None,
                   threshold: float = DEFAULT_THRESHOLD) -> tuple[str, float, bool]:
    """(name, score, accepted). The score is per official operator (best over its
    name and aliases), so aliases of one operator never compete for the margin.
    Accepted: score >= threshold, or (built-in list only) score >= OPERATOR_SOFT_THRESHOLD
    with a margin >= OPERATOR_MARGIN over the second-best operator. Not accepted:
    (cleaned raw text, best score)."""
    raw = clean_operator(text)
    k = _key(raw)
    if not k:
        return "", 0.0, False
    pairs = operator_keys() if known is None else tuple((c, c) for c in known)
    per: dict[str, float] = {}
    for cand, official in pairs:
        ck = _key(cand)
        if not ck:
            continue
        sc = 1.0 if ck == k else difflib.SequenceMatcher(None, k, ck).ratio()
        if sc > per.get(official, 0.0):
            per[official] = sc
    ranked = sorted(per.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked:
        return raw, 0.0, False
    (name, score), second = ranked[0], (ranked[1][1] if len(ranked) > 1 else 0.0)
    if score >= threshold or (known is None and score >= OPERATOR_SOFT_THRESHOLD
                              and score - second >= OPERATOR_MARGIN):
        return name, score, True
    return raw, score, False


def canonical_operator(text: str | None, known: Iterable[str] | None = None,
                       threshold: float = DEFAULT_THRESHOLD) -> tuple[str, float]:
    """(official name, score); not accepted: (cleaned raw text, best score)."""
    name, score, _ = operator_match(text, known, threshold)
    return name, score


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
