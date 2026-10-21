# © 2026 Andy217Ace
from __future__ import annotations

import os
from dataclasses import dataclass

from app.weather import WeatherConfig, config_from_env


@dataclass(frozen=True)
class Settings:
    db_path: str
    source_url: str
    vapid_private_key: str
    vapid_public_key: str
    vapid_subject: str
    tesseract_cmd: str
    poller_restart_backoff: float = 5.0  # first delay before restarting a crashed poller
    poller_enabled: bool = True  # POLLER_ENABLED=0 serves the stored board only (dev)
    last_image_path: str | None = "data/last.jpg"  # LAST_IMAGE_PATH="" disables saving
    weather: WeatherConfig | None = None  # get_settings: WEATHER_* env, on by default


def get_settings() -> Settings:
    return Settings(
        db_path=os.environ.get("DB_PATH", "tabela.db"),
        source_url=os.environ.get(
            "SOURCE_URL", "https://cfr.ro/gari/camereweb/index.php?statie=BucurestiNord"
        ),
        vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY", ""),
        vapid_public_key=os.environ.get("VAPID_PUBLIC_KEY", ""),
        vapid_subject=os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com"),
        tesseract_cmd=os.environ.get("TESSERACT_CMD", "tesseract"),
        poller_restart_backoff=float(os.environ.get("POLLER_RESTART_BACKOFF", "5")),
        poller_enabled=os.environ.get("POLLER_ENABLED", "1").strip().lower()
        not in ("0", "false", "no", "off"),
        last_image_path=os.environ.get("LAST_IMAGE_PATH", "data/last.jpg") or None,
        weather=config_from_env(),
    )
