# © 2026 Andy217Ace
"""Val 5 — rutele legate în api.py: export CSV sezoane și estimarea per tren (cu poartă)."""
from fastapi.testclient import TestClient

from app.api import create_app
from tests.test_api import settings


def test_seasons_csv_route_has_bom_and_header():
    with TestClient(create_app(settings(), start_poller=False)) as c:
        r = c.get("/api/stats/seasons?format=csv")
    assert r.status_code == 200
    assert r.content.startswith(b"\xef\xbb\xbf")
    assert "text/csv" in r.headers["content-type"]
    assert 'filename="sezoane.csv"' in r.headers["content-disposition"]


def test_seasons_json_is_default():
    with TestClient(create_app(settings(), start_poller=False)) as c:
        r = c.get("/api/stats/seasons")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")


def test_train_prediction_is_gated_without_numbers_on_empty_base():
    with TestClient(create_app(settings(), start_poller=False)) as c:
        r = c.get("/api/trains/1234/prediction")
    assert r.status_code == 200
    body = r.json()
    assert body.get("published") is False
