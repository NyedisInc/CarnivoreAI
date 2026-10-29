
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from src.api.auth import require_auth
from src.config import settings
from src.core.db import DatastoreUnreadableError, db_path_for
from src.core.db_reuse.core_read import lend_pooled_or_raise
from src.core.federation import discovery as disc
from src.core.hosts import roster_push, store

logger = structlog.get_logger()

router = APIRouter(prefix="/federation", tags=["federation"])


class AdvertiseRequest(BaseModel):
    """PATCH body: ``advertise`` and/or ``pack_name`` (the opt-in name a main advertises as ``pn``; null or "" clears it)."""

    advertise: Optional[bool] = None
    pack_name: Optional[str] = None


def _service(request: Request) -> disc.Discovery:
    svc = getattr(request.app.state, "federation_discovery", None)
    if svc is None:
        raise HTTPException(503, {"code": "discovery_unavailable",
                                  "detail": "federation discovery is not running"})
    return svc


def _known_targets() -> List[str]:
    try:
        with closing(lend_pooled_or_raise(db_path_for(settings.get_state_dir()))) as conn:
            return [h.ssh_target for h in store.list_hosts(conn) if h.ssh_target]
    except (DatastoreUnreadableError, store.HostsUnavailable, sqlite3.DatabaseError, OSError):
        return []


def _settings_body(svc: disc.Discovery) -> Dict[str, Any]:
    return {"advertise": svc.advertising_wanted, "pack_name": disc.read_pack_name(Path(settings.auth_config_file).expanduser()),
            "state": svc.state, "browse_state": svc.browse_state}


@router.get("/discovered")
async def list_discovered(request: Request, _: bool = Depends(require_auth)) -> Dict[str, Any]:
    """Other Macs advertising ``_carnivore._tcp`` on this network."""
    svc = _service(request)
    targets = await run_in_threadpool(_known_targets)
    return {"discovered": svc.discovered(targets), **_settings_body(svc)}


@router.get("/settings")
async def get_settings(request: Request, _: bool = Depends(require_auth)) -> Dict[str, Any]:
    """The advertise flag and the discovery state."""
    return _settings_body(_service(request))


@router.patch("/settings")
async def patch_settings(
    body: AdvertiseRequest, request: Request, _: bool = Depends(require_auth)
) -> Dict[str, Any]:
    """Persist the advertise flag and/or the pack name, then register or withdraw at once.

    422 ``bad_pack_name`` for a name outside ``[A-Za-z0-9 ._-]`` or over 32 characters (never mangled); null or "" clears it.
    """
    svc = _service(request)
    path = Path(settings.auth_config_file).expanduser()
    fields = body.model_fields_set
    if not fields & {"advertise", "pack_name"} or (body.advertise is None and "advertise" in fields):
        raise HTTPException(422, {"code": "bad_request", "detail": "send advertise and/or pack_name"})
    try:
        name = disc.validate_pack_name(body.pack_name) if "pack_name" in fields else None
    except ValueError:
        raise HTTPException(422, {"code": "bad_pack_name", "detail": "use letters, digits, spaces, dots, dashes and underscores, up to 32"}) from None
    try:
        await run_in_threadpool(disc.write_settings, path, body.advertise, name, "pack_name" in fields)
    except (OSError, ValueError) as exc:
        logger.warning("federation_advertise_persist_failed", error=str(exc))
        raise HTTPException(500, {"code": "settings_write_failed",
                                  "detail": "could not write config"})
    if body.advertise is not None:
        svc.set_advertise(body.advertise)
    if "pack_name" in fields:
        roster_push.announce()
        svc.refresh_link_port()
    return _settings_body(svc)
