# © 2026 Andy217Ace
"""Predicția peronului (Val 5b, peron): o estimare etichetată, nu o citire.

Ce prezice: peronul pe care apare un serviciu (tren + stație + bord + dată), din
observații validate (``validation_state = 'ok'``) cu peron citit. Nu scrie nimic în baza
de date (``load_cases`` doar citește). Spec: docs/superpowers/specs/2026-11-05-val5-peron-design.md.

Ierarhia (primul nivel care trece ambii pragi: n și peron dominant):
  (a) tren + stație + bord, ultimele WINDOW_DAYS zile strict anterioare, n >= MIN_N_A;
  (b) stație + bord + oră programată (bucket 1h) + zi a săptămânii, n >= MIN_N_B.
Peronul dominant trebuie să aibă cel puțin MIN_SHARE_PCT % din citiri (inclusiv).
Sub prag: fără predicție (``Pool.predict`` întoarce None).

Zgomotul OCR (5↔6, 3↔8) nu se corectează: se măsoară în backtest.

Poarta de publicare (``gate``): publicat doar dacă backtestul (``walk_forward``) are
cel puțin MIN_BACKTEST_N predicții, acuratețea predicțiilor >= MIN_ACC, iar acuratețea
pe cazurile comune cu linia de bază depășește linia de bază cu cel puțin MIN_LIFT puncte.
"""
from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from app import quality as dq

MIN_N_A = 5  # n minim pe grupă, nivelul (a)
MIN_N_B = 20  # n minim pe grupă, nivelul (b)
WINDOW_DAYS = 60  # fereastra nivelului (a)
MIN_SHARE_PCT = 60  # peronul dominant: cel puțin 60% din citiri (inclusiv)
MIN_BACKTEST_N = 100  # predicții evaluate, înainte de orice publicare
MIN_ACC = 80.0  # acuratețea predicțiilor, procente
MIN_LIFT = 5.0  # puncte peste linia de bază „ultimul peron citit”
CONFUSION_PAIRS = (frozenset({5, 6}), frozenset({3, 8}))  # confuzii OCR, doar numărate


@dataclass(frozen=True)
class Case:
    """Un serviciu cu peronul lui adevărat (modal din citirile valide)."""
    service_id: int
    service_date: str  # YYYY-MM-DD
    train_no: int
    station: str
    board: str
    sched_time: str  # HH:MM
    platform: int


@dataclass(frozen=True)
class Prediction:
    platform: int
    n: int  # citiri (servicii) în grupa care a decis
    share: float  # cota peronului dominant în grupă, 0..1
    basis: str  # "a" | "b"


@dataclass(frozen=True)
class Evaluation:
    service_id: int
    service_date: str
    truth: int
    prediction: Prediction | None
    baseline: int | None


@dataclass(frozen=True)
class Gate:
    published: bool
    reason: str


def _hour(sched_time: str) -> int:
    return int(sched_time.split(":")[0])


def _weekday(service_date: str) -> int:
    return date.fromisoformat(service_date).weekday()


def _top(vals: list[int], min_n: int) -> tuple[int, int, float] | None:
    """(peron dominant, n, cota) dacă grupa are n >= min_n și un dominant de >= MIN_SHARE_PCT %."""
    n = len(vals)
    if n < min_n:
        return None
    ranked = Counter(vals).most_common(2)
    platform, top = ranked[0]
    if len(ranked) > 1 and ranked[1][1] == top:  # egalitate: nu există dominant
        return None
    if top * 100 < MIN_SHARE_PCT * n:
        return None
    return platform, n, top / n


class Pool:
    """Istoricul servicilor deja văzute. ``add`` și ``predict``/``baseline`` nu scriu nimic
    în afară de acest istoric în memorie."""

    def __init__(self) -> None:
        self._a: dict[tuple, list[tuple[date, int]]] = defaultdict(list)
        self._b: dict[tuple, list[tuple[date, int]]] = defaultdict(list)
        self._last: dict[tuple, list[tuple[date, int]]] = defaultdict(list)

    def add(self, c: Case) -> None:
        d = date.fromisoformat(c.service_date)
        self._a[(c.train_no, c.station, c.board)].append((d, c.platform))
        self._b[(c.station, c.board, _hour(c.sched_time), _weekday(c.service_date))].append(
            (d, c.platform))
        self._last[(c.train_no, c.station, c.board)].append((d, c.platform))

    def predict(self, c: Case) -> Prediction | None:
        d = date.fromisoformat(c.service_date)
        lo = d - timedelta(days=WINDOW_DAYS)
        vals_a = [p for (dd, p) in self._a.get((c.train_no, c.station, c.board), [])
                  if lo <= dd < d]
        hit = _top(vals_a, MIN_N_A)
        if hit:
            return Prediction(hit[0], hit[1], hit[2], "a")
        kb = (c.station, c.board, _hour(c.sched_time), _weekday(c.service_date))
        vals_b = [p for (dd, p) in self._b.get(kb, []) if dd < d]
        hit = _top(vals_b, MIN_N_B)
        if hit:
            return Prediction(hit[0], hit[1], hit[2], "b")
        return None

    def baseline(self, c: Case) -> int | None:
        """Ultimul peron citit pentru același tren, stație și bord, dintr-o zi anterioară."""
        d = date.fromisoformat(c.service_date)
        best: tuple[date, int] | None = None
        for dd, p in self._last.get((c.train_no, c.station, c.board), []):
            if dd < d and (best is None or dd >= best[0]):
                best = (dd, p)
        return best[1] if best else None


def build_pool(cases: list[Case]) -> Pool:
    pool = Pool()
    for c in cases:
        pool.add(c)
    return pool


def walk_forward(cases: list[Case]) -> list[Evaluation]:
    """Backtest temporal: predicțiile zilei t folosesc doar zile strict anterioare lui t."""
    by_day: dict[str, list[Case]] = defaultdict(list)
    for c in cases:
        by_day[c.service_date].append(c)
    pool = Pool()
    out: list[Evaluation] = []
    for day in sorted(by_day):
        for c in by_day[day]:
            out.append(Evaluation(c.service_id, c.service_date, c.platform,
                                  pool.predict(c), pool.baseline(c)))
        for c in by_day[day]:  # ziua devine istoric abia după predicțiile ei
            pool.add(c)
    return out


_CASES_SQL = (
    "SELECT s.id, s.service_date, s.train_no, s.station, s.board, s.sched_time, o.platform"
    " FROM services s JOIN observations o ON o.service_id = s.id"
    " WHERE o.validation_state = 'ok' AND o.platform IS NOT NULL AND {where}"
    " ORDER BY s.service_date, s.id, o.id")


def load_cases(conn: sqlite3.Connection) -> list[Case]:
    """Servicii cu peronul adevărat: peronul modal din citirile valide. Egalitatea exclude
    serviciul. Doar citire."""
    reads: dict[int, list[int]] = defaultdict(list)
    meta: dict[int, tuple] = {}
    for sid, sd, tn, station, board, st, plat in conn.execute(
            _CASES_SQL.format(where=dq.public_services_where("s"))):
        reads[sid].append(int(plat))
        meta.setdefault(sid, (sd, int(tn), station, board, st))
    out: list[Case] = []
    for sid, vals in reads.items():
        ranked = Counter(vals).most_common(2)
        if len(ranked) > 1 and ranked[1][1] == ranked[0][1]:
            continue
        sd, tn, station, board, st = meta[sid]
        out.append(Case(sid, sd, tn, station, board, st, ranked[0][0]))
    out.sort(key=lambda c: (c.service_date, c.service_id))
    return out


def _pct(num: int, den: int) -> float | None:
    return round(100 * num / den, 1) if den else None


def report(evals: list[Evaluation]) -> dict:
    """Rezumat al backtestului: acuratețe, linie de bază, confuzii 5↔6 / 3↔8, cazuri fără
    predicție, N pe nivel."""
    done = [e for e in evals if e.prediction is not None]
    correct = sum(1 for e in done if e.prediction.platform == e.truth)
    common = [e for e in done if e.baseline is not None]
    wrong = [e for e in done if e.prediction.platform != e.truth]
    wrong_base = [e for e in common if e.baseline != e.truth]
    pairs_pred = sum(1 for e in wrong
                     if frozenset({e.prediction.platform, e.truth}) in CONFUSION_PAIRS)
    pairs_base = sum(1 for e in wrong_base
                     if frozenset({e.baseline, e.truth}) in CONFUSION_PAIRS)
    return {
        "n_cases": len(evals),
        "n_pred": len(done),
        "n_nopred": len(evals) - len(done),
        "acc_pred": _pct(correct, len(done)),
        "n_common": len(common),
        "acc_pred_common": _pct(sum(1 for e in common if e.prediction.platform == e.truth),
                                len(common)),
        "acc_base_common": _pct(sum(1 for e in common if e.baseline == e.truth), len(common)),
        "wrong_pairs_56_38": pairs_pred,
        "wrong_pairs_share": _pct(pairs_pred, len(wrong)),
        "base_wrong_pairs_share": _pct(pairs_base, len(wrong_base)),
        "by_level": {lv: sum(1 for e in done if e.prediction.basis == lv) for lv in ("a", "b")},
        "good_days": len({e.service_date for e in evals}),
    }


def gate(rep: dict) -> Gate:
    """Poarta de publicare. Publicat doar dacă toate condițiile sunt îndeplinite."""
    n = rep.get("n_pred") or 0
    if n < MIN_BACKTEST_N:
        return Gate(False, f"nepublicat: backtest cu {n} predicții (minim {MIN_BACKTEST_N})")
    acc = rep.get("acc_pred")
    if acc is None or acc < MIN_ACC:
        return Gate(False, f"nepublicat: acuratețe {acc} sub {MIN_ACC}")
    if not rep.get("n_common"):
        return Gate(False, "nepublicat: niciun caz comun cu linia de bază")
    diff = rep["acc_pred_common"] - rep["acc_base_common"]
    if diff < MIN_LIFT:
        return Gate(False, f"nepublicat: avantaj {diff:.1f} puncte față de linia de bază "
                           f"(minim {MIN_LIFT})")
    return Gate(True, f"publicat: acuratețe {acc} %, avantaj {diff:.1f} puncte")
