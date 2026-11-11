
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from src.api.auth import require_auth
from src.api.error_response import api_error
from src.core import resource_push
from src.core.pack.globalsync import wiring
from src.core.pack.globalsync.store import clean_settings
from src.core.pack.machines import runtime as machines_runtime
from src.core.resource_push import topics

logger = structlog.get_logger()
router = APIRouter(prefix="/pack/global-sync", tags=["pack-global-sync"], dependencies=[Depends(require_auth)])


class SettingsBody(BaseModel):
    """A partial settings document; only the fields sent change."""

    model_config = ConfigDict(extra="forbid")

    enabled: Optional[StrictBool] = None
    auto: Optional[StrictBool] = None
    claude: Optional[StrictBool] = None
    codex: Optional[StrictBool] = None


class SyncBody(BaseModel):
    """Which computers to sync now (all eligible ones when empty)."""

    model_config = ConfigDict(extra="forbid")

    install_ids: List[str] = Field(default_factory=list, max_length=64)


def _sync() -> wiring.GlobalSync:
    if wiring.SYNC is None:
        raise HTTPException(503, {"code": "pack_unavailable", "detail": "the Pack is not running"})
    return wiring.SYNC


@router.get("")
async def get_global_sync() -> Dict[str, Any]:
    """The settings and the per-computer state. Example: GET /api/v1/pack/global-sync."""
    return await asyncio.to_thread(_sync().snapshot)


@router.put("")
async def put_global_sync(body: SettingsBody, request: Request) -> Dict[str, Any]:
    """Change the settings. Turning the sync on (or a harness on) sends to every computer that passes its gates; auto sync arms the watch."""
    sync, wired = _sync(), machines_runtime.wiring()
    if wired is None:
        raise HTTPException(503, {"code": "pack_unavailable", "detail": "the Pack machine layer is not running"})
    before = sync.settings()
    after = clean_settings({**before, **body.model_dump(exclude_none=True)})
    try:
        await asyncio.to_thread(wired.state.save_global_sync, after)
    except (OSError, ValueError) as exc:
        raise api_error(500, "config_unwritable", exc) from exc
    logger.info("pack_global_sync_settings", enabled=after["enabled"], auto=after["auto"])
    resource_push.notify(topics.PACK_GLOBAL_SYNC)
    if wiring.WATCH is not None:
        await wiring.WATCH.rearm()
    if after["enabled"] and after != before:
        wiring.spawn(sync.sync())
    return await asyncio.to_thread(sync.snapshot)


@router.post("/sync")
async def post_sync(body: SyncBody, request: Request) -> Dict[str, Any]:
    """Sync now: build one bundle and send it to each computer that passes its gates. Output: ``{results: {install id: outcome}}``. Raises 409 ``sync_off`` / ``not_main``."""
    sync = _sync()
    if not sync.settings().get("enabled"):
        raise HTTPException(409, {"code": "sync_off", "detail": "turn the global setup sync on first"})
    if not await asyncio.to_thread(sync.is_main):
        raise HTTPException(409, {"code": "not_main", "detail": "only the Pack's main computer sends its setup"})
    results = await sync.sync(body.install_ids or None, force=True)
    return {"results": results}
