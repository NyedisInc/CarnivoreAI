
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

    Description: name, description, the schedule only when the task file
      records one, and the last recorded run. A missing folder is
      ``absent``, an unreadable one ``unreadable``; both are 200s. For the
      owner, each paired Mac's own tasks follow under its host; a peer
      token gets this Mac's list only (one level, F8), and the owning Mac
      is the only one that runs a task.
    Inputs: none.
    Output: ScheduledTasksList.
    Example: GET /api/v1/scheduled-tasks
    """
    local = await asyncio.to_thread(scheduled_tasks.READER.read)
    if principal.is_peer:
        return local
    return await peer_scheduled_tasks.merge(local, peer_auth.open_db, peer_links.LINKS)
