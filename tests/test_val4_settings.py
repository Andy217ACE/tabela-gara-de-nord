# © 2026 Andy217Ace
"""app.settings: fațada Val 4c; setări validate, nimic nu se scrie la valoare invalidă."""
import pytest

from app import settings
from app.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.migrate()
    yield s
    s.close()


def test_out_of_range_changes_nothing(store):
    with pytest.raises(ValueError):
        settings.save(store, {"capture_retention_days": 5, "capture_min_free_mb": 1})
    assert settings.effective(store, "capture_retention_days", 7) == 7


def test_save_then_view_roundtrip(store):
    settings.save(store, {"capture_retention_days": 3})
    v = settings.view(store, {})
    assert v["capture_retention_days"]["value"] == 3
    assert (v["capture_retention_days"]["min"], v["capture_retention_days"]["max"]) == (1, 30)


def test_no_secret_keys_exposed():
    assert not any("token" in k or "key" in k.lower() for k in settings.SPECS)


def test_is_known_key():
    assert settings.is_known("capture_retention_days")
    assert not settings.is_known("admin_token")
