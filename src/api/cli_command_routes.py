
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends

from src.api.auth import require_auth
from src.config import settings
from src.core.cli_command import service

router = APIRouter(prefix="/cli-command", tags=["cli-command"], dependencies=[Depends(require_auth)])


@router.get("")
async def get_cli_command() -> Dict[str, str]:
    """The command's link state, paths and the copyable manual command."""
    return await asyncio.to_thread(service.status_body, settings.get_state_dir())


@router.post("/install")
async def install_cli_command() -> Dict[str, Any]:
    """Write the shim and link it into /usr/local/bin (one admin prompt when needed)."""
    return await asyncio.to_thread(service.install, settings.get_state_dir())
