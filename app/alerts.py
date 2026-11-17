# © 2026 Andy217Ace
"""Punct unic de intrare pentru canalele de alertă (Val 4d). Implementarea Telegram e în
`app.telegram`; aici se expun doar numele canalelor active, fără secrete."""
from __future__ import annotations

import os

from app.telegram import config_from_env, make_telegram_sender  # noqa: F401  (re-export)


def enabled_channels(env=None) -> list[str]:
    """Numele canalelor opționale active (azi doar „telegram”); niciodată valori de mediu."""
    env = os.environ if env is None else env
    return ["telegram"] if config_from_env(env) is not None else []
