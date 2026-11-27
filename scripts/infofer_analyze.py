# © 2026 Andy217Ace
"""Spike INTERN: prezice harta Infofer întârzierea la sosirea în Gara de Nord mai devreme
decât o arată tabela? READ-ONLY pe ambele baze, nu scrie nimic.

    python scripts/infofer_analyze.py [--infofer /var/lib/tabela/infofer.db]
                                      [--db /var/lib/tabela/tabela.db] [--json]

Pentru fiecare sosire cu întârziere finală confirmată (``app.predict.load_journeys``, aceeași
definiție ca backtestul) și pentru orizonturile T-60/-30/-15 min înainte de ora din mers,
ia ultima observație Infofer proaspătă de la acel moment și compară „întârzierea Infofer
de acum” cu finala. Linii de bază: ce arăta tabela la acel moment (ultima întârziere
citită, 0 dacă nimic) și modelul din app/predict.py (mediana istorică, 0 fără istoric).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import predict, quality  # noqa: E402
from app.journeys import TZ, sched_at  # noqa: E402

DEFAULT_INFOFER = "/var/lib/tabela/infofer.db"
DEFAULT_DB = "/var/lib/tabela/tabela.db"
HORIZONS = (60, 30, 15)
MAX_PASSED = 15  # passedTime >= 15: Infofer însuși gri-ează markerul (poziție veche)
MAX_REPORT_AGE_MIN = 30  # raportarea CFR mai veche de atât față de cerere: ignorată
MAX_LOOKBACK = timedelta(minutes=60)  # observația trebuie să fie din ultima oră a orizontului


def _ro(path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)


def _fresh(fetched: datetime, passed: int | None, report_hhmm: str | None) -> bool:
    if passed is not None and passed >= MAX_PASSED:
        return False
    if report_hhmm:
        local = fetched.astimezone(TZ)
        hh, mm = (int(p) for p in report_hhmm.split(":"))
        age = (local.hour * 60 + local.minute - hh * 60 - mm) % (24 * 60)  # raport de ieri
        if age > MAX_REPORT_AGE_MIN:
            return False
    return True


def load_obs(conn: sqlite3.Connection) -> dict[str, list[tuple]]:
    """train_no -> [(fetched_at, service_date, delay_min)] proaspete, sortate după timp."""
    out: dict[str, list[tuple]] = defaultdict(list)
    for fa, sd, tn, dl, rep, passed in conn.execute(
            "SELECT fetched_at, service_date, train_no, delay_min, report_hhmm, passed_time"
            " FROM infofer_obs WHERE delay_min IS NOT NULL ORDER BY fetched_at"):
        fetched = datetime.fromisoformat(fa)
        if _fresh(fetched, passed, rep):
            out[tn.lstrip("0") or "0"].append((fetched, sd, dl))
    return out


def pick(obs: list[tuple], at: datetime, service_date: str) -> int | None:
    """Ultima întârziere Infofer la `at` (cel mult MAX_LOOKBACK în urmă). Data Infofer e a
    plecării trenului: o sosire după miezul nopții poate avea data din ziua anterioară."""
    days = {service_date, (date.fromisoformat(service_date) - timedelta(days=1)).isoformat()}
    i = bisect_right([o[0] for o in obs], at)
    for fetched, sd, dl in reversed(obs[:i]):
        if at - fetched > MAX_LOOKBACK:
            return None
        if sd in days:
            return dl
    return None


def load_board(conn: sqlite3.Connection) -> dict[int, list[tuple]]:
    """service_id -> [(ts, delay)] citiri de întârziere (fără cele suspecte), după timp."""
    out: dict[int, list[tuple]] = defaultdict(list)
    for sid, ts, new in conn.execute(
            "SELECT e.service_id, e.ts, e.new FROM events e"
            f" WHERE e.kind = 'delay' AND NOT {quality.SUSPECT_EVENT_SQL} ORDER BY e.ts, e.id"):
        try:
            d = datetime.fromisoformat(ts)
            out[sid].append((d if d.tzinfo else d.replace(tzinfo=TZ), int(new)))
        except (TypeError, ValueError):
            continue
    return out


def board_at(reads: list[tuple], at: datetime) -> int:
    val = 0
    for ts, dl in reads:
        if ts > at:
            break
        val = dl
    return val


def _stats(pairs: list[tuple[float, int]]) -> dict:
    if not pairs:
        return {"mae": None, "bias": None}
    n = len(pairs)
    return {"mae": round(sum(abs(p - f) for p, f in pairs) / n, 2),
            "bias": round(sum(p - f for p, f in pairs) / n, 2)}


def analyze(infofer: sqlite3.Connection, main: sqlite3.Connection) -> dict:
    obs = load_obs(infofer)
    span = infofer.execute("SELECT MIN(fetched_at), MAX(fetched_at) FROM infofer_obs").fetchone()
    result = {"period": span, "horizons": {}, "worst": []}
    if not span[0]:
        return result
    first, last = (datetime.fromisoformat(s) for s in span)
    journeys = [j for j in predict.load_journeys(main) if j.board == "arrival"]
    model = {e.service_id: e.prediction for e in predict.walk_forward(journeys)}
    board = load_board(main)
    misses = []
    for h in HORIZONS:
        eligible = covered = better = 0
        pairs = {"infofer": [], "tabela": [], "model": []}
        for j in journeys:
            at = (sched_at(j.service_date, j.sched_time).astimezone(timezone.utc)
                  - timedelta(minutes=h))
            if not first <= at <= last:  # doar sosirile din perioada colectării
                continue
            eligible += 1
            inf = pick(obs.get(str(j.train_no), []), at, j.service_date)
            if inf is None:
                continue
            covered += 1
            tab = board_at(board.get(j.service_id, []), at)
            pred = model.get(j.service_id)
            pairs["infofer"].append((inf, j.final))
            pairs["tabela"].append((tab, j.final))
            pairs["model"].append((pred.delay_min if pred else 0, j.final))
            better += abs(inf - j.final) < abs(tab - j.final)
            misses.append({"train_no": j.train_no, "service_date": j.service_date,
                           "sched_time": j.sched_time, "horizon": h, "infofer": inf,
                           "tabela": tab, "final": j.final, "err": inf - j.final})
        result["horizons"][h] = {
            "eligible": eligible, "covered": covered,
            "coverage_pct": round(100 * covered / eligible, 1) if eligible else None,
            "infofer_better_pct": round(100 * better / covered, 1) if covered else None,
            **{k: _stats(v) for k, v in pairs.items()}}
    result["worst"] = sorted(misses, key=lambda m: -abs(m["err"]))[:10]
    return result


def _f(v) -> str:
    return "-" if v is None else str(v)


def text_report(r: dict) -> str:
    lines = ["Spike Infofer (INTERN) - întârzierea la sosire, Gara de Nord",
             f"Perioada observațiilor Infofer (UTC): {r['period'][0]} .. {r['period'][1]}"]
    if not r["horizons"]:
        return "\n".join(lines + ["Nicio observație Infofer."])
    lines.append("Predicția = întârzierea Infofer de la acel moment; finala = confirmată din tabela.")
    for h, s in r["horizons"].items():
        lines.append(
            f"\nT-{h} min: {s['covered']}/{s['eligible']} sosiri cu observație"
            f" (acoperire {_f(s['coverage_pct'])}%); Infofer mai aproape decât tabela în"
            f" {_f(s['infofer_better_pct'])}% din cazuri")
        for name, label in (("infofer", "Infofer"), ("tabela", "Tabela la acel moment"),
                            ("model", "Model app/predict (0 fără istoric)")):
            lines.append(f"  {label:<36} MAE {_f(s[name]['mae'])} min, bias {_f(s[name]['bias'])} min")
    if r["worst"]:
        lines.append("\nCele mai mari 10 erori Infofer (tren, data, ora, orizont: Infofer / tabela / finală):")
        for m in r["worst"]:
            lines.append(f"  {m['train_no']:>6} {m['service_date']} {m['sched_time']} T-{m['horizon']}:"
                         f" {m['infofer']} / {m['tabela']} / {m['final']} (eroare {m['err']:+d})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Spike Infofer: analiza predicției la sosire")
    ap.add_argument("--infofer", default=DEFAULT_INFOFER)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    inf, main_db = _ro(args.infofer), _ro(args.db)
    try:
        r = analyze(inf, main_db)
    finally:
        inf.close()
        main_db.close()
    print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else text_report(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
