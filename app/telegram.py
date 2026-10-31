# © 2026 Andy217Ace
"""Telegram alerts for followed trains (Val 4d), a second channel next to Web Push.

Only the administrator receives them: one fixed chat, configured in the
environment (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Off unless both are set.

Failures are not retried. Each attempt is recorded in a small JSON file
(`TELEGRAM_STATE_PATH`, default `data/telegram_sent.json`), so an event that was
already attempted is not sent again after a restart. The file holds only event
keys and service dates; it needs no table.

The token is never logged, never put in an exception message and never returned.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

import httpx

from app.store import Subscription

log = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Bucharest")
API = "https://api.telegram.org"
HTTP_TIMEOUT = 10.0
ERROR_LOG_EVERY = 600.0  # a network/HTTP error is logged at most once per 10 minutes
KEEP_DAYS = 2            # sent-keys are kept for today and the day before (as in notifier)


@dataclass(frozen=True)
class TelegramConfig:
    token: str = field(repr=False)
    chat_id: str
    state_path: str = "data/telegram_sent.json"


def config_from_env(env=None) -> TelegramConfig | None:
    """None (channel off) unless both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."""
    env = os.environ if env is None else env
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = env.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return None
    return TelegramConfig(token=token, chat_id=chat,
                          state_path=env.get("TELEGRAM_STATE_PATH", "").strip()
                          or "data/telegram_sent.json")


class SentLog:
    """Keys of the alerts already attempted, persisted to a small JSON file."""

    def __init__(self, path: str):
        self.path = Path(path)
        self._keys: dict[str, str] = {}  # key -> service_date (ISO)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._keys = {str(k): str(v) for k, v in raw.items()}
        except (OSError, ValueError):
            self._keys = {}  # missing or unreadable: start empty (a new file is written later)

    def has(self, key: str) -> bool:
        return key in self._keys

    def record(self, key: str, service_date: str, today: date) -> None:
        self._keys[key] = service_date
        keep = (today - timedelta(days=KEEP_DAYS - 1)).isoformat()
        self._keys = {k: v for k, v in self._keys.items() if v >= keep}
        self._save()

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._keys, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("telegram state not saved: %s", type(e).__name__)


def format_text(data: dict, now: datetime) -> str:
    """Short Romanian text with the reading time (the token never appears here)."""
    body = data.get("body") or ""
    return f"Gara de Nord: {body}. Ora citirii: {now.astimezone(TZ):%H:%M}."


class TelegramChannel:
    """Sends one alert to the fixed chat. `send(sub, data)` has the Notifier signature;
    `sub` is ignored because the destination is the configured chat."""

    def __init__(self, cfg: TelegramConfig, *, client: httpx.AsyncClient | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(TZ),
                 sent: SentLog | None = None):
        self.cfg = cfg
        self._client = client
        self._clock = clock
        self.sent = sent if sent is not None else SentLog(cfg.state_path)
        self._last_error_log: float | None = None

    def has(self, key: str) -> bool:
        return self.sent.has(key)

    def record(self, key: str, service_date: str | None, today: date) -> None:
        self.sent.record(key, service_date or today.isoformat(), today)

    async def send(self, sub: Subscription | None, data: dict) -> None:
        text = format_text(data, self._clock())
        url = f"{API}/bot{self.cfg.token}/sendMessage"
        payload = {"chat_id": self.cfg.chat_id, "text": text, "disable_web_page_preview": True}
        try:
            client = self._client or httpx.AsyncClient(timeout=HTTP_TIMEOUT)
            try:
                r = await client.post(url, json=payload, timeout=HTTP_TIMEOUT)
            finally:
                if self._client is None:
                    await client.aclose()
            if r.status_code != 200:
                self._log_error(f"telegram failed: HTTP {r.status_code}")
        except httpx.HTTPError as e:  # str(e) may contain the URL: log the type only
            self._log_error(f"telegram failed: {type(e).__name__}")

    def _log_error(self, msg: str) -> None:
        now = time.monotonic()
        if self._last_error_log is None or now - self._last_error_log >= ERROR_LOG_EVERY:
            self._last_error_log = now
            log.warning(msg)


def make_telegram_sender(cfg: TelegramConfig, **kwargs) -> TelegramChannel:
    """Channel for the Notifier. Returns the object (with `send`, `has`, `record`)."""
    return TelegramChannel(cfg, **kwargs)
