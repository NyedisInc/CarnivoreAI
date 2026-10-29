
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from src.api import app_update_routes, peer_auth
from src.api.auth import require_auth
from src.core.federation import peer_app_update, peer_fanout
from src.core.pack.machines import config_state, restrictions

served = APIRouter(prefix="/federation/app-update", tags=["app-update"])
asked = APIRouter(prefix="/app-update/computer", tags=["app-update"], dependencies=[Depends(require_auth)])
_peer = peer_auth.require_peer_sessions


async def _may_write(request: Request, principal: peer_auth.Principal = Depends(_peer)) -> None:
    if principal.is_peer:
        current = await asyncio.to_thread(config_state.default().restrictions)
        restrictions.enforce(current, restrictions.ACTION_UPDATE_CARNIVORE)


@served.get("", dependencies=[Depends(_peer)])
async def served_status() -> Dict[str, Any]:
    """This computer's updater status, as the owner's ``GET /app-update`` answers it."""
    return await app_update_routes.get_status()


@served.put("/auto-update", dependencies=[Depends(_may_write)])
async def served_auto_update(body: app_update_routes.AutoUpdateSetting) -> Dict[str, Any]:
    """Turn this computer's automatic updates on or off. Example: PUT {"enabled": true}."""
    return await app_update_routes.set_auto_update(body)


@served.post("/check", dependencies=[Depends(_may_write)])
async def served_check() -> Dict[str, Any]:
    """Ask this computer's app to check the feed now."""
    return await app_update_routes.check_now()


@served.post("/install", dependencies=[Depends(_may_write)])
async def served_install() -> Dict[str, Any]:
    """Ask this computer's app to download if needed and restart into the update (409 when there is none)."""
    return await app_update_routes.install_now()


async def _ask(request: Request, host_key: str, action: str, enabled: Any = None) -> Dict[str, Any]:
    if peer_fanout.is_peer_call(request):
        return {"status": "unavailable", "reason": "not_local"}
    return await peer_app_update.call(peer_auth.open_db, host_key, action, enabled)


@asked.get("/{host_key}")
async def computer_status(host_key: str, request: Request) -> Dict[str, Any]:
    """One paired computer's updater status, asked at request time. Output: see ``peer_app_update.call``."""
    return await _ask(request, host_key, "status")


@asked.put("/{host_key}/auto-update")
async def computer_auto_update(host_key: str, body: app_update_routes.AutoUpdateSetting, request: Request) -> Dict[str, Any]:
    """Turn that computer's automatic updates on or off."""
    return await _ask(request, host_key, "auto", body.enabled)


@asked.post("/{host_key}/check")
async def computer_check(host_key: str, request: Request) -> Dict[str, Any]:
    """Ask that computer's app to check the feed now."""
    return await _ask(request, host_key, "check")


@asked.post("/{host_key}/install")
async def computer_install(host_key: str, request: Request) -> Dict[str, Any]:
    """Ask that computer's app to install the update and restart."""
    return await _ask(request, host_key, "install")
