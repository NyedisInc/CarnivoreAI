
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam

from src.api.auth import require_auth
from src.core.pipeline import contract as C
from src.core.pipeline import plugin_db, runtime
from src.core.pipeline import rebuild as new_rebuild

router = APIRouter(tags=["pipeline"], dependencies=[Depends(require_auth)])


@router.get("/pipeline/status")
async def pipeline_status() -> Dict[str, Any]:
    """The engine's state (``runtime.status``). Output: dict. Reads no file and takes no lock."""
    return runtime.status()


@router.post("/pipeline/plugins/{plugin_id}/rebuild", status_code=202)
async def rebuild_plugin(plugin_id: str = PathParam(..., pattern=C.ID_PATTERN)) -> Dict[str, Any]:
    """Rebuild one plugin from the files on disk. Output: {plugin, dropped_bytes, files_marked}."""
    try:
        return await asyncio.to_thread(runtime.rebuild_plugin, plugin_id)
    except new_rebuild.UnknownPlugin as exc:
        raise HTTPException(status_code=404, detail=f"no such plugin: {plugin_id}") from exc
    except plugin_db.PluginUnavailable as exc:
        raise HTTPException(status_code=409, detail=f"rebuild refused, the old database was kept: {exc}") from exc
