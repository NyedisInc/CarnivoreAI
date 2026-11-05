
from __future__ import annotations

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_auth
from src.api.swarm_routes import NEEDS_PORT, _RosterBodies, _manager, _missing, _refused
from src.core import db
from src.core.swarm import views, waiting
from src.models.swarm import SwarmWaiting

router = APIRouter(prefix="/swarm", tags=["swarm"], dependencies=[Depends(require_auth)])


@router.get("/agents/{agent_id}/waiting", response_model=SwarmWaiting, dependencies=NEEDS_PORT)
async def get_waiting(agent_id: int, request: Request) -> Dict[str, Any]:
    """Everything waiting on the owner under this agent's chat: its own cards, its descendants', Review cards and inbox items.

    Output: SwarmWaiting. 404 for an unknown or torn-down agent, 503 when the datastore cannot be read.
    Example: GET /api/v1/swarm/agents/1/waiting -> {"agent_id": 1, "items": [...], "count": 3}
    """
    inbox: Any = getattr(request.app.state, "approvals_inbox", None)
    try:
        return await waiting.feed(agent_id, manager=_RosterBodies(_manager(request)), inbox=inbox)
    except views.AgentMissing:
        raise _missing() from None
    except (db.DatastoreUnreadableError, sqlite3.Error) as exc:
        _refused(exc)
