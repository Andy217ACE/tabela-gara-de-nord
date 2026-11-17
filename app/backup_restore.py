# © 2026 Andy217Ace
"""Fațadă Val 4b: copie, verificare, restaurare și listare a copiilor de siguranță.
Logica stă în `app.backup_api` (copie/verificare) și `app.restore` (restaurare)."""
from __future__ import annotations

from pathlib import Path

from app import dbbackup
from app.backup_api import KEEP, make_backup, verify_backup  # noqa: F401  (re-export)
from app.restore import CONFIRM, RestoreRefused, restore  # noqa: F401  (re-export)


def list_backups(directory: str | Path) -> list[Path]:
    """Copiile `tabela-*.db` din director, cele mai noi primele (numele conține ștampila).
    Director lipsă sau ilizibil: listă goală."""
    d = Path(directory)
    try:
        found = [p for p in d.iterdir() if p.is_file() and p.name.startswith(dbbackup.PREFIX)
                 and p.suffix == ".db"]
    except OSError:
        return []
    return sorted(found, key=lambda p: p.name, reverse=True)
