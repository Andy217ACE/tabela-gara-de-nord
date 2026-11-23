# © 2026 Andy217Ace
"""docs/api.md (and its English twin) must mention every route the app registers,
so the API documentation cannot silently go stale."""
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Route

from app.api import create_app
from tests.test_api import settings

DOCS = Path(__file__).resolve().parent.parent / "docs"
# Framework-generated, not part of the product API.
ALLOW = {
    "/openapi.json": "FastAPI schema endpoint",
    "/docs": "FastAPI Swagger UI",
    "/docs/oauth2-redirect": "FastAPI Swagger UI helper",
    "/redoc": "FastAPI ReDoc UI",
}


def _walk(routes, prefix=""):
    """FastAPI >= 0.15x keeps included routers lazy (_IncludedRouter): descend into them."""
    for r in routes:
        if isinstance(r, (APIRoute, Route)):
            yield prefix + r.path
        elif hasattr(r, "original_router"):
            yield from _walk(r.original_router.routes, prefix + r.include_context.prefix)


def _paths():
    app = create_app(settings(), start_poller=False)
    return sorted(set(_walk(app.routes)) - set(ALLOW))


@pytest.mark.parametrize("doc", [DOCS / "api.md", DOCS / "en" / "api.md"], ids=["ro", "en"])
def test_every_registered_route_is_documented(doc):
    text = doc.read_text(encoding="utf-8")
    missing = [p for p in _paths() if p not in text]
    assert not missing, f"routes missing from {doc.name}: {missing}"
