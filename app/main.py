# © 2026 Andy217Ace
"""ASGI entry point.

Run with `uvicorn app.main:create --factory` (or `uvicorn app.main:app`).
Importing this module does not build the app or start the poller: `app` is
created lazily on first attribute access.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app import api

_app: FastAPI | None = None


def create() -> FastAPI:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return api.create_app()


def __getattr__(name: str):
    global _app
    if name == "app":
        if _app is None:
            _app = create()
        return _app
    raise AttributeError(name)
