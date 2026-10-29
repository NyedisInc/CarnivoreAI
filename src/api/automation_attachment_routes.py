from __future__ import annotations

import asyncio
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from src.api.auth import require_auth
from src.api.automation_routes import get_store
from src.core.automations import attachments
from src.core.automations.models import AutomationNotFound

router = APIRouter(prefix="/automations", tags=["automations"], dependencies=[Depends(require_auth)])


@router.get("/runs/{run_id}/attachments/{name}")
async def get_attachment(request: Request, run_id: str, name: str):
    """One attachment as a download. 404 unless the run exists and ``name`` is in its stored list; the path is built only after that
    lookup and refused unless its real path is a regular file inside the run's folder.

    Example: ``GET /automations/runs/run_ab/attachments/report.csv`` answers the bytes with ``Content-Disposition: attachment``.
    """
    store = get_store(request)
    try:
        run = await asyncio.to_thread(store.run, run_id)
    except AutomationNotFound as exc:
        raise HTTPException(404, detail={"code": "not_found"}) from exc
    if name not in {item.get("name") for item in run.get("attachments") or ()}:
        raise HTTPException(404, detail={"code": "not_found"})
    path = await asyncio.to_thread(attachments.resolve, store.attachments_root, run["run_id"], name)
    if path is None:
        raise HTTPException(404, detail={"code": "not_found"})
    return FileResponse(path, media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
