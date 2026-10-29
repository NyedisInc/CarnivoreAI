
from __future__ import annotations

import sqlite3
from typing import Any, Dict

import structlog
from fastapi import UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from src.cplugs.huddle import files, service, task_files
from src.cplugs.huddle.routes import Ctx, router, run_store
from src.cplugs.sdk import CplugContext
from src.cplugs.sdk.uploads import read_validated_upload

logger = structlog.get_logger()

SAFE_HEADERS = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'; img-src 'self'",
                "Cache-Control": "private, max-age=3600"}


@router.post("/items/{item_id}/files")
async def upload_file(item_id: int, file: UploadFile, ctx: CplugContext = Ctx) -> Dict[str, Any]:
    await run_store(lambda: service.store(ctx).item(item_id))
    data, name = await read_validated_upload(file)
    saved = await run_store(lambda: files.save(ctx.storage, item_id, name, data))
    try:
        await run_in_threadpool(files.sweep_orphans, ctx.storage)
    except (OSError, sqlite3.Error) as exc:
        logger.warning("task_manager_orphan_sweep_failed", error=str(exc))
    logger.info("task_manager_file_uploaded", item=item_id, size=saved["size"])
    return saved


@router.get("/items/{item_id}/files/{file_id}")
async def get_file(item_id: int, file_id: str, ctx: CplugContext = Ctx) -> FileResponse:
    """One stored file's bytes. Output: the file (``inline`` for an image, ``attachment`` otherwise)."""
    path = await run_store(lambda: files.locate(ctx.storage, item_id, file_id, task_files.search_dirs(item_id)))
    name = files.name_of(path.name)
    return FileResponse(path, media_type=files.mime_of(name),
                        headers={**SAFE_HEADERS, "Content-Disposition": f'{files.disposition(name)}; filename="{name}"'})
