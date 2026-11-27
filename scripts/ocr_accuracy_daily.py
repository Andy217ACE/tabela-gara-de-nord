# © 2026 Andy217Ace
"""Monitorizarea zilnica a acuratetii OCR pe cadrele live (doar citire din baza).

Fara etichete scrise de mana pe live, valoarea *confirmata* a unui camp intr-o citire e
consensul (app.consensus.winner: majoritate stricta, >= 3 voturi) al celorlalte citiri ale
aceluiasi serviciu din jurul ei (K inainte si K dupa, citirea insasi nu voteaza). Citirea e
ok (egala), necitita (None) sau gresita (alta valoare); fara consens, campul nu se noteaza.
Se noteaza doar citirile publicate (validation_state ok/uncertain), pe ziua de serviciu.

E o masura de consecventa, nu adevar: o greseala stabila (aceeasi in toate cadrele) apare
ok aici; adevarul ramane suita de regresie (tests/test_ocr_regression.py). Utilitatea ei e
tendinta zi de zi, in aceleasi campuri si categorii ca scripts/ocr_eval.py.

    python scripts/ocr_accuracy_daily.py [--db FILE] [--date AAAA-LL-ZZ] [--days N] [--out DIR]

Implicit: ziua de ieri, rezumat JSON pe stdout; cu --out, si ocr-accuracy-AAAA-LL-ZZ.json in DIR.
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.consensus import FIELDS, VOTING_STATES, _vote_of, winner  # noqa: E402
from app.store import TZ  # noqa: E402

DEFAULT_DB = Path("/var/lib/tabela/tabela.db")
K = 7  # vecini de fiecare parte: fereastra ~ consensus.WINDOW (15)


def score_service(reads: list[dict], counts: dict, k: int = K) -> None:
    """Adauga in `counts` ({camp: Counter}) notele citirilor unui serviciu (in ordinea timpului)."""
    for i, r in enumerate(reads):
        around = reads[max(0, i - k):i] + reads[i + 1:i + 1 + k]
        for f in FIELDS:
            want = winner(_vote_of(n, f) for n in around)
            if want is None:
                continue
            cell = r.get(f)
            got = cell.get("norm") if isinstance(cell, dict) else None
            counts[f]["ok" if got == want else "unread" if got is None else "wrong"] += 1


def day_summary(con: sqlite3.Connection, day: str) -> dict:
    counts = {f: collections.Counter() for f in FIELDS}
    marks = ",".join("?" * len(VOTING_STATES))
    rows = con.execute(
        "SELECT o.service_id, o.fields_json FROM observations o"
        " JOIN services s ON s.id = o.service_id"
        f" WHERE s.service_date = ? AND o.validation_state IN ({marks})"
        " ORDER BY o.service_id, o.observed_at, o.id", (day, *VOTING_STATES)).fetchall()
    by_service: dict[int, list[dict]] = collections.defaultdict(list)
    for sid, fj in rows:
        try:
            by_service[sid].append(json.loads(fj or "{}"))
        except (TypeError, ValueError):
            continue
    for reads in by_service.values():
        score_service(reads, counts)
    fields = {}
    for f in FIELDS:
        c = counts[f]
        n = c["ok"] + c["unread"] + c["wrong"]
        fields[f] = {"n": n, "ok": c["ok"], "unread": c["unread"], "wrong": c["wrong"],
                     "accuracy": round(c["ok"] / n, 4) if n else None}
    return {"date": day, "method": f"leave-one-out consensus, K={K}",
            "services": len(by_service), "readings": len(rows), "fields": fields}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--date", help="ultima zi (implicit ieri, ora Romaniei)")
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--out", help="director pentru ocr-accuracy-AAAA-LL-ZZ.json")
    a = ap.parse_args(argv)
    last = (date.fromisoformat(a.date) if a.date
            else datetime.now(TZ).date() - timedelta(days=1))
    con = sqlite3.connect(f"{Path(a.db).resolve().as_uri()}?mode=ro", uri=True)
    try:
        for i in range(a.days - 1, -1, -1):
            s = day_summary(con, (last - timedelta(days=i)).isoformat())
            print(json.dumps(s, ensure_ascii=False), flush=True)
            if a.out:
                Path(a.out).mkdir(parents=True, exist_ok=True)
                (Path(a.out) / f"ocr-accuracy-{s['date']}.json").write_text(
                    json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
