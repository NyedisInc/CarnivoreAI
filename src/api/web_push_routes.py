
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

from src.api.auth import require_auth
from src.config import settings
from src.core.notifications import kind_specs
from src.core.notifications.destinations.service import get_service
from src.core.web_push import vapid
from src.core.web_push.endpoints import endpoint_allowed
from src.core.web_push.store import public_view
from src.core.web_push.wiring import sender_for

logger = structlog.get_logger()
router = APIRouter(prefix="/push", tags=["push"], dependencies=[Depends(require_auth)])


class Keys(BaseModel):
    """A subscription's keys as the browser's ``toJSON()`` gives them."""

    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class SubscribeBody(BaseModel):
    """``PushSubscription.toJSON()``; the server, never the client, links a subscription to a device."""

    endpoint: str = Field(max_length=2048)
    keys: Keys

    @field_validator("endpoint")
    @classmethod
    def _known_service(cls, value: str) -> str:
        if not endpoint_allowed(value):
            raise ValueError("endpoint is not a known push service")
        return value

    @field_validator("keys")
    @classmethod
    def _key_shapes(cls, keys: Keys) -> Keys:
        try:
            point = vapid.b64url_decode(keys.p256dh)
            secret = vapid.b64url_decode(keys.auth)
        except ValueError as exc:
            raise ValueError("keys are not base64url") from exc
        if len(point) != 65 or point[0] != 4 or len(secret) != 16:
            raise ValueError("keys have the wrong length")
        return keys


@router.get("/vapid-public-key")
async def vapid_public_key() -> Dict[str, str]:
    """The public key a browser subscribes with. Output: {key}."""
    return {"key": await asyncio.to_thread(vapid.public_key_b64, settings.get_state_dir())}


@router.post("/subscriptions", status_code=201)
async def add_subscription(body: SubscribeBody, request: Request) -> Dict[str, Any]:
    """Store (or refresh) this browser's subscription. Output: its public view.

    The paired device it belongs to is the one the link gate verified from the ``__Host-cc_link`` cookie (the
    request scope's ``link_device``), never anything the client sends; a subscription made on the Mac itself has none.
    """
    store = sender_for(request.app.state).store
    device = request.scope.get("link_device") if request.scope.get("via_link") else None
    known = {r["id"] for r in await asyncio.to_thread(store.list)}
    try:
        row = await asyncio.to_thread(store.add, body.endpoint, body.keys.p256dh, body.keys.auth, device)
    except OverflowError as exc:
        raise HTTPException(status_code=409, detail="too many push subscriptions") from exc
    manager = getattr(request.app.state, "phone_link", None)
    if device and manager is not None and device not in {d.id for d in manager.pairing.devices()}:
        await asyncio.to_thread(store.remove_for_device, device)
        raise HTTPException(status_code=403, detail="this device is no longer paired")
    if row["id"] not in known:
        await _seed_new_subscription(request, row["id"])
    return public_view(row)


async def _seed_new_subscription(request: Request, sub_id: str) -> None:
    dest_id = kind_specs.webpush_destination_id(sub_id)
    try:
        await get_service(request.app.state).destinations.seed_destination_ticks(dest_id, kind_specs.KIND_WEBPUSH)
    except (OSError, ValueError) as exc:
        logger.warning("web_push_seed_ticks_failed", error_type=type(exc).__name__)


@router.get("/subscriptions")
async def list_subscriptions(request: Request) -> Dict[str, List[Dict[str, Any]]]:
    """Every subscription with its last push result. Output: {subscriptions}."""
    rows = await asyncio.to_thread(sender_for(request.app.state).store.list)
    return {"subscriptions": [public_view(r) for r in rows]}


@router.delete("/subscriptions/{sub_id}", status_code=204)
async def delete_subscription(sub_id: str, request: Request) -> Response:
    """Forget one subscription; 404 when it does not exist."""
    if not await asyncio.to_thread(sender_for(request.app.state).store.remove, sub_id):
        raise HTTPException(status_code=404, detail="no such subscription")
    return Response(status_code=204)


@router.post("/test")
async def send_test(request: Request) -> Dict[str, List[Dict[str, Any]]]:
    """Send one fixed "approval needed" to every subscription now, ignoring the 60 s wait. 429 inside a 5 s cooldown. Output: {sent}."""
    sent = await sender_for(request.app.state).notify_test()
    if sent is None:
        raise HTTPException(status_code=429, detail="test push was just sent")
    return {"sent": sent}
