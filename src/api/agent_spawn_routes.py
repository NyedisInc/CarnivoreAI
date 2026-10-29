
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.core.crosstalk import spawn
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.mcp.protocol import BatchView

router = APIRouter(tags=['agents'], dependencies=[Depends(require_auth)])


async def spawn_for_caller(request: Request, body: spawn.SpawnRequest,
                           caller: AgentCaller, *, owner_approved: bool = False) -> dict:
    view = BatchView(request.app.state.session_manager, request.app)
    try:
        return await spawn.spawn(view, caller, body, owner_approved=owner_approved)
    except ToolError as exc:
        raise HTTPException(status_code=409, detail={'code': 'spawn_refused', 'message': str(exc)}) from exc


@router.post('/agents/spawn')
async def agent_spawn(request: Request, body: spawn.SpawnRequest) -> dict:
    if not body.parent:
        raise HTTPException(status_code=422, detail={'code': 'parent_required',
                                                      'message': 'parent is required for the owner route'})
    infos = await request.app.state.session_manager.list_session_infos()
    parent = next((info for info in infos if info.session.id == body.parent), None)
    if parent is None or not parent.tmux_session:
        raise HTTPException(status_code=409, detail={'code': 'parent_unavailable'})
    caller = AgentCaller(session_id=parent.session.id, tmux_name=parent.tmux_session,
                         current_session_id=parent.session.id)
    return await spawn_for_caller(request, body, caller, owner_approved=True)
