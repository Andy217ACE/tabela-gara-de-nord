# © 2026 Andy217Ace
"""Backtest al predicției peronului (Val 5b). READ-ONLY, nu scrie nimic.

    python scripts/backtest_peron.py --db /cale/copie_read_only.db

Ia o COPIE a bazei (nu baza de producție): scriptul refuză explicit calea de producție
``/var/lib/tabela/tabela.db`` și deschide baza în modul ``mode=ro``. Afișează N,
acuratețea predicției, linia de bază „ultimul peron citit”, cazurile fără predicție,
confuziile 5↔6 / 3↔8 și decizia porții de publicare (``app.peron_predict.gate``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import peron_predict as pp  # noqa: E402
from backtest_delay import check_db_path, open_readonly  # noqa: E402

PRODUCTION_DB = "/var/lib/tabela/tabela.db"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):  # consola Windows: diacriticele din rapoarte
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, help="copia read-only a bazei de date")
    args = ap.parse_args(argv)
    try:
        conn = open_readonly(args.db)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    try:
        cases = pp.load_cases(conn)
    except Exception as e:  # noqa: BLE001 — schema lipsă: mesaj clar, nu traceback
        print(f"baza nu are tabelele necesare (rulați mai întâi migrările pe copie): {e}",
              file=sys.stderr)
        return 2
    finally:
        conn.close()
    rep = pp.report(pp.walk_forward(cases))
    g = pp.gate(rep)
    print(f"servicii cu peron adevărat: {rep['n_cases']} (zile: {rep['good_days']})")
    print(f"predicții evaluate: {rep['n_pred']}  fără predicție: {rep['n_nopred']}")
    print(f"acuratețe predicție (toate cazurile cu predicție): {rep['acc_pred']} %")
    print(f"cazuri comune cu linia de bază: {rep['n_common']}")
    print(f"acuratețe predicție pe cazuri comune: {rep['acc_pred_common']} %")
    print(f"acuratețe linie de bază pe cazuri comune: {rep['acc_base_common']} %")
    print(f"N pe nivel: {rep['by_level']}")
    print(f"greșeli predicție 5↔6/3↔8: {rep['wrong_pairs_56_38']} "
          f"({rep['wrong_pairs_share']} % din greșeli)")
    print(f"greșeli linie de bază 5↔6/3↔8: {rep['base_wrong_pairs_share']} % din greșelile ei")
    print(g.reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
