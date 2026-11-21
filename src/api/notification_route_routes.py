
from __future__ import annotations

import asyncio
import platform
from typing import Any, Dict, List, Mapping, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import require_auth
from src.core.notifications import doc_model, types
from src.core.notifications.destinations.service import NotificationService, get_service
from src.core.notifications.sync import runtime as sync_runtime, status as sync_status
from src.core.notifications.sync.peers import PeerInfo
from src.core.notifications.settings_doc import routes

router = APIRouter(prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_auth)])


class RouteBody(BaseModel):
    """``PUT /routes``: one cell (``computer`` x ``target``) for ``type_ids``."""

    model_config = ConfigDict(extra="forbid")

    type_ids: List[str] = Field(min_length=1, max_length=60)
    computer: str
    target: str
    value: bool


class MasterBody(BaseModel):
    """``PUT /master``: the master switch of ``type_ids``."""

    model_config = ConfigDict(extra="forbid")

    type_ids: List[str] = Field(min_length=1, max_length=60)
    value: bool


def _visible_types() -> List[types.NotifyType]:
    from src.config import settings  # noqa: PLC0415

    return [r for r in types.ordered_types() if r.id not in types.DEV_ONLY or settings.dev_shape_alerts]


def _self_identity(doc: Mapping[str, Any]) -> tuple[Optional[str], str]:
    from src.core.computers import runtime  # noqa: PLC0415

    rt = runtime.active()
    iid = doc_model.self_iid(doc) or (rt.iid if rt is not None else None)
    return iid, (rt.label if rt is not None and rt.label else platform.node().split(".")[0][:64] or "this computer")


def routes_body(doc: Mapping[str, Any], self_iid: str, self_label: str, peers: Sequence[PeerInfo], phone_paired: bool,
                rows: Sequence[types.NotifyType]) -> Dict[str, Any]:
    ordered = sorted(peers, key=lambda p: (p.label.lower(), p.install_id))
    computers = [{"install_id": self_iid, "label": self_label, "self": True, "online": True, "syncs": True, "hue": 0}]
    computers += [{"install_id": p.install_id, "label": p.label, "self": False, "online": p.connected,
                   "syncs": sync_status.is_enabled(doc, p.install_id) and p.speaks_sync, "hue": i}
                  for i, p in enumerate(ordered, start=1)]
    iids = [c["install_id"] for c in computers]
    return {
        "revision": int(doc["rev"]), "self": self_iid, "targets": ["app", "desk", "phone"], "computers": computers,
        "phone_paired": phone_paired,
        "types": {r.id: {"on": routes.master_on(doc, r.id),
                         "locked": {"phone": routes.is_locked(r.id, "phone"), "corner": routes.is_locked(r.id, "corner")},
                         "cells": routes.cells_for_type(doc, self_iid, iids, r.id)} for r in rows},
    }


async def _body(request: Request, service: NotificationService, skipped: Optional[List[str]] = None) -> Dict[str, Any]:
    doc = await asyncio.to_thread(service.docs.snapshot)
    iid, label = _self_identity(doc)
    if iid is None:
        raise HTTPException(503, {"error": "computers_unavailable"})
    manager = sync_runtime.current(request.app.state)
    peers = await manager.gateway.roster() if manager is not None else []
    phone = any(d.kind in ("webpush", "apns") for d in service.routing.view().destinations())
    body = routes_body(doc, iid, label, peers, phone, _visible_types())
    if skipped is not None:
        body["skipped"] = skipped
    return body


async def _guard(fn: Any, *args: Any) -> Any:
    try:
        return await asyncio.to_thread(fn, *args)
    except routes.UnknownComputer:
        raise HTTPException(404, {"error": "unknown_computer"}) from None
    except ValueError:
        raise HTTPException(422, {"error": "bad_value"}) from None
    except OSError:
        raise HTTPException(503, {"error": "write_failed"}) from None


@router.get("/routes")
async def get_routes(request: Request) -> Dict[str, Any]:
    """Every visible type's master switch, locks and per-computer cells, plus the computers and whether a phone is paired here."""
    return await _body(request, get_service(request.app.state))


@router.put("/routes")
async def put_routes(body: RouteBody, request: Request) -> Dict[str, Any]:
    """Write one cell for many types in one commit. 404 unknown_computer, 422 bad_value; locked types are skipped and listed."""
    service = get_service(request.app.state)
    doc = await asyncio.to_thread(service.docs.snapshot)
    iid, _ = _self_identity(doc)
    manager = sync_runtime.current(request.app.state)
    known = [p.install_id for p in await manager.gateway.roster()] if manager is not None else []
    skipped, _doc = await _guard(routes.put_routes, service.docs, body.type_ids, body.computer, body.target, body.value, iid, known)
    return await _body(request, service, skipped)


@router.put("/master")
async def put_master(body: MasterBody, request: Request) -> Dict[str, Any]:
    """Switch types on or off (a type or a whole group). Routes are untouched, so switching back on restores them. 422 bad_value."""
    service = get_service(request.app.state)
    await _guard(routes.put_master, service.docs, body.type_ids, body.value)
    return await _body(request, service)
