
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.api.error_response import api_error
from src.api.auth import require_auth
from src.core.notifications import routing_view
from src.core.notifications.destinations import extras as extras_mod
from src.core.notifications.destinations import secrets as secrets_mod
from src.core.notifications.destinations import store as store_mod
from src.core.notifications.destinations import validate
from src.core.notifications.destinations.service import get_service
from src.core.notifications.settings_doc import view
from src.core.notifications.settings_doc import ticks

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)])


class CreateBody(BaseModel):
    """``POST /destinations``."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    name: str
    config: Dict[str, Any] = {}
    secrets: Dict[str, Any] = {}
    scope: str = "global"
    enabled: bool = True
    allow_private: Optional[bool] = None
    allow_plain_http: Optional[bool] = None


class PatchBody(BaseModel):
    """``PATCH /destinations/{id}``: every field optional; a blank secret stays untouched."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None
    secrets: Optional[Dict[str, Any]] = None
    scope: Optional[str] = None
    allow_private: Optional[bool] = None
    allow_plain_http: Optional[bool] = None


class ExtrasBody(BaseModel):
    """``PUT /destinations/{id}/extras``: a partial change; ``quiet`` and ``reminder_minutes`` accept null."""

    model_config = ConfigDict(extra="forbid")

    away: Optional[bool] = None
    quiet: Optional[Dict[str, str]] = None
    reminder_minutes: Optional[int] = None
    projects: Optional[list] = None
    details: Optional[bool] = None
    scope: Optional[str] = None


def _with_status(item: Dict[str, Any]) -> Dict[str, Any]:
    status = routing_view.current_statuses().get(item["id"])
    return {**item, "status": view.status_json(item, status)}


def _errors(exc: Exception) -> HTTPException:
    if isinstance(exc, validate.InvalidDestination):
        return api_error(422, "destination_invalid", exc, extra={"fields": exc.fields})
    if isinstance(exc, (store_mod.UnknownDestination, ticks.UnknownDestination)):
        return api_error(404, "destination_unknown", exc)
    if isinstance(exc, store_mod.DestinationLimit):
        return api_error(409, "destination_limit", exc)
    if isinstance(exc, store_mod.KeychainUnavailable):
        return api_error(503, "destination_keychain_unavailable", exc)
    if isinstance(exc, extras_mod.DetailsNotAllowed):
        return api_error(422, "destination_details_not_allowed", exc)
    if isinstance(exc, secrets_mod.SecretTooLarge):
        return api_error(422, "destination_secret_too_large", exc)
    if isinstance(exc, secrets_mod.InvalidFields):
        return api_error(422, "destination_invalid_secret_fields", exc)
    if isinstance(exc, ValueError):
        return api_error(422, "destination_bad_value", exc)
    return api_error(503, "destination_write_failed", exc)


_HANDLED = (validate.InvalidDestination, store_mod.UnknownDestination, ticks.UnknownDestination,
            store_mod.DestinationLimit, store_mod.KeychainUnavailable, extras_mod.DetailsNotAllowed, secrets_mod.SecretTooLarge, secrets_mod.InvalidFields,
            ValueError, OSError)


@router.get("/destinations")
async def list_destinations(request: Request) -> Dict[str, Any]:
    """Every destination, with status; secrets only as ``{"set": bool}``."""
    items = await get_service(request.app.state).destinations.list()
    return {"destinations": [_with_status(i) for i in items]}


@router.post("/destinations", status_code=201)
async def create_destination(body: CreateBody, request: Request) -> Dict[str, Any]:
    """Create a destination; ticks are seeded from the global defaults. A webhook's generated signing secret
    is in this response only."""
    try:
        made = await get_service(request.app.state).destinations.create(
            body.kind, body.name, body.config, body.secrets, scope=body.scope, enabled=body.enabled,
            allow_private=body.allow_private,
            allow_plain_http=body.allow_plain_http)
    except _HANDLED as exc:
        raise _errors(exc) from None
    out: Dict[str, Any] = {"destination": _with_status(made.destination)}
    if made.signing_secret:
        out["signing_secret"] = made.signing_secret
    return out


@router.patch("/destinations/{dest_id}")
async def patch_destination(dest_id: str, body: PatchBody, request: Request) -> Dict[str, Any]:
    """Change name, enabled, public config or secrets (blank means untouched); ``scope: local`` pins ``enabled``."""
    if body.scope not in (None, "local"):
        raise HTTPException(422, {"error": "bad_value"})
    try:
        item = await get_service(request.app.state).destinations.update(
            dest_id, name=body.name, enabled=body.enabled, config=body.config, secret_patch=body.secrets,
            local_only=body.scope == "local", allow_private=body.allow_private,
            allow_plain_http=body.allow_plain_http)
    except _HANDLED as exc:
        raise _errors(exc) from None
    return {"destination": _with_status(item)}


@router.delete("/destinations/{dest_id}")
async def delete_destination(dest_id: str, request: Request) -> Dict[str, bool]:
    """Tombstone the destination and delete its Keychain item."""
    try:
        await get_service(request.app.state).destinations.delete(dest_id)
    except _HANDLED as exc:
        raise _errors(exc) from None
    return {"deleted": True}


@router.put("/destinations/{dest_id}/extras")
async def put_extras(dest_id: str, body: ExtrasBody, request: Request) -> Dict[str, Any]:
    """Partial extras change (only the fields sent). 422 ``details_not_allowed`` for SMS-like kinds."""
    sent = {k: v for k, v in body.model_dump().items() if k != "scope" and k in body.model_fields_set}
    service = get_service(request.app.state)
    try:
        await asyncio.to_thread(extras_mod.set_extras, service.docs, dest_id, sent, body.scope)
        return {"destination": _with_status(await service.destinations.get(dest_id))}
    except _HANDLED as exc:
        raise _errors(exc) from None
