# © 2026 Andy217Ace
"""Predicția întârzierii FINALE a unui tren (Val 5b).

Estimare, nu citire: mediana întârzierilor confirmate ale aceluiași tren (sau ale
stației, pe oră și zi a săptămânii), cu interval P25–P75 și N. Nu scrie nimic în baza
de date (citește doar ``services`` / ``service_quality`` / ``events``).

Ierarhia (prima variantă cu n suficient):
  (a) tren + stație + bord + zi a săptămânii, n >= MIN_N_TRAIN;
  (b) tren + bord, n >= MIN_N_TRAIN;
  (c) stație + bord + oră + zi a săptămânii, n >= MIN_N_STATION.
Sub prag: fără predicție (``predict_final`` întoarce None).

Poarta de publicare (``gate``): predicția se arată public DOAR dacă backtestul
(``walk_forward``) arată MAE mai mic decât linia de bază „ultima întârziere citită”,
cu cel puțin MIN_GOOD_DAYS zile de date bune și MIN_BACKTEST_N predicții evaluate.
Altfel ``gate`` întoarce ``Gate(False, motiv)``.
"""
from __future__ import annotations

import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app import quality as dq

MIN_N_TRAIN = 10  # n minim pe grupă pentru nivelurile (a) și (b)
MIN_N_STATION = 30  # n minim pe grupă pentru nivelul (c)
MIN_GOOD_DAYS = 30  # zile calendaristice cu date confirmate, înainte de orice publicare
MIN_BACKTEST_N = 100  # predicții evaluate în backtest, înainte de orice publicare

LEVELS = ("a", "b", "c")


@dataclass(frozen=True)
class Journey:
    """O călătorie cu întârziere finală confirmată și linia de bază din backtest."""
    service_id: int
    train_no: int
    board: str
    station: str
    service_date: str  # YYYY-MM-DD
    sched_time: str  # HH:MM
    final: int  # ultima întârziere confirmată (services/service_quality.last_delay_clean)
    baseline: int  # ultima întârziere citită la prima citire (0 dacă nu s-a citit altceva)


@dataclass(frozen=True)
class Prediction:
    delay_min: float  # mediana grupei
    low: float  # P25
    high: float  # P75
    n: int
    basis: str  # "a" | "b" | "c"


@dataclass(frozen=True)
class Gate:
    published: bool
    reason: str


def _weekday(service_date: str) -> int:
    return date.fromisoformat(service_date).weekday()


def _hour(sched_time: str) -> int:
    return int(sched_time.split(":")[0])


def _keys(j: Journey) -> dict[str, tuple]:
    wd = _weekday(j.service_date)
    return {
        "a": (j.train_no, j.station, j.board, wd),
        "b": (j.train_no, j.board),
        "c": (j.station, j.board, _hour(j.sched_time), wd),
    }


_MIN_N = {"a": MIN_N_TRAIN, "b": MIN_N_TRAIN, "c": MIN_N_STATION}


class Pool:
    """Eșantioane de antrenare pe grupe. Se construiește din zile anterioare; nu se modifică
    la predicție."""

    def __init__(self) -> None:
        self._groups: dict[str, dict[tuple, list[int]]] = {lv: defaultdict(list) for lv in LEVELS}

    def add(self, j: Journey) -> None:
        for lv, key in _keys(j).items():
            self._groups[lv][key].append(j.final)

    def values(self, level: str, key: tuple) -> list[int]:
        return self._groups[level].get(key, [])


def build_pool(journeys: list[Journey]) -> Pool:
    pool = Pool()
    for j in journeys:
        pool.add(j)
    return pool


def predict_final(pool: Pool, j: Journey) -> Prediction | None:
    """Predicția întârzierii finale pentru călătoria ``j``, din ``pool``; None sub prag.
    Citește doar pool-ul; ``j.final`` nu se folosește."""
    keys = _keys(j)
    for lv in LEVELS:
        vals = pool.values(lv, keys[lv])
        if len(vals) >= _MIN_N[lv]:
            q1, _, q3 = statistics.quantiles(vals, n=4, method="inclusive")
            return Prediction(delay_min=float(statistics.median(vals)), low=q1, high=q3,
                              n=len(vals), basis=lv)
    return None


@dataclass(frozen=True)
class Evaluation:
    service_id: int
    service_date: str
    final: int
    baseline: int
    prediction: Prediction | None


def walk_forward(journeys: list[Journey]) -> list[Evaluation]:
    """Backtest temporal: pentru fiecare zi t, predicția folosește doar călătoriile din zile
    strict anterioare lui t (fără scurgere din viitor)."""
    by_day: dict[str, list[Journey]] = defaultdict(list)
    for j in journeys:
        by_day[j.service_date].append(j)
    pool = Pool()
    out: list[Evaluation] = []
    for day in sorted(by_day):
        for j in by_day[day]:
            out.append(Evaluation(j.service_id, j.service_date, j.final, j.baseline,
                                  predict_final(pool, j)))
        for j in by_day[day]:  # the day becomes history only after its predictions
            pool.add(j)
    return out


def report(evals: list[Evaluation], journeys: list[Journey]) -> dict:
    """Rezumat al backtestului: MAE predicție și linie de bază, procent în interval, N pe grupă."""
    done = [e for e in evals if e.prediction is not None]
    n = len(done)
    by_level = {lv: sum(1 for e in done if e.prediction.basis == lv) for lv in LEVELS}
    if n:
        mae_pred = sum(abs(e.prediction.delay_min - e.final) for e in done) / n
        mae_base = sum(abs(e.baseline - e.final) for e in done) / n
        median_err = statistics.median(e.prediction.delay_min - e.final for e in done)
        inside = sum(1 for e in done if e.prediction.low <= e.final <= e.prediction.high)
        in_pct = round(100 * inside / n, 1)
    else:
        mae_pred = mae_base = median_err = in_pct = None
    return {
        "n_eval": n,
        "n_skipped": len(evals) - n,
        "mae_pred": mae_pred,
        "mae_base": mae_base,
        "median_err_pred": median_err,
        "in_interval_pct": in_pct,
        "by_level": by_level,
        "good_days": len({j.service_date for j in journeys}),
    }


def gate(rep: dict) -> Gate:
    """Poarta de publicare. Publicat doar dacă toate condițiile sunt îndeplinite."""
    days = rep.get("good_days") or 0
    if days < MIN_GOOD_DAYS:
        return Gate(False, f"nepublicat: {days} zile de date bune (minim {MIN_GOOD_DAYS})")
    n = rep.get("n_eval") or 0
    if n < MIN_BACKTEST_N:
        return Gate(False, f"nepublicat: backtest cu {n} predicții (minim {MIN_BACKTEST_N})")
    mp, mb = rep.get("mae_pred"), rep.get("mae_base")
    if mp is None or mb is None:
        return Gate(False, "nepublicat: MAE lipsă")
    if mp >= mb:
        return Gate(False, f"nepublicat: MAE estimare {mp:.2f} nu bate linia de bază {mb:.2f}")
    return Gate(True, f"publicat: MAE estimare {mp:.2f} < linia de bază {mb:.2f}")


_SERVICES_SQL = (
    "SELECT s.id, s.train_no, s.board, s.station, s.service_date, s.sched_time,"
    " q.last_delay_clean"
    " FROM services s JOIN service_quality q ON q.service_id = s.id"
    " WHERE q.delay_checked = 1 AND q.last_delay_clean IS NOT NULL AND {where}"
    " ORDER BY s.service_date, s.id")

_FIRST_READ_SQL = (
    "SELECT e.service_id, e.new FROM events e"
    " WHERE e.kind = 'delay' AND NOT {suspect}"
    " ORDER BY e.service_id, e.ts, e.id")


def load_journeys(conn: sqlite3.Connection) -> list[Journey]:
    """Călătoriile cu întârziere finală confirmată (fără ghosturi și fără perioada de calitate
    redusă). Doar citire."""
    rows = conn.execute(_SERVICES_SQL.format(where=dq.public_services_where("s"))).fetchall()
    first: dict[int, int] = {}
    for sid, new in conn.execute(_FIRST_READ_SQL.format(suspect=dq.SUSPECT_EVENT_SQL)):
        if sid not in first:  # the first delay read of the journey
            try:
                first[sid] = int(new)
            except (TypeError, ValueError):
                continue
    return [Journey(sid, int(tn), board, station, sd, st, int(final), first.get(sid, 0))
            for sid, tn, board, station, sd, st, final in rows]
