
from __future__ import annotations

from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from src.api.argent.status import feature_on
from src.api.auth import require_auth
from src.api.error_response import refusal_error
from src.api.remote_route_guard import refuse_remote
from src.core.argent import declare as declare_module
from src.core.argent import session_ref, timeline, work_items

router = APIRouter(tags=["argent"], dependencies=[Depends(require_auth)])


class ContextDeclaration(BaseModel):
    """A declaration. Example: {"work_item_id": "wi_story1", "sub_agent_id": "", "source": "picker"}"""

    model_config = ConfigDict(extra="forbid")

    work_item_id: str = Field(..., min_length=1, max_length=200)
    sub_agent_id: str = Field("", max_length=128)
    source: Literal["picker", "mcp-self"] = "picker"


_STATUS = {"feature_off": 409, "login_required": 403, "bad_source": 422, "bad_sub_agent": 422, "unknown_work_item": 404}


async def _tmux_name(request: Request, session_id: str) -> str:
    manager = request.app.state.session_manager
    refuse_remote(manager, session_id, "the argent work context")
    info = await manager.get_session_info(session_id)
    if info is None or not info.tmux_session:
        raise HTTPException(status_code=404, detail={"code": "session_not_found", "message": f"No session with id {session_id!r}"})
    return str(info.tmux_session)


@router.get("/sessions/{session_id}/context")
async def get_context(request: Request, session_id: str) -> Dict[str, Any]:
    """The session's work context. Inputs: session_id.

    Output: {enabled, session_id (Argent's id for it), agents: [{sub_agent_id, work_item_id, effective_work_item_id, ts, source}], queued (rows not yet
    acknowledged by Argent)}; with the feature off or nobody logged in the list is empty.
    Example: GET /api/v1/argent/sessions/ses_abc/context
    """
    name = await _tmux_name(request, session_id)
    if not feature_on():
        return {"enabled": False, "session_id": None, "agents": [], "queued": 0}
    tenant = await run_in_threadpool(work_items.current_tenant)
    if not tenant:
        return {"enabled": True, "session_id": None, "agents": [], "queued": 0}
    ref = await run_in_threadpool(session_ref.ref_for_name, tenant, name)
    declared = await run_in_threadpool(timeline.current, tenant, ref)
    agents = [{"sub_agent_id": d["sub_agent_id"], "work_item_id": d["work_item_id"], "effective_work_item_id": timeline.effective(declared, d["sub_agent_id"]),
               "ts": d["ts"], "source": d["reason"]} for d in declared]
    return {"enabled": True, "session_id": ref, "agents": agents, "queued": await run_in_threadpool(timeline.backlog, tenant)}


@router.put("/sessions/{session_id}/context")
async def put_context(request: Request, session_id: str, body: ContextDeclaration) -> Dict[str, Any]:
    """Declare the item an agent of the session is on. Output: {session_id, sub_agent_id, work_item_id, ts, reason, changed}.

    Raises: 404 ``session_not_found`` or ``unknown_work_item``, 409 ``feature_off``, 403 ``login_required``, 422 for a bad sub-agent id.
    Example: PUT /api/v1/argent/sessions/ses_abc/context {"work_item_id": "wi_story1"}
    """
    name = await _tmux_name(request, session_id)
    try:
        return await declare_module.declare(name, body.work_item_id, body.source, body.sub_agent_id)
    except declare_module.DeclareError as exc:
        raise refusal_error(exc, status=_STATUS.get(exc.code, 400), extra={"message": exc.message}) from None
