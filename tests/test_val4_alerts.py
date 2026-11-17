# © 2026 Andy217Ace
"""app.alerts: punctul unic de intrare pentru canalele de alertă (Val 4d)."""
from app import alerts, telegram


def test_no_token_means_no_channels():
    assert alerts.enabled_channels({}) == []
    assert alerts.enabled_channels({"TELEGRAM_BOT_TOKEN": "x"}) == []  # fără chat


def test_telegram_listed_without_leaking_secrets():
    env = {"TELEGRAM_BOT_TOKEN": "123:SECRET", "TELEGRAM_CHAT_ID": "42"}
    out = alerts.enabled_channels(env)
    assert out == ["telegram"]
    assert "SECRET" not in repr(out)


def test_reexports_are_the_telegram_ones():
    assert alerts.make_telegram_sender is telegram.make_telegram_sender
    assert alerts.config_from_env is telegram.config_from_env
