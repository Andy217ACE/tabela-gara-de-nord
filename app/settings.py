# © 2026 Andy217Ace
"""Fațadă Val 4c: setările editabile din pagina Setări. Logica (validare, tabel `settings`,
audit) e în `app.admin_settings`; cheia de admin și tokenurile nu intră niciodată aici."""
from __future__ import annotations

from app.admin_settings import SPECS, effective, save, validate, view  # noqa: F401  (re-export)


def is_known(key: str) -> bool:
    return key in SPECS
