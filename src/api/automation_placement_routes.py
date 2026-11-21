
from __future__ import annotations

import asyncio
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict

from src.api.auth import require_auth, security
from src.api.automation_routes import get_store, refuse
from src.api.error_response import api_error, refusal_error
from src.core.api_keys.store import is_api_key
from src.core.automations import models as m
from src.core.pack.jobs.types import JobError
from src.core.pack.session_place import automation as placement_store

router = APIRouter(prefix="/automations", tags=["automations"], dependencies=[Depends(require_auth)])


class PlacementBody(BaseModel):
    """The choice: this computer, or auto (a pegged or lacking computer sends it to another)."""

    model_config = ConfigDict(extra="forbid")
    placement: Literal["here", "auto"]


async def _owner_only(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> None:
    if credentials is not None and is_api_key(credentials.credentials):
        raise api_error(403, "auto_owner_only")


async def _target(request: Request, automation_id: str) -> Dict[str, Any]:
    try:
        return (await asyncio.to_thread(get_store(request).get, automation_id))["target"]
    except m.AutomationNotFound as exc:
        raise refuse(exc) from exc


@router.get("/{automation_id}/placement")
async def get_placement(request: Request, automation_id: str) -> Dict[str, Any]:
    """The automation's computer choice. Output: {placement: "here"|"auto", applies}; ``applies`` is false for a kind auto never places.

    Raises: 404 not_found, 503 jobs_not_ready.
    """
    target = await _target(request, automation_id)
    try:
        word = await asyncio.to_thread(placement_store.get, automation_id)
    except JobError as exc:
        raise refusal_error(exc) from exc
    return {"placement": word, "applies": placement_store.applies(target)}


@router.put("/{automation_id}/placement", dependencies=[Depends(_owner_only)])
async def put_placement(request: Request, automation_id: str, body: PlacementBody) -> Dict[str, Any]:
    """Set the choice. Body: {placement: "here"|"auto"}. Output: as GET. The automation itself is not touched (its revision stays).

    Raises: 404 not_found, 422 placement_unsupported (auto on a kind that always stays here), 503 jobs_not_ready.
    """
    target = await _target(request, automation_id)
    applies = placement_store.applies(target)
    if body.placement == placement_store.AUTO and not applies:
        raise api_error(422, "placement_unsupported")
    try:
        word = await asyncio.to_thread(placement_store.put, automation_id, body.placement)
    except JobError as exc:
        raise refusal_error(exc) from exc
    return {"placement": word, "applies": applies}
