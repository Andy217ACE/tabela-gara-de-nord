# © 2026 Andy217Ace
"""Backtest al predicției întârzierii finale (Val 5b). READ-ONLY, nu scrie nimic.

    python scripts/backtest_delay.py --db /cale/copie_read_only.db

Ia o COPIE a bazei (nu baza de producție): scriptul refuză explicit calea de producție
``/var/lib/tabela/tabela.db`` și deschide baza în modul ``mode=ro``. Afișează MAE
predicție vs. linia de bază „ultima întârziere citită”, procentul în interval, N pe grupă
și decizia porții de publicare (``app.predict.gate``).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import predict  # noqa: E402

PRODUCTION_DB = "/var/lib/tabela/tabela.db"


def check_db_path(path: str) -> str:
    """Întoarce calea absolută a copiei; ridică ValueError pentru baza de producție
    (verificare explicită, înainte de orice deschidere)."""
    absolute = os.path.abspath(path)
    if (os.path.normcase(absolute) == os.path.normcase(os.path.abspath(PRODUCTION_DB))
            or os.path.realpath(path) == os.path.realpath(PRODUCTION_DB)):
        raise ValueError(f"refuz: {path} este baza de producție; folosiți o copie read-only")
    if not os.path.isfile(absolute):
        raise ValueError(f"nu există fișierul: {path}")
    return absolute


def open_readonly(path: str) -> sqlite3.Connection:
    absolute = check_db_path(path)
    return sqlite3.connect(f"file:{Path(absolute).as_posix()}?mode=ro", uri=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, help="copia read-only a bazei de date")
    args = ap.parse_args(argv)
    try:
        conn = open_readonly(args.db)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    try:
        journeys = predict.load_journeys(conn)
    except sqlite3.OperationalError as e:
        print(f"baza nu are tabelele necesare (rulați mai întâi migrările pe copie): {e}",
              file=sys.stderr)
        return 2
    finally:
        conn.close()
    rep = predict.report(predict.walk_forward(journeys), journeys)
    g = predict.gate(rep)
    print(f"zile cu date bune: {rep['good_days']}")
    print(f"predicții evaluate: {rep['n_eval']} (sărite sub prag: {rep['n_skipped']})")
    print(f"N pe grupă: {rep['by_level']}")
    print(f"MAE estimare: {rep['mae_pred']}  MAE linie de bază: {rep['mae_base']}")
    print(f"mediana erorii estimării: {rep['median_err_pred']}")
    print(f"valori reale în interval P25–P75: {rep['in_interval_pct']}%")
    print(g.reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
