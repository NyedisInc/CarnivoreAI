
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from src.api.auth import require_auth
from src.core.automations import command_allowlist

router = APIRouter(prefix="/automation-commands", tags=["automations"], dependencies=[Depends(require_auth)])


class CommandList(BaseModel):

    model_config = ConfigDict(extra="forbid")
    commands: List[str]


def _shape(commands: List[str]) -> Dict[str, Any]:
    return {"commands": commands, "max_entries": command_allowlist.LIST_MAX, "max_length": command_allowlist.ENTRY_MAX}


@router.get("")
async def get_commands() -> Dict[str, Any]:
    """The allow-list. Output: {commands, max_entries, max_length}."""
    return _shape(await asyncio.to_thread(command_allowlist.read))


@router.put("")
async def put_commands(body: CommandList) -> Dict[str, Any]:
    """Replace the allow-list. Inputs: body (CommandList). Output: the list stored."""
    try:
        return _shape(await asyncio.to_thread(command_allowlist.save, body.commands))
    except command_allowlist.CommandListInvalid as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)[:200]}) from exc
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=503, detail={"code": "config_unwritable", "error": type(exc).__name__}) from exc
