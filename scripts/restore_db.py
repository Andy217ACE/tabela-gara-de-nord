# © 2026 Andy217Ace
"""Restaurează baza din o copie de siguranță. Rulează pe server, cu serviciul oprit:

    sudo systemctl stop tabela
    python scripts/restore_db.py COPIE.db --db /var/lib/tabela/tabela.db --confirm RESTAUREZ
    sudo systemctl start tabela

Fără `--confirm RESTAUREZ` nu se face nimic. Starea curentă se salvează înainte."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import restore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Restaurează baza din o copie de siguranță.")
    ap.add_argument("copie", type=Path, help="fișierul copiei (.db)")
    ap.add_argument("--db", type=Path, required=True, help="baza de date live")
    ap.add_argument("--confirm", default="", help=f"trebuie să fie „{restore.CONFIRM}”")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        restore.restore(args.copie, args.db, confirm=args.confirm)
    except restore.RestoreRefused as e:
        print(f"Refuzat: {e}", file=sys.stderr)
        return 2
    print("Restaurare făcută. Pornește serviciul.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
