# © 2026 Andy217Ace
"""HTTP routes of the „Sistem” page: GET /api/system (public, minimal) and
GET /api/admin/system (admin only, with details). Both come from
`system_status.collect_status`; the app is wired with `include_router(router)` and
`include_router(admin_router)` in app.api."""
from __future__ import annotations

import hmac
from datetime import datetime

from fastapi import APIRouter, Depends, Request

from app import admin
from app.store import TZ
from app.system_status import collect_status

router = APIRouter()
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin.require_admin)])


def _is_admin(request: Request) -> bool:
    """True when this client has a valid admin bearer token or session cookie. Never raises,
    so the public page can tell an admin apart without a 503/401 on anonymous visits."""
    token = admin.admin_token()
    if not token:
        return False
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer " and hmac.compare_digest(auth[7:].strip().encode(), token.encode()):
        return True
    return admin.check_session(token, request.cookies.get(admin.COOKIE))


@router.get("/api/system")
def system(request: Request):
    out = collect_status(request.app.state.store, request.app.state.settings,
                         datetime.now(TZ))
    out["admin"] = _is_admin(request)  # the page asks /api/admin/system only when True
    return out


@admin_router.get("/system")
def system_admin(request: Request):
    return collect_status(request.app.state.store, request.app.state.settings,
                          datetime.now(TZ), admin=True)
