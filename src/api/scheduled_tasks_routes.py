"""App-level scheduled tasks: ``GET /api/v1/scheduled-tasks`` (issue #893).

ONE READ-ONLY, AUTHENTICATED ENDPOINT for the home screen's scheduled
tasks widget and a future MCP tool. It reads ``~/.claude/scheduled-tasks``
and the heads of the transcripts under ``~/.claude/projects``, bounded and
cached (``src/core/scheduled_tasks.py``), off the event loop. No write.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from src.api import peer_auth
from src.api.peer_auth import Principal, require_peer_sessions
from src.core import scheduled_tasks
from src.core.federation import peer_links, peer_scheduled_tasks
from src.models.scheduled_tasks import ScheduledTasksList

router = APIRouter()


@router.get(
    "/scheduled-tasks",
    response_model=ScheduledTasksList,
)
async def list_scheduled_tasks(principal: Principal = Depends(require_peer_sessions)) -> ScheduledTasksList:
    """List the Claude desktop app's scheduled tasks, with what is recorded.
    """
    local = await asyncio.to_thread(scheduled_tasks.READER.read)
    if principal.is_peer:
        return local
    return await peer_scheduled_tasks.merge(local, peer_auth.open_db, peer_links.LINKS)
