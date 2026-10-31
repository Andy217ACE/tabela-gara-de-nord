# © 2026 Andy217Ace
"""HTTP routes of the „Sistem” page: GET /api/system (public, minimal) and
GET /api/admin/system (admin only, with details). Both come from
`system_status.collect_status`; the app is wired with `include_router(router)` and
`include_router(admin_router)` in app.api."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request

from app import admin
from app.store import TZ
from app.system_status import collect_status

router = APIRouter()
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin.require_admin)])


@router.get("/api/system")
def system(request: Request):
    return collect_status(request.app.state.store, request.app.state.settings,
                          datetime.now(TZ))


@admin_router.get("/system")
def system_admin(request: Request):
    return collect_status(request.app.state.store, request.app.state.settings,
                          datetime.now(TZ), admin=True)
