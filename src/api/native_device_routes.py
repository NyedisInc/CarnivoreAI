
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from src.api.auth import require_auth
from src.core.native_push import wiring
from src.core.native_push.store import public_view
from src.core.notifications.destinations import secrets as secret_store
from src.core.web_push import vapid

logger = structlog.get_logger()
router = APIRouter(prefix="/native-devices", tags=["native-devices"], dependencies=[Depends(require_auth)])

_TOKEN = re.compile(r"[0-9a-fA-F]{64,200}")
_BUNDLE = re.compile(r"[A-Za-z0-9.-]{1,155}")


def require_link_device(request: Request) -> str:
    device = request.scope.get("link_device") if request.scope.get("via_link") else None
    if not device:
        raise HTTPException(status_code=403, detail="register from a paired phone")
    return str(device)


class RegisterBody(BaseModel):
    """What the app sends. The link device is never read from here (unknown fields are ignored)."""

    platform: Literal["ios"]
    token: str = Field(max_length=200)
    environment: Literal["sandbox", "production"]
    bundle_id: str = Field(max_length=155)
    app_version: str = Field(max_length=40)
    payload_key: str = Field(max_length=100)

    @field_validator("token")
    @classmethod
    def _token_shape(cls, value: str) -> str:
        if not _TOKEN.fullmatch(value):
            raise ValueError("token is not an APNs device token")
        return value.lower()

    @field_validator("bundle_id")
    @classmethod
    def _bundle_shape(cls, value: str) -> str:
        if not _BUNDLE.fullmatch(value):
            raise ValueError("bundle_id is not a bundle id")
        return value

    @field_validator("payload_key")
    @classmethod
    def _key_shape(cls, value: str) -> str:
        try:
            raw = vapid.b64url_decode(value)
        except ValueError as exc:
            raise ValueError("payload_key is not base64url") from exc
        if len(raw) != 32:
            raise ValueError("payload_key must be 32 bytes")
        return value


@router.post("", status_code=201)
async def register_device(body: RegisterBody, request: Request, device: str = Depends(require_link_device)) -> Dict[str, Any]:
    """Register or refresh this phone's APNs token and payload key. Output: the row's public view."""
    state = request.app.state
    store = wiring.store_for(state)
    try:
        row, created = await asyncio.to_thread(store.upsert, device, body.platform, body.token, body.environment,
                                               body.bundle_id, body.app_version)
    except OverflowError as exc:
        raise HTTPException(status_code=409, detail="too many native devices for this phone") from exc
    try:
        await wiring.secrets_for(state).put(row["id"], {wiring.KEY_FIELD: body.payload_key})
    except secret_store.SecretError as exc:
        if created:
            await asyncio.to_thread(store.remove, row["id"])
        logger.warning("native_push_key_store_failed", error_type=type(exc).__name__)
        raise HTTPException(status_code=503, detail="the payload key could not be stored") from exc
    manager = getattr(state, "phone_link", None)
    if manager is not None and device not in {d.id for d in manager.pairing.devices()}:
        await wiring.remove_for_device(state, device)
        raise HTTPException(status_code=403, detail="this device is no longer paired")
    if created:
        await wiring.seed_new_device(state, row["id"])
    return public_view(row)


@router.get("")
async def list_devices(request: Request) -> Dict[str, List[Dict[str, Any]]]:
    """Every native device. Output: {devices}; no token, no key."""
    rows = await asyncio.to_thread(wiring.store_for(request.app.state).list)
    return {"devices": [public_view(r) for r in rows]}


@router.delete("/{row_id}", status_code=204)
async def delete_device(row_id: str, request: Request) -> Response:
    """Forget one native device and its payload key; 404 when it does not exist."""
    if not await asyncio.to_thread(wiring.store_for(request.app.state).remove, row_id):
        raise HTTPException(status_code=404, detail="no such native device")
    await wiring.delete_key(request.app.state, row_id)
    await wiring.drop_local_destination(request.app.state, row_id)
    return Response(status_code=204)
