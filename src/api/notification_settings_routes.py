
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from src.api import notification_sync_routes as sync_routes
from src.api.auth import require_auth
from src.core.notifications import doc_model, links, routing_view, types
from src.core.notifications.destinations.service import NotificationService, get_service
from src.core.notifications.settings_doc import ticks, view

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)])


class PauseBody(BaseModel):
    """``PUT /settings``: the local pause switch."""

    model_config = ConfigDict(extra="forbid")

    paused: bool


class TickBody(BaseModel):
    """``PUT /ticks``: one matrix cell; ``scope`` is optional (see the contract)."""

    model_config = ConfigDict(extra="forbid")

    column: str
    type_id: str
    value: bool
    scope: Optional[str] = None


class DefaultBody(BaseModel):
    """``PUT /defaults``: one type's global default tick."""

    model_config = ConfigDict(extra="forbid")

    type_id: str
    value: bool


def _invalid(detail: str) -> HTTPException:
    return HTTPException(422, {"error": detail})


def settings_body(service: NotificationService, link: Dict[str, str], sync: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    doc = service.docs.snapshot()
    statuses = routing_view.current_statuses()
    destinations = []
    for dest in service.routing.view().destinations():
        item = view.destination_dict(doc, dest.id)
        if item is not None:
            status = statuses.get(dest.id)
            item["status"] = view.status_json(item, status)
            destinations.append(item)
    columns = [d["id"] for d in destinations]
    columns += [d.id for d in service.routing.view().destinations() if d.kind in ("webpush", "apns")]
    rows = types.ordered_types()
    return {
        "revision": int(doc["rev"]), "paused": view.paused(doc), "link": link,
        "defaults": {r.id: view.default_tick(doc, r.id) for r in rows},
        "screen": {r.id: view.cell(doc, doc_model.COL_SCREEN, r.id).as_dict() for r in rows},
        "ticks": {c: {r.id: view.cell(doc, c, r.id).as_dict() for r in rows} for c in columns},
        "destinations": destinations, "sync": sync,
    }


async def _body(request: Request) -> Dict[str, Any]:
    service = get_service(request.app.state)
    result = await links.resolver.resolve(getattr(request.app.state, "phone_link", None))
    link = {"kind": result.kind, "base": result.base, "reason": result.reason}
    sync = await sync_routes.sync_summary(request.app.state)
    body = await asyncio.to_thread(settings_body, service, link, sync)
    doc = await asyncio.to_thread(service.docs.snapshot)
    body["destinations"] = [await service.destinations.reported(d, doc) for d in body["destinations"]]
    return body


@router.get("/settings")
async def get_settings(request: Request) -> Dict[str, Any]:
    """Effective settings: pause switch, link kind, defaults, screen and per-destination cells, destinations."""
    return await _body(request)


@router.put("/settings")
async def put_settings(body: PauseBody, request: Request) -> Dict[str, Any]:
    """Set the local pause switch (per computer, never synced); returns the settings body."""
    service = get_service(request.app.state)
    await _write(ticks.set_paused, service.docs, body.paused)
    return await _body(request)


async def _write(fn: Any, *args: Any) -> Any:
    try:
        return await asyncio.to_thread(fn, *args)
    except ticks.LockedCell:
        raise HTTPException(409, {"error": "locked"}) from None
    except ticks.UnknownDestination:
        raise HTTPException(404, {"error": "unknown_destination"}) from None
    except ValueError as exc:
        if str(exc) == "not resettable":
            raise HTTPException(409, {"error": "not_resettable"}) from None
        raise _invalid("bad_value") from None
    except OSError:
        raise HTTPException(503, {"error": "write_failed"}) from None


@router.put("/ticks")
async def put_tick(body: TickBody, request: Request) -> Dict[str, Any]:
    """Set one cell. 409 locked, 404 unknown destination, 422 bad type, column or scope."""
    service = get_service(request.app.state)
    cell = await _write(ticks.put_tick, service.docs, body.column, body.type_id, body.value, body.scope)
    return {"revision": service.docs.revision, "cell": cell.as_dict()}


@router.put("/defaults")
async def put_default(body: DefaultBody, request: Request) -> Dict[str, Any]:
    """Set a type's global default tick (what new destinations copy)."""
    service = get_service(request.app.state)
    defaults = await _write(ticks.put_default, service.docs, body.type_id, body.value)
    return {"revision": service.docs.revision, "defaults": defaults}


@router.delete("/overrides")
async def delete_override(request: Request, path: str = Query(...)) -> Dict[str, Any]:
    """Reset a pinned path to its global value. 409 for a local-scope destination, 422 for a bad path."""
    service = get_service(request.app.state)
    reset = await _write(ticks.reset_override, service.docs, path)
    return {"revision": service.docs.revision, "reset": reset}
