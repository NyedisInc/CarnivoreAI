
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from src.api.auth import require_auth
from src.core.crosstalk.fork import engine
from src.core.mcp.caller import AgentCaller
from src.core.mcp.common import ToolError
from src.core.mcp.protocol import BatchView

router = APIRouter(tags=['crosstalk'], dependencies=[Depends(require_auth)])


async def fork_for_caller(request: Request, body: engine.ForkRequest,
                          caller: AgentCaller, *, owner_approved: bool = False) -> dict:
    try:
        return await engine.fork(BatchView(request.app.state.session_manager, request.app),
                                 caller, body, owner_approved=owner_approved)
    except ToolError as exc:
        raise HTTPException(status_code=409, detail={'code': 'fork_refused', 'message': str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={'code': 'fork_history_unavailable', 'message': str(exc)}) from exc


@router.post('/sessions/{session_id}/fork-to', status_code=201)
async def fork_to(request: Request, session_id: str, body: engine.ForkRequest) -> dict:
    """Fork an exact local pane id after owner authentication."""
    if body.source not in ('self', session_id):
        raise HTTPException(status_code=400, detail='body source must match the path session id')
    request_body = body.model_copy(update={'source': session_id})
    caller = AgentCaller(session_id='owner', tmux_name='owner', current_session_id='owner', token_name='owner')
    return await fork_for_caller(request, request_body, caller, owner_approved=True)
