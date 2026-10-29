
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from src.api.error_response import api_error, refusal_error
from src.api.auth import require_auth
from src.core.automations import command_allowlist

router = APIRouter(prefix="/automation-commands", tags=["automations"], dependencies=[Depends(require_auth)])


class CommandList(BaseModel):
    """The body of a PUT: the whole list, in the order the owner wants it shown."""

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
        raise refusal_error(exc, status=422) from exc
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise api_error(503, "config_unwritable", exc) from exc
