
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from src.api.error_response import api_error
from src.api.auth import require_auth
from src.core.automations import scheduler_log

router = APIRouter(prefix="/automation-log", tags=["automations"], dependencies=[Depends(require_auth)])


def _config_path() -> Path:
    from src.config import settings  # noqa: PLC0415

    return Path(settings.auth_config_file).expanduser()


@router.get("")
async def read_log(automation_id: Optional[str] = Query(None, pattern=r"^aut_[0-9a-f]{32}$"),
                   limit: int = Query(200, ge=1, le=1000)) -> Dict[str, Any]:
    """Recent scheduler log lines, newest first. Inputs: automation_id (optional filter); limit. Output: {lines, path, settings}."""
    lines = await asyncio.to_thread(scheduler_log.LOG.read, automation_id, limit)
    return {"lines": lines, "file": scheduler_log.FILENAME, "settings": scheduler_log.LOG.settings.model_dump()}


@router.get("/settings")
async def get_log_settings() -> Dict[str, Any]:
    """The rotation in force. Output: {rotate, max_mb, keep}."""
    return scheduler_log.LOG.settings.model_dump()


@router.put("/settings")
async def put_log_settings(body: scheduler_log.LogSettings) -> Dict[str, Any]:
    """Store and apply the rotation. Inputs: body (LogSettings). Output: the settings in force. 503 when config.json is unwritable."""
    try:
        saved = await asyncio.to_thread(scheduler_log.save_settings, _config_path(), body)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise api_error(503, "config_unwritable", exc) from exc
    return saved.model_dump()
